"""
HX711 Newton Calibration
-------------------------

Steps:
    1. Script connects to ESP32
    2. Tares for 3 seconds (load cell UNLOADED)
    3. You apply exactly 1N with your Newton meter
    4. Press SPACE — script records 3 seconds of readings
    5. Prints the COUNTS_PER_NEWTON constant to paste into main code

Install deps once:
    pip install pyserial

Run:
    python calibrate_newton.py
"""

import serial
import serial.tools.list_ports
import threading
import time
import sys

# ── Section 1: Config ────────────────────────────────────────
BAUD_RATE        = 115200
TARE_DURATION    = 3.0        # seconds to tare (unloaded)
SAMPLE_DURATION  = 3.0        # seconds to sample at 1N
KNOWN_FORCE_N    = 1.0        # the force you are applying (Newtons)

# ── Section 2: Global state ──────────────────────────────────
phase            = "waiting"  # waiting → taring → armed → sampling → done
tare_readings    = []
tare_offset      = 0.0
sample_readings  = []
stop_event       = threading.Event()
ser              = None

# ── Section 3: Port detection ────────────────────────────────
def find_port():
    """
    Scans all COM ports and returns the first ESP32/USB-serial device found.
    Checks description and hardware ID for known chip names.
    """
    ports = serial.tools.list_ports.comports()
    for p in ports:
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        if any(x in desc for x in ["usbmodem", "cp210", "ch340", "esp32", "ftdi", "jtag"]):
            return p.device
        if "usb" in hwid:
            return p.device
    return ports[0].device if ports else None

# ── Section 4: Parse raw value from serial line ──────────────
def parse_raw(line):
    """
    Reads a line from serial and extracts the integer ADC value.
    Supports two formats:
        DATA:millis:value   (from main HX711 logger firmware)
        Raw reading: value  (from simple test firmware)
    Returns None if line is not a data line.
    """
    if line.startswith("DATA:"):
        parts = line.split(":")
        if len(parts) == 3:
            try:
                return int(parts[2])
            except ValueError:
                pass
    elif line.startswith("Raw reading:"):
        try:
            return int(line.replace("Raw reading:", "").strip())
        except ValueError:
            pass
    return None

# ── Section 5: Serial reader thread ─────────────────────────
def serial_thread():
    """
    Runs in background. Reads raw ADC values from ESP32 over serial.
    Depending on current phase:
        taring   → collects readings to compute tare offset
        sampling → collects readings at known 1N load
    Auto-advances phase when durations are reached.
    """
    global ser, phase, tare_offset

    port = find_port()
    if not port:
        print("No serial port found. Is your ESP32 plugged in?")
        stop_event.set()
        return

    print(f" Connecting to {port} at {BAUD_RATE} baud...")
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=1)
        print(f" Connected to {port}\n")
    except Exception as e:
        print(f"Could not open {port}: {e}")
        print("   → Close PlatformIO serial monitor first.")
        stop_event.set()
        return

    tare_start = None
    sample_start = None

    while not stop_event.is_set():
        try:
            line    = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            raw_val = parse_raw(line)
            if raw_val is None:
                # Non-data line from ESP32 — print it for info
                print(f"  ESP32: {line}")
                continue

            now = time.time()

            # ── Phase: taring ────────────────────────────────
            if phase == "taring":
                if tare_start is None:
                    tare_start = now

                elapsed   = now - tare_start
                remaining = max(0.0, TARE_DURATION - elapsed)
                tare_readings.append(raw_val)

                sys.stdout.write(
                    f"\r  ⏱  Taring... {remaining:.1f}s  "
                    f"({len(tare_readings)} samples)  raw: {raw_val:>12,}   "
                )
                sys.stdout.flush()

                # Tare complete — compute offset and wait for SPACE
                if elapsed >= TARE_DURATION:
                    tare_offset = sum(tare_readings) / len(tare_readings)
                    phase       = "armed"
                    print(
                        f"\n\n  ✅ Tare complete."
                        f"\n     Tare offset = {tare_offset:,.0f}  "
                        f"({len(tare_readings)} samples)\n"
                    )
                    print("─" * 46)
                    print("  Now apply exactly 1N with your Newton meter.")
                    print("  Hold it steady, then press SPACE to sample.\n")

            # ── Phase: sampling at 1N ────────────────────────
            elif phase == "sampling":
                if sample_start is None:
                    sample_start = now

                elapsed   = now - sample_start
                remaining = max(0.0, SAMPLE_DURATION - elapsed)

                # Subtract tare so we see net force counts only
                zeroed = raw_val - tare_offset
                sample_readings.append(zeroed)

                sys.stdout.write(
                    f"\r   Sampling... {remaining:.1f}s  "
                    f"({len(sample_readings)} samples)  "
                    f"zeroed: {zeroed:>+10.0f}   "
                )
                sys.stdout.flush()

                # Sampling complete — calculate and print result
                if elapsed >= SAMPLE_DURATION:
                    phase = "done"
                    avg_counts = sum(sample_readings) / len(sample_readings)
                    counts_per_newton = avg_counts / KNOWN_FORCE_N

                    print(f"\n\n{'=' * 46}")
                    print(f"  CALIBRATION COMPLETE")
                    print(f"{'=' * 46}")
                    print(f"  Known force applied : {KNOWN_FORCE_N} N")
                    print(f"  Tare offset         : {tare_offset:,.0f} counts")
                    print(f"  Avg counts at 1N    : {avg_counts:,.0f} counts")
                    print(f"  Samples taken       : {len(sample_readings)}")
                    print(f"{'─' * 46}")
                    print(f"\n  ┌─────────────────────────────────────┐")
                    print(f"  │  COUNTS_PER_NEWTON = {counts_per_newton:>14,.1f}  │")
                    print(f"  └─────────────────────────────────────┘")
                    print(f"\n  Paste this into your main code:")
                    print(f"\n      COUNTS_PER_NEWTON = {counts_per_newton:.1f}\n")
                    print(f"  To convert readings: force_N = zeroed_value / COUNTS_PER_NEWTON\n")
                    stop_event.set()

        except serial.SerialException:
            print("\n⚠️  Serial disconnected.")
            stop_event.set()
            break

# ── Section 6: Keyboard thread ───────────────────────────────
def keyboard_thread():
    """
    Waits for SPACE bar press to advance through phases:
        armed    → sampling   (start 3s sample at 1N)
    Ctrl+C exits at any time.
    """
    global phase

    # Wait for serial to connect before starting keyboard loop
    time.sleep(2.0)

    if stop_event.is_set():
        return

    # Auto-start taring immediately
    print("  Starting 3-second tare — keep load cell UNLOADED...\n")
    phase = "taring"

    try:
        import tty, termios
        fd  = sys.stdin.fileno()
        old = termios.tcgetattr(fd)

        def raw():    tty.setraw(fd)
        def cooked(): termios.tcsetattr(fd, termios.TCSADRAIN, old)

        raw()
        try:
            while not stop_event.is_set():
                ch = sys.stdin.read(1)

                # Ctrl+C to quit
                if ch == "\x03":
                    stop_event.set()
                    break

                # SPACE to start sampling
                if ch == " " and phase == "armed":
                    phase = "sampling"
                    print("\n  ● Sampling 1N reading...\n")

        finally:
            cooked()

    except ImportError:
        # Windows fallback — use input() instead of raw tty
        while not stop_event.is_set():
            if phase == "armed":
                input()          # press Enter on Windows
                phase = "sampling"
                print("\n  ● Sampling 1N reading...\n")
            time.sleep(0.05)

# ── Section 7: Main ──────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 46)
    print("  HX711 Newton Calibration")
    print("=" * 46)
    print("  This will:")
    print("  1. Tare for 3s  (unloaded)")
    print("  2. You apply 1N with Newton meter")
    print("  3. Press SPACE  → samples for 3s")
    print("  4. Prints COUNTS_PER_NEWTON constant")
    print("=" * 46 + "\n")

    # Start serial reader in background
    st = threading.Thread(target=serial_thread, daemon=True)
    st.start()

    try:
        keyboard_thread()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        if ser and ser.is_open:
            ser.close()
        print("Goodbye.")