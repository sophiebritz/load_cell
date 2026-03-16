"""
HX711 Logger — 3-Test Mode
---------------------------
Run in VS Code terminal (NOT PlatformIO serial monitor).

Install deps once:
    pip install pyserial matplotlib

Run:
    python hx711_logger.py

Flow:
    ── Done ONCE at startup ──────────────────────────────────
    1.  SPACE  → friction reading 1 (load cell on moving board, no thrust)
                 SPACE to stop
    2.  SPACE  → friction reading 2  →  SPACE to stop
    3.  SPACE  → friction reading 3  →  SPACE to stop
                 avg of all 3 stored as friction_offset

    ── Repeated for each named session ───────────────────────
    4.  SPACE  → enter name details
    5.  SPACE  → start test 1  →  SPACE to stop
    6.  SPACE  → start test 2  →  SPACE to stop
    7.  SPACE  → start test 3  →  SPACE to stop
                 saves 8 files in named folder

Every recorded value has friction_offset subtracted.
"""

import serial
import serial.tools.list_ports
import threading
import time
import sys
import os

# ── Section 1: Config ────────────────────────────────────────
SERIAL_PORT       = None
BAUD_RATE         = 115200
SAVE_DIR          = os.path.dirname(os.path.abspath(__file__))
NUM_FRICTION      = 3
NUM_TESTS         = 3

# Newton calibration constant — from calibrate_newton.py
COUNTS_PER_NEWTON = 2336.0

# ── Section 2: Global state ──────────────────────────────────
phase             = "friction_idle"

friction_runs     = []
friction_current  = []
friction_test     = 0
friction_offset   = 0.0

record_start_ts   = None
current_test      = 0
current_run       = []
all_runs          = []

name_base         = ""
folder_path       = ""

ser               = None
stop_event        = threading.Event()

# ── Section 2b: Display pause flag ───────────────────────────
# When True the serial thread stops writing \r live updates.
# This prevents the live readout from overwriting or garbling
# y/n prompts and input() lines while the user is typing.
display_paused    = False

COLORS = ["#378ADD", "#e07b3a", "#2ca05a"]

# ── Section 3: Port detection ────────────────────────────────
def find_port():
    ports = serial.tools.list_ports.comports()
    for p in ports:
        desc = (p.description or "").lower()
        hwid  = (p.hwid or "").lower()
        if any(x in desc for x in ["usbmodem", "cp210", "ch340", "esp32", "ftdi", "jtag"]):
            return p.device
        if "usb" in hwid:
            return p.device
    return ports[0].device if ports else None

# ── Section 4: Unique folder creation ────────────────────────
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
def save_run_csv(run, path):
    with open(path, "w") as f:
        f.write("index,time_s,value,newtons,raw_value\n")
        f.write(f"# friction_offset={friction_offset:.1f}  counts_per_newton={COUNTS_PER_NEWTON}\n")
        for i, (t, v) in enumerate(run):
            raw     = v + friction_offset
            newtons = v / COUNTS_PER_NEWTON
            f.write(f"{i+1},{t:.3f},{v:.0f},{newtons:.4f},{raw:.0f}\n")
    print(f"  💾 {os.path.basename(path)}")

# ── Section 7: Save individual run PNG ───────────────────────
def save_run_png(run, path, test_num, label):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        times  = [r[0] for r in run]
        values = [r[1] for r in run]
        mn, mx = min(values), max(values)
        avg    = sum(values) / len(values)
        data_range = mx - mn if mx != mn else 100
        pad    = max(data_range * 0.15, 50)

        peak_idx = values.index(min(values))
        peak_t, peak_v = times[peak_idx], values[peak_idx]

        col = COLORS[test_num - 1]
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(times, values, linewidth=1.4, color=col, label=f"Test {test_num}")
        ax.fill_between(times, values, 0, alpha=0.08, color=col)
        ax.axhline(0,   color="#aaa", linewidth=0.7, linestyle=":",  label="zero")
        ax.axhline(avg, color="#555", linewidth=0.9, linestyle="--", label=f"avg {avg:+.1f}")

        ax.plot(peak_t, peak_v, "o", color=col, markersize=7, zorder=5)
        x_span = times[-1] - times[0] if len(times) > 1 else 1
        ax.annotate(
            f"peak {peak_v:+.0f}",
            xy=(peak_t, peak_v),
            xytext=(peak_t + x_span * 0.03, peak_v - pad * 0.3),
            fontsize=8, color=col,
            arrowprops=dict(arrowstyle="-", color=col, lw=0.8)
        )

        ax.set_ylim(mn - pad, mx + pad)
        ax.set_xlim(left=0, right=max(times) * 1.05)
        ax.legend(fontsize=9)
        ax.set_xlabel("Time (s)", fontsize=10)
        ax.set_ylabel("ADC (friction zeroed)", fontsize=10)
        ax.set_title(
            f"{label}  —  Test {test_num}  |  {len(run)} pts  |  "
            f"min {mn:+.0f}  max {mx:+.0f}  avg {avg:+.1f}\n"
            f"friction offset: {friction_offset:,.0f}",
            fontsize=10
        )
        ax.grid(True, alpha=0.15)
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"  📊 {os.path.basename(path)}")
    except ImportError:
        print("  ⚠️  matplotlib not installed.")

# ── Section 8: Save combined PNG ─────────────────────────────
def save_combined_png(runs, path, label):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(14, 6))
        peaks, all_values = [], []

        for idx, run in enumerate(runs):
            times  = [r[0] for r in run]
            values = [r[1] for r in run]
            col    = COLORS[idx]
            n      = idx + 1

            peak_idx = values.index(min(values))
            peak_t, peak_v = times[peak_idx], values[peak_idx]
            peaks.append(peak_v)
            all_values.extend(values)

            ax.plot(times, values, linewidth=1.3, color=col, alpha=0.85,
                    label=f"Test {n}  (peak {peak_v:+.0f})")
            ax.fill_between(times, values, 0, alpha=0.05, color=col)
            ax.plot(peak_t, peak_v, "o", color=col, markersize=6, zorder=5)
            ax.annotate(f"T{n}", xy=(peak_t, peak_v),
                        xytext=(peak_t + 0.05, peak_v),
                        fontsize=8, color=col, va="top")

        avg_max = sum(peaks) / len(peaks)
        x_right = max(r[-1][0] for r in runs)
        ax.axhline(avg_max, color="#cc3333", linewidth=1.6, linestyle="-.",
                   label=f"avg peak  {avg_max:+.1f}", zorder=4)
        ax.text(x_right * 0.99,
                avg_max - (max(all_values) - min(all_values)) * 0.03,
                f"avg peak\n{avg_max:+.1f}",
                fontsize=8, color="#cc3333", ha="right", va="top")

        ax.axhline(0, color="#aaa", linewidth=0.7, linestyle=":", label="zero")

        mn, mx = min(all_values), max(all_values)
        pad = max((mx - mn) * 0.18, 50)
        ax.set_ylim(mn - pad, mx + pad)
        ax.set_xlim(left=0, right=x_right * 1.05)
        ax.legend(fontsize=9, loc="upper left")
        ax.set_xlabel("Time (s)", fontsize=10)
        ax.set_ylabel("ADC (friction zeroed)", fontsize=10)
        ax.set_title(
            f"{label}  —  All 3 Tests  |  Avg peak: {avg_max:+.1f}  "
            f"(T1: {peaks[0]:+.0f}  T2: {peaks[1]:+.0f}  T3: {peaks[2]:+.0f})\n"
            f"friction offset: {friction_offset:,.0f}",
            fontsize=10
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
    peaks, peak_times = [], []
    for run in runs:
        values = [r[1] for r in run]
        times  = [r[0] for r in run]
        idx    = values.index(min(values))
        peaks.append(values[idx])
        peak_times.append(times[idx])

    avg_max    = sum(peaks) / len(peaks)
    avg_peak_t = sum(peak_times) / len(peak_times)

    with open(path, "w") as f:
        f.write("metric,test1,test2,test3,average\n")
        f.write("peak_value,"  + ",".join(f"{p:.1f}" for p in peaks) + f",{avg_max:.1f}\n")
        f.write("peak_time_s," + ",".join(f"{t:.3f}" for t in peak_times) + f",{avg_peak_t:.3f}\n")
        f.write(f"\nlabel,{label}\n")
        f.write(f"friction_offset,{friction_offset:.1f}\n")
        f.write(f"counts_per_newton,{COUNTS_PER_NEWTON:.1f}\n")
    print(f"  💾 {os.path.basename(path)}")

# ── Section 10: Finalise — save all 8 files ──────────────────
def finalise():
    n, fp = name_base, folder_path
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
    global phase
    global friction_runs, friction_current, friction_test, friction_offset
    global record_start_ts, current_test, current_run, all_runs
    global name_base, folder_path
    global display_paused

    import tty, termios
    fd  = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    def raw():    tty.setraw(fd)
    def cooked(): termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def ask_yn(prompt):
        """
        Safely asks a y/n question without the serial thread
        garbling the output.

        Steps:
          1. Sets display_paused = True so serial thread stops
             writing \r updates immediately.
          2. Switches terminal to cooked mode so input() works.
          3. Prints a clean newline so prompt appears on its own line.
          4. Loops until user types y or n and presses Enter.
          5. Restores raw mode and clears display_paused.
        """
        global display_paused
        display_paused = True
        cooked()
        sys.stdout.write("\n")
        sys.stdout.flush()
        while True:
            ans = input(prompt).strip().lower()
            if ans in ("y", "n"):
                break
        raw()
        display_paused = False
        return ans

    print("\n" + "=" * 46)
    print("  FRICTION CALIBRATION  (done once)")
    print("=" * 46)
    print("  Mount the load cell on the moving board.")
    print("  No thrust — just the board moving freely.")
    print(f"  You will take {NUM_FRICTION} readings.")
    print("\n  Press SPACE to start friction reading 1.\n")

    try:
        raw()
        while not stop_event.is_set():
            ch = sys.stdin.read(1)

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

            # ══ FRICTION PHASES ══════════════════════════════

            if phase == "friction_idle":
                friction_test   += 1
                friction_current = []
                record_start_ts  = time.time()
                phase            = "friction_recording"
                print(f"\n  ● Friction reading {friction_test}/{NUM_FRICTION} — press SPACE to stop.\n")

            elif phase == "friction_recording":
                print(f"\n  ■ Friction {friction_test} done — {len(friction_current)} samples.")
                ans = ask_yn("  Accept this reading? (y/n): ")

                if ans == "n":
                    friction_current = []
                    record_start_ts  = time.time()
                    phase            = "friction_recording"
                    print(f"\n  ↩  Repeating friction reading {friction_test}/{NUM_FRICTION} — press SPACE to stop.\n")
                else:
                    friction_runs.append(list(friction_current))

                    if friction_test < NUM_FRICTION:
                        phase = "friction_idle"
                        print(f"  Press SPACE to start friction reading {friction_test + 1}/{NUM_FRICTION}.\n")
                    else:
                        all_friction_vals = [v for run in friction_runs for _, v in run]
                        friction_offset   = sum(all_friction_vals) / len(all_friction_vals)
                        phase             = "idle"
                        cooked()
                        print(f"\n  ✅ Friction calibration complete.")
                        print(f"     Friction offset = {friction_offset:,.0f}  ({len(all_friction_vals)} samples)\n")
                        print("  This offset will be subtracted from ALL test readings.")
                        print("─" * 46)
                        print("\n  Press SPACE to begin a test session.\n")
                        raw()

            # ══ SESSION PHASES ════════════════════════════════

            elif phase == "idle":
                display_paused = True
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
                print(f"  Press SPACE to start test 1/{NUM_TESTS}.")
                print("─" * 46 + "\n")
                raw()
                display_paused = False
                phase = "ready"

            elif phase == "ready":
                current_test    += 1
                current_run      = []
                record_start_ts  = time.time()
                phase            = "recording"
                print(f"\n  ● Test {current_test}/{NUM_TESTS} — press SPACE to stop.\n")

            elif phase == "recording":
                print(f"\n  ■ Test {current_test} done — {len(current_run)} readings.")
                ans = ask_yn("  Accept this reading? (y/n): ")

                if ans == "n":
                    current_run     = []
                    record_start_ts = time.time()
                    phase           = "recording"
                    print(f"\n  ↩  Repeating test {current_test}/{NUM_TESTS} — press SPACE to stop.\n")
                else:
                    all_runs.append(list(current_run))

                    if current_test < NUM_TESTS:
                        phase = "ready"
                        print(f"  Press SPACE to start test {current_test + 1}/{NUM_TESTS}.\n")
                    else:
                        phase = "idle"
                        cooked()
                        finalise()
                        raw()
                        print("  Press SPACE for a new session, Ctrl+C to quit.\n")

    finally:
        cooked()

# ── Section 12: Serial reader thread ─────────────────────────
def serial_thread():
    global ser, phase
    global friction_current, current_run

    port = SERIAL_PORT or find_port()
    if not port:
        print("❌ No serial port found.")
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
                # Only print ESP32 non-data messages when display is free
                if not display_paused:
                    sys.stdout.write(f"\n  ESP32: {line}\n")
                    sys.stdout.flush()
                continue

            now = time.time()

            # ── Friction recording ────────────────────────────
            if phase == "friction_recording":
                elapsed = now - record_start_ts
                friction_current.append((elapsed, float(raw_val)))
                if not display_paused:
                    sys.stdout.write(
                        f"\r  Friction {friction_test}  [{len(friction_current):>5} pts]  "
                        f"raw: {raw_val:>12,}   "
                    )
                    sys.stdout.flush()

            # ── Test recording ────────────────────────────────
            elif phase == "recording":
                elapsed = now - record_start_ts
                zeroed  = raw_val - friction_offset
                current_run.append((elapsed, zeroed))
                if not display_paused:
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
    print(f"  Calibration: {COUNTS_PER_NEWTON:.1f} counts/N")
    print("=" * 46)

    st = threading.Thread(target=serial_thread, daemon=True)
    st.start()
    time.sleep(1.5)

    try:
        keyboard_thread()
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        stop_event.set()
        if ser and ser.is_open:
            ser.close()
        print("Goodbye.")  