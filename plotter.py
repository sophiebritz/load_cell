"""
plot_results.py
---------------
Reads all test CSV folders in the same directory and produces:
  - One combined PNG per folder (all 3 tests overlaid, in Newtons vs time)
  - One per-test PNG per folder (individual runs)

Drop this script in the same folder that contains your result folders, then run:
    python plot_results.py

All PNGs are saved inside their respective result folders.
"""

import os
import sys
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# ── Config ────────────────────────────────────────────────────
COLORS      = ["#378ADD", "#e07b3a", "#2ca05a"]
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))

# ── Helpers ───────────────────────────────────────────────────

def read_csv(path):
    """
    Reads a run CSV, skipping the comment line that starts with #.
    Returns list of (time_s, newtons) tuples.
    """
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["index"].startswith("#"):
                continue
            try:
                rows.append((float(row["time_s"]), float(row["newtons"])))
            except (ValueError, KeyError):
                continue
    return rows


def y_limits(all_series):
    """
    Returns (ymin, ymax) with 18% padding, always including zero,
    so every chart uses a consistent, readable scale.
    """
    flat = [v for series in all_series for _, v in series]
    mn, mx = min(flat), max(flat)
    # always show zero
    mn = min(mn, 0)
    mx = max(mx, 0)
    pad = max((mx - mn) * 0.18, 0.05)
    return mn - pad, mx + pad


def style_ax(ax):
    """Applies consistent grid / spine styling to an axis."""
    ax.grid(True, alpha=0.18, linewidth=0.7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.2f N"))


def human_label(folder_name):
    """
    Turns 'Simple_Angled_Stalk_45_reverse_set2' into a readable title.
    Replaces underscores with spaces.
    """
    return folder_name.replace("_", " ")


# ── Per-test individual PNGs ──────────────────────────────────

def plot_individual(run, test_num, folder_path, folder_name, counts_per_newton):
    times   = [r[0] for r in run]
    newtons = [r[1] for r in run]

    ymin, ymax = y_limits([run])
    col        = COLORS[test_num - 1]
    label      = human_label(folder_name)

    peak_idx   = newtons.index(min(newtons))   # most negative = highest drag
    peak_t     = times[peak_idx]
    peak_n     = newtons[peak_idx]
    avg_n      = sum(newtons) / len(newtons)

    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(times, newtons, color=col, linewidth=1.6, label=f"Test {test_num}")
    ax.fill_between(times, newtons, 0, alpha=0.09, color=col)
    ax.axhline(0,     color="#aaa", linewidth=0.8, linestyle=":")
    ax.axhline(avg_n, color="#555", linewidth=0.9, linestyle="--",
               label=f"avg  {avg_n:+.3f} N")

    # peak marker
    ax.plot(peak_t, peak_n, "o", color=col, markersize=7, zorder=5)
    x_span = times[-1] - times[0] if len(times) > 1 else 1
    ax.annotate(
        f"peak {peak_n:+.3f} N",
        xy=(peak_t, peak_n),
        xytext=(peak_t + x_span * 0.04, peak_n - (ymax - ymin) * 0.08),
        fontsize=8, color=col,
        arrowprops=dict(arrowstyle="-", color=col, lw=0.8)
    )

    ax.set_xlim(left=0, right=max(times) * 1.08)
    ax.set_ylim(ymin, ymax)
    ax.set_xlabel("Time (s)", fontsize=10)
    ax.set_ylabel("Force (N)", fontsize=10)
    ax.set_title(
        f"{label}  —  Test {test_num}\n"
        f"{len(run)} samples  |  peak {peak_n:+.3f} N  |  avg {avg_n:+.3f} N",
        fontsize=10
    )
    ax.legend(fontsize=9)
    style_ax(ax)
    fig.tight_layout()

    out = os.path.join(folder_path, f"{folder_name}_{test_num}.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"    📊 {folder_name}_{test_num}.png")


# ── Combined overlay PNG ──────────────────────────────────────

def plot_combined(runs, folder_path, folder_name):
    label  = human_label(folder_name)
    ymin, ymax = y_limits(runs)

    fig, ax = plt.subplots(figsize=(13, 5.5))
    peaks, peak_times = [], []

    for idx, run in enumerate(runs):
        times   = [r[0] for r in run]
        newtons = [r[1] for r in run]
        col     = COLORS[idx]
        n       = idx + 1

        peak_idx = newtons.index(min(newtons))
        peak_t   = times[peak_idx]
        peak_n   = newtons[peak_idx]
        peaks.append(peak_n)
        peak_times.append(peak_t)

        ax.plot(times, newtons, color=col, linewidth=1.4, alpha=0.9,
                label=f"Test {n}  (peak {peak_n:+.3f} N)")
        ax.fill_between(times, newtons, 0, alpha=0.06, color=col)
        ax.plot(peak_t, peak_n, "o", color=col, markersize=6, zorder=5)
        ax.annotate(f"T{n}", xy=(peak_t, peak_n),
                    xytext=(peak_t + 0.04, peak_n - (ymax - ymin) * 0.06),
                    fontsize=8, color=col)

    avg_peak = sum(peaks) / len(peaks)
    x_right  = max(r[-1][0] for r in runs)

    ax.axhline(0,        color="#aaa",    linewidth=0.8, linestyle=":")
    ax.axhline(avg_peak, color="#cc3333", linewidth=1.6, linestyle="-.",
               label=f"avg peak  {avg_peak:+.3f} N", zorder=4)
    ax.text(x_right * 0.98,
            avg_peak - (ymax - ymin) * 0.04,
            f"avg peak\n{avg_peak:+.3f} N",
            fontsize=8, color="#cc3333", ha="right", va="top")

    ax.set_xlim(left=0, right=x_right * 1.08)
    ax.set_ylim(ymin, ymax)
    ax.set_xlabel("Time (s)", fontsize=10)
    ax.set_ylabel("Force (N)", fontsize=10)
    ax.set_title(
        f"{label}  —  All 3 Tests\n"
        f"Peaks:  T1 {peaks[0]:+.3f} N   T2 {peaks[1]:+.3f} N   "
        f"T3 {peaks[2]:+.3f} N   →  avg {avg_peak:+.3f} N",
        fontsize=10
    )
    ax.legend(fontsize=9, loc="upper left")
    style_ax(ax)
    fig.tight_layout()

    out = os.path.join(folder_path, f"{folder_name}_combined.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"    📊 {folder_name}_combined.png")


# ── Discover folders and process ─────────────────────────────

def find_result_folders(root):
    """
    Returns list of (folder_path, folder_name) for every subfolder
    that contains at least one _1.csv, _2.csv, _3.csv triplet.
    Also handles the case where the CSVs sit directly in root.
    """
    found = []
    for entry in sorted(os.listdir(root)):
        fp = os.path.join(root, entry)
        if not os.path.isdir(fp):
            continue
        csvs = [f for f in os.listdir(fp) if f.endswith(".csv") and not f.endswith("avg_max.csv")]
        run_csvs = [f for f in csvs if any(f.endswith(f"_{i}.csv") for i in range(1, 4))]
        if len(run_csvs) >= 3:
            found.append((fp, entry))
    return found


def process_folder(folder_path, folder_name):
    print(f"\n  ── {folder_name}")
    runs = []
    counts_per_newton = 2336.0  # fallback default

    for t in range(1, 4):
        csv_path = os.path.join(folder_path, f"{folder_name}_{t}.csv")
        if not os.path.exists(csv_path):
            print(f"    ⚠️  Missing: {folder_name}_{t}.csv — skipping folder.")
            return

        # extract counts_per_newton from comment line
        with open(csv_path) as f:
            for line in f:
                if "counts_per_newton" in line:
                    try:
                        counts_per_newton = float(line.split("counts_per_newton=")[1].strip())
                    except (IndexError, ValueError):
                        pass
                    break

        run = read_csv(csv_path)
        if not run:
            print(f"    ⚠️  No data in {folder_name}_{t}.csv — skipping folder.")
            return
        runs.append(run)
        plot_individual(run, t, folder_path, folder_name, counts_per_newton)

    plot_combined(runs, folder_path, folder_name)


# ── Entry point ───────────────────────────────────────────────

if __name__ == "__main__":
    root = SCRIPT_DIR
    print("=" * 50)
    print("  HX711 Graph Generator")
    print(f"  Scanning: {root}")
    print("=" * 50)

    folders = find_result_folders(root)

    if not folders:
        print("\n  ❌ No result folders found.")
        print("  Make sure this script is in the same directory")
        print("  as your test folders (e.g. Simple_Angled_Stalk_45_reverse/).\n")
        sys.exit(1)

    print(f"\n  Found {len(folders)} folder(s):")
    for _, name in folders:
        print(f"    • {name}")

    for fp, name in folders:
        process_folder(fp, name)

    print(f"\n  ✅ Done — PNGs saved inside each folder.\n")