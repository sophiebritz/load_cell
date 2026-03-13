"""
HX711 Logger — 3-Test Mode
---------------------------
Run in VS Code terminal (NOT PlatformIO serial monitor).

Install deps once:
    pip install pyserial matplotlib

Run:
    python hx711_logger.py

Flow:
    1.  SPACE  → enter name details
    2.  SPACE  → 1s calibration (load cell unloaded)
    3.  SPACE  → start test 1  →  SPACE to stop
    4.  SPACE  → start test 2  →  SPACE to stop
    5.  SPACE  → start test 3  →  SPACE to stop
    →   saves folder with 8 files

Saves folder <name>/ containing:
    <n>_1.csv / _2.csv / _3.csv      per-test raw data (time starts at 0)
    <n>_1.png / _2.png / _3.png      per-test graphs (zoomed y-axis)
    <n>_combined.png                 all 3 overlaid + avg max line
    <n>_avg_max.csv                  peak summary table
"""

import serial
import serial.tools.list_ports
import threading
import time
import sys
import os

# ── Section 1: Config ────────────────────────────────────────
SERIAL_PORT   = None
BAUD_RATE     = 115200
SAVE_DIR      = os.path.dirname(os.path.abspath(__file__))
TARE_DURATION = 1.0          # 1 second calibration
NUM_TESTS     = 3

# ── Section 2: Global state ──────────────────────────────────
# phase drives the state machine:
#   idle → named → taring → ready → recording → (×3) → idle
phase          = "idle"

tare_readings  = []           # raw ADC samples during calibration window
tare_offset    = 0.0          # mean of tare_readings, subtracted from all data
tare_start_ts  = None         # wall-clock when tare began

record_start_ts = None        # wall-clock when current test recording began
                              # each test gets its OWN start time so t=0 is correct

current_test   = 0            # 1, 2, or 3
current_run    = []           # (elapsed_s, zeroed_value) for active test
all_runs       = []           # list of 3 completed run lists

name_base      = ""           # e.g. "staggered_45_reverse"
folder_path    = ""           # full path to output folder

ser            = None
stop_event     = threading.Event()

COLORS = ["#378ADD", "#e07b3a", "#2ca05a"]   # blue, orange, green per test

# ── Section 3: Port detection ────────────────────────────────
def find_port():
    ports = serial.tools.list_ports.comports()
    for p in ports:
        desc = (p.description or "").lower()
        hwid  = (p.hwid or "").lower()
        if any(x in desc for x in ["usbmodem", "cp210", "ch340", "esp32", "ftdi"]):
            return p.device
        if "usb" in hwid:
            return p.device
    return ports[0].device if ports else None

# ── Section 4: Unique folder creation ────────────────────────
# Appends _set2, _set3 etc. if folder already exists.
def make_folder(base):
    path = os.path.join(SAVE_DIR, base)
    if not os.path.exists(path):
        os.makedirs(path)
        return path, base
    n = 2
    while os.path.exists(os.path.join(SAVE_DIR, f"{base}_set{n}")):
        n += 1
    new_name = f"{base}_set{n}"
    new_path = os.path.join(SAVE_DIR, new_name)
    os.makedirs(new_path)
    return new_path, new_name

# ── Section 5: Parse raw value from serial line ──────────────
# Handles both firmware formats:
#   New: "DATA:<timestamp_ms>:<value>"
#   Old: "Raw reading: <value>"
def parse_raw(line):
    if line.startswith("DATA:"):
        parts = line.split(":")
        if len(parts) == 3:
            try: return int(parts[2])
            except ValueError: pass
    elif line.startswith("Raw reading:"):
        try: return int(line.replace("Raw reading:", "").strip())
        except ValueError: pass
    return None

# ── Section 6: Save individual run CSV ───────────────────────
# Time column starts at 0 for every test (uses record_start_ts offset).
def save_run_csv(run, path):
    with open(path, "w") as f:
        f.write("index,time_s,zeroed_value,raw_value\n")
        for i, (t, v) in enumerate(run):
            f.write(f"{i+1},{t:.3f},{v:.0f},{v + tare_offset:.0f}\n")
    print(f"  💾 {os.path.basename(path)}")

# ── Section 7: Save individual run PNG ───────────────────────
# Y-axis zooms to actual data range ± padding.
# X-axis starts at 0 (time since test start).
def save_run_png(run, path, test_num, label):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        times  = [r[0] for r in run]
        values = [r[1] for r in run]

        mn  = min(values)
        mx  = max(values)
        avg = sum(values) / len(values)

        # Y-axis: zoom to data range + 15% padding, minimum ±50
        data_range = mx - mn if mx != mn else 100
        pad = max(data_range * 0.15, 50)

        # Peak point (largest absolute value)
        peak_idx = values.index(max(values, key=abs))
        peak_t   = times[peak_idx]
        peak_v   = values[peak_idx]

        col = COLORS[test_num - 1]
        fig, ax = plt.subplots(figsize=(12, 5))

        ax.plot(times, values, linewidth=1.4, color=col, label=f"Test {test_num}")
        ax.fill_between(times, values, 0, alpha=0.08, color=col)
        ax.axhline(0,   color="#aaa", linewidth=0.7, linestyle=":",  label="zero (tare)")
        ax.axhline(avg, color="#555", linewidth=0.9, linestyle="--", label=f"avg {avg:+.1f}")

        # Peak dot + label
        ax.plot(peak_t, peak_v, "o", color=col, markersize=7, zorder=5)
        x_span = times[-1] - times[0] if len(times) > 1 else 1
        ax.annotate(
            f"peak {peak_v:+.0f}",
            xy=(peak_t, peak_v),
            xytext=(peak_t + x_span * 0.03, peak_v + pad * 0.3),
            fontsize=8, color=col,
            arrowprops=dict(arrowstyle="-", color=col, lw=0.8)
        )

        ax.set_ylim(mn - pad, mx + pad)
        ax.set_xlim(left=0, right=max(times) * 1.05)
        ax.legend(fontsize=9)
        ax.set_xlabel("Time (s)", fontsize=10)
        ax.set_ylabel("Zeroed ADC", fontsize=10)
        ax.set_title(
            f"{label}  —  Test {test_num}  |  {len(run)} pts  |  "
            f"min {mn:+.0f}  max {mx:+.0f}  avg {avg:+.1f}",
            fontsize=11
        )
        ax.grid(True, alpha=0.15)
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"  📊 {os.path.basename(path)}")

    except ImportError:
        print("  ⚠️  matplotlib not installed. Run: pip install matplotlib")

# ── Section 8: Save combined PNG ─────────────────────────────
# All 3 tests overlaid with individual peak markers.
# Red dash-dot line = average of the 3 peak values.
def save_combined_png(runs, path, label):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(14, 6))

        peaks      = []
        all_values = []

        for idx, run in enumerate(runs):
            times  = [r[0] for r in run]
            values = [r[1] for r in run]
            col    = COLORS[idx]
            n      = idx + 1

            peak_idx = values.index(max(values, key=abs))
            peak_t   = times[peak_idx]
            peak_v   = values[peak_idx]
            peaks.append(peak_v)
            all_values.extend(values)

            ax.plot(times, values, linewidth=1.3, color=col, alpha=0.85,
                    label=f"Test {n}  (peak {peak_v:+.0f})")
            ax.fill_between(times, values, 0, alpha=0.05, color=col)

            # Per-test peak dot
            ax.plot(peak_t, peak_v, "o", color=col, markersize=6, zorder=5)
            ax.annotate(
                f"T{n}",
                xy=(peak_t, peak_v),
                xytext=(peak_t + 0.05, peak_v),
                fontsize=8, color=col,
                va="bottom"
            )

        # Average max horizontal line
        avg_max  = sum(peaks) / len(peaks)
        x_right  = max(r[-1][0] for r in runs)

        ax.axhline(avg_max, color="#cc3333", linewidth=1.6, linestyle="-.",
                   label=f"avg max  {avg_max:+.1f}", zorder=4)

        # Annotation on right edge
        ax.text(x_right * 0.99, avg_max + (max(all_values) - min(all_values)) * 0.03,
                f"avg max\n{avg_max:+.1f}",
                fontsize=8, color="#cc3333", ha="right", va="bottom")

        ax.axhline(0, color="#aaa", linewidth=0.7, linestyle=":", label="zero")

        mn  = min(all_values)
        mx  = max(all_values)
        data_range = mx - mn if mx != mn else 100
        pad = max(data_range * 0.18, 50)

        ax.set_ylim(mn - pad, mx + pad)
        ax.set_xlim(left=0, right=x_right * 1.05)
        ax.legend(fontsize=9, loc="upper left")
        ax.set_xlabel("Time (s)", fontsize=10)
        ax.set_ylabel("Zeroed ADC", fontsize=10)
        ax.set_title(
            f"{label}  —  All 3 Tests  |  "
            f"Avg peak: {avg_max:+.1f}  "
            f"(T1: {peaks[0]:+.0f}  T2: {peaks[1]:+.0f}  T3: {peaks[2]:+.0f})",
            fontsize=11
        )
        ax.grid(True, alpha=0.12)
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"  📊 {os.path.basename(path)}")

    except ImportError:
        print("  ⚠️  matplotlib not installed.")

# ── Section 9: Save avg max CSV ──────────────────────────────
def save_avg_max_csv(runs, path, label):
    peaks      = []
    peak_times = []
    for run in runs:
        values   = [r[1] for r in run]
        times    = [r[0] for r in run]
        peak_idx = values.index(max(values, key=abs))
        peaks.append(values[peak_idx])
        peak_times.append(times[peak_idx])

    avg_max    = sum(peaks) / len(peaks)
    avg_peak_t = sum(peak_times) / len(peak_times)

    with open(path, "w") as f:
        f.write("metric,test1,test2,test3,average\n")
        f.write("peak_zeroed_value," + ",".join(f"{p:.1f}" for p in peaks) + f",{avg_max:.1f}\n")
        f.write("peak_time_s,"      + ",".join(f"{t:.3f}" for t in peak_times) + f",{avg_peak_t:.3f}\n")
        f.write(f"\nlabel,{label}\n")
        f.write(f"tare_offset,{tare_offset:.1f}\n")
    print(f"  💾 {os.path.basename(path)}")

# ── Section 10: Finalise — save all 8 files ──────────────────
def finalise():
    n  = name_base
    fp = folder_path
    print(f"\n  ── Saving to: {os.path.basename(fp)}/\n")

    for i, run in enumerate(all_runs):
        t = i + 1
        save_run_csv(run, os.path.join(fp, f"{n}_{t}.csv"))
        save_run_png(run, os.path.join(fp, f"{n}_{t}.png"), t, n)

    save_combined_png(all_runs, os.path.join(fp, f"{n}_combined.png"), n)
    save_avg_max_csv(all_runs,  os.path.join(fp, f"{n}_avg_max.csv"),  n)

    print(f"\n  ✅ 8 files saved in {os.path.basename(fp)}/\n")

# ── Section 11: Keyboard / state machine ─────────────────────
def keyboard_thread():
    global phase, tare_readings, tare_offset, tare_start_ts
    global record_start_ts, current_test, current_run, all_runs
    global name_base, folder_path

    import tty, termios
    fd  = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    def raw():    tty.setraw(fd)
    def cooked(): termios.tcsetattr(fd, termios.TCSADRAIN, old)

    print("\n  Press SPACE to begin.\n")

    try:
        raw()
        while not stop_event.is_set():
            ch = sys.stdin.read(1)

            # Ctrl+C — save whatever we have and quit
            if ch == "\x03":
                if phase == "recording" and current_run:
                    all_runs.append(list(current_run))
                if all_runs:
                    cooked()
                    print("\n  Interrupted — saving completed tests...")
                    finalise()
                stop_event.set()
                break

            if ch != " ":
                continue

            # ── idle → ask for details ────────────────────────
            if phase == "idle":
                cooked()
                print("\n" + "─" * 46)
                print("  New 3-test session")
                print("─" * 46)
                model     = input("  Model / bit name   : ").strip().replace(" ", "_") or "model"
                angle     = input("  Angle              : ").strip().replace(" ", "_") or "0"
                direction = input("  Direction (forward/reverse): ").strip().lower()
                if direction not in ("forward", "reverse"):
                    direction = "forward"

                base                   = f"{model}_{angle}_{direction}"
                folder_path, name_base = make_folder(base)
                all_runs               = []
                current_test           = 0

                print(f"\n  Folder  → {name_base}/")
                print(f"  Press SPACE when ready to calibrate (load cell UNLOADED).")
                print("─" * 46 + "\n")
                raw()
                phase = "named"

            # ── named → begin 1s tare ─────────────────────────
            elif phase == "named":
                tare_readings  = []
                tare_offset    = 0.0
                tare_start_ts  = time.time()
                phase          = "taring"
                print(f"\n  ⏱  Calibrating {TARE_DURATION:.0f}s — hold still...\n")

            # ── pre_tare → begin calibration for next test ──────
            elif phase == "pre_tare":
                tare_readings  = []
                tare_offset    = 0.0
                tare_start_ts  = time.time()
                phase          = "taring_next"
                print(f"\n  ⏱  Calibrating {TARE_DURATION:.0f}s — hold still...\n")

            # ── ready → start next test ───────────────────────
            elif phase == "ready":
                current_test    += 1
                current_run      = []
                record_start_ts  = time.time()   # ← fresh t=0 for THIS test
                phase            = "recording"
                print(f"\n  ● Test {current_test}/{NUM_TESTS} — press SPACE to stop.\n")

            # ── recording → stop, then re-tare before next test ──
            elif phase == "recording":
                all_runs.append(list(current_run))
                print(f"\n  ■ Test {current_test} stopped — {len(current_run)} readings.")

                if current_test < NUM_TESTS:
                    print(f"  Press SPACE to calibrate then start test {current_test + 1}/{NUM_TESTS}.\n")
                    phase = "pre_tare"   # wait for space, then tare, then record
                else:
                    # All 3 done
                    phase = "idle"
                    cooked()
                    finalise()
                    raw()
                    print("  Press SPACE for a new session, Ctrl+C to quit.\n")

    finally:
        cooked()

# ── Section 12: Serial reader thread ─────────────────────────
def serial_thread():
    global ser, phase, tare_offset, tare_start_ts, current_run

    port = SERIAL_PORT or find_port()
    if not port:
        print("❌ No serial port found. Plug in your ESP32-C3.")
        stop_event.set()
        return

    print(f"🔌 Connecting to {port} at {BAUD_RATE} baud...")
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=1)
        print(f"✅ Connected.\n")
    except Exception as e:
        print(f"❌ Could not open {port}: {e}")
        print("   Close PlatformIO serial monitor first.")
        stop_event.set()
        return

    while not stop_event.is_set():
        try:
            line    = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            raw_val = parse_raw(line)

            if raw_val is None:
                # Show unrecognised lines (helps debug firmware mismatches)
                sys.stdout.write(f"\n  ESP32: {line}\n")
                sys.stdout.flush()
                continue

            now = time.time()

            # ── Tare: collect 1s of samples ───────────────────
            if phase in ("taring", "taring_next"):
                elapsed = now - tare_start_ts
                tare_readings.append(raw_val)
                remaining = max(0.0, TARE_DURATION - elapsed)
                sys.stdout.write(
                    f"\r  Calibrating... {remaining:.1f}s  ({len(tare_readings)} samples)   "
                )
                sys.stdout.flush()

                if elapsed >= TARE_DURATION:
                    tare_offset = sum(tare_readings) / len(tare_readings)
                    next_test   = current_test + 1
                    phase       = "ready"
                    sys.stdout.write(
                        f"\r  ✅ Calibrated. Offset = {tare_offset:,.0f}                       \n"
                        f"  Press SPACE to start test {next_test}/{NUM_TESTS}.\n\n"
                    )
                    sys.stdout.flush()

            # ── Recording: store zeroed value, t=0 is test start
            elif phase == "recording":
                elapsed = now - record_start_ts   # ← uses per-test origin
                zeroed  = raw_val - tare_offset
                current_run.append((elapsed, zeroed))
                sys.stdout.write(
                    f"\r  Test {current_test}  [{len(current_run):>5} pts]  "
                    f"zeroed: {zeroed:>+10.0f}  raw: {raw_val:>12,}   "
                )
                sys.stdout.flush()

        except serial.SerialException:
            print("\n⚠️  Serial disconnected.")
            stop_event.set()
            break

# ── Section 13: Main ─────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 46)
    print("  HX711 Logger — 3-Test Mode")
    print("=" * 46)

    st = threading.Thread(target=serial_thread, daemon=True)
    st.start()
    time.sleep(1.5)   # let serial connect before showing prompt

    try:
        keyboard_thread()
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        stop_event.set()
        if ser and ser.is_open:
            ser.close()
        print("Goodbye.")