# HX711 Load Cell Logger — Setup Guide

## What you need

- ESP32-C3 Mini
- HX711 amplifier wired to **DT → GPIO4**, **SCK → GPIO5**
- PlatformIO installed in VS Code
- Python 3 with `pyserial` and `matplotlib`

---

## Step 1 — Open the project in PlatformIO

1. Open **VS Code**
2. Click the **PlatformIO icon** in the left sidebar (the alien head)
3. Click **Open** → **Open Project**
4. Navigate to your `load_cell` project folder and open it

---

## Step 2 — Upload the firmware to the ESP32

1. Open `src/main.cpp` in the editor
2. Click the **→ Upload** button in the bottom toolbar (or press `Ctrl+Shift+U` / `Cmd+Shift+U`)
3. Wait for the upload to finish — you should see `SUCCESS` in the terminal

---

## Step 3 — Close the PlatformIO serial monitor

> **Important:** The serial monitor and the Python logger both need the same USB port. Only one can use it at a time.

- If the serial monitor is open (the plug icon at the bottom), click it to **disconnect**
- Close any terminal tabs inside PlatformIO that show serial output
- You can confirm the port is free if you see no activity in the bottom status bar

---

## Step 4 — Install Python dependencies

Open a **new terminal** (Terminal → New Terminal in VS Code) and run:

```bash
pip install pyserial matplotlib
```

You only need to do this once.

---

## Step 5 — Run the logger

Make sure `hx711_logger.py` is in your project folder, then in the terminal run:

```bash
python hx711_logger.py
```

You should see:

```
==============================================
  HX711 Logger — 3-Test Mode
==============================================
🔌 Connecting to /dev/cu.usbmodem101 at 115200 baud...
✅ Connected.

  Press SPACE to begin.
```

---

## Step 6 — Record a 3-test session

Follow the prompts — everything is controlled with the **Space bar**:

| Press Space | What happens |
|---|---|
| 1st | Enter model name, angle, direction |
| 2nd | 1 second calibration (keep load cell **unloaded**) |
| 3rd | Test 1 starts recording |
| 4th | Test 1 stops |
| 5th | 1 second calibration again (keep load cell **unloaded**) |
| 6th | Test 2 starts recording |
| 7th | Test 2 stops |
| 8th | 1 second calibration again |
| 9th | Test 3 starts recording |
| 10th | Test 3 stops → all files saved automatically |

Press **Ctrl+C** at any point to quit and save whatever has been recorded so far.

---

## Step 7 — Find your output files

A folder is created automatically in the same directory as `hx711_logger.py`, named after your inputs:

```
staggered_non_curved_45_reverse/
├── staggered_non_curved_45_reverse_1.csv
├── staggered_non_curved_45_reverse_2.csv
├── staggered_non_curved_45_reverse_3.csv
├── staggered_non_curved_45_reverse_1.png
├── staggered_non_curved_45_reverse_2.png
├── staggered_non_curved_45_reverse_3.png
├── staggered_non_curved_45_reverse_combined.png
└── staggered_non_curved_45_reverse_avg_max.csv
```

If you run the same name again, a `_set2` folder is created automatically so nothing is overwritten.

---

## Troubleshooting

**"No serial port found"**
→ Make sure the ESP32 is plugged in and the PlatformIO serial monitor is fully closed.

**"Could not open port"**
→ Close the serial monitor in PlatformIO. Only one program can use the port at a time.

**Stuck on "Calibrating..."**
→ The ESP32 firmware may not be uploaded yet. Repeat Step 2, then close the serial monitor before running the Python script.

**Graphs look wrong / flat line**
→ Check the HX711 wiring: DT → GPIO4, SCK → GPIO5, VCC → 3.3V or 5V, GND → GND.