"""
data_cleaner.py
---------------
Scans test folders for runs 1, 2, and 3.
Identifies the anomalous run (the outlier based on peak force).
Creates a "cleaner" folder, synthesizes a perfectly averaged replacement 
for the anomalous run, and automatically generates PNG plots using plotter.py.
"""

import os
import csv
import glob
import numpy as np
import sys

# Import your existing plotter!
try:
    import plotter
    CAN_PLOT = True
except ImportError:
    CAN_PLOT = False
    print("⚠️ Could not find 'plotter.py' in the same directory. Will only generate CSVs.")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def read_csv_full(path):
    """Reads a run CSV and extracts metadata, headers, and rows."""
    with open(path, 'r', newline='') as f:
        reader = csv.reader(f)
        headers = next(reader)
        meta_line = next(reader)
        
        offset = 0.0
        cpn = 1.0
        meta_str = "".join(meta_line)
        
        if "friction_offset" in meta_str:
            parts = meta_str.replace('#', '').split()
            for p in parts:
                if "friction_offset=" in p:
                    offset = float(p.split("=")[1])
                elif "counts_per_newton=" in p:
                    cpn = float(p.split("=")[1])

        rows = []
        for row in reader:
            if not row or row[0].startswith('#'): continue
            rows.append({
                'index': int(row[0]),
                'time_s': float(row[1]),
                'value': float(row[2]),
                'newtons': float(row[3]),
                'raw_value': float(row[4])
            })
    return headers, meta_line, offset, cpn, rows

def write_csv(path, headers, meta_line, rows):
    """Writes the data back to CSV exactly matching the original format."""
    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerow(meta_line)
        for r in rows:
            writer.writerow([
                r['index'], 
                f"{r['time_s']:.3f}", 
                r['value'], 
                f"{r['newtons']:.4f}", 
                r['raw_value']
            ])

def write_avg_max(cleaner_dir, label, offset, cpn, rows_list):
    """Re-generates the avg_max.csv file for the cleaned data."""
    path = os.path.join(cleaner_dir, f"{label}_avg_max.csv")
    peaks = []
    peak_times = []
    
    for rows in rows_list:
        vals = [r['value'] for r in rows]
        abs_vals = [abs(v) for v in vals]
        m_idx = np.argmax(abs_vals)
        peaks.append(vals[m_idx])
        peak_times.append(rows[m_idx]['time_s'])

    with open(path, 'w', newline='') as f:
        f.write("metric,test1,test2,test3,average\n")
        avg_peak = sum(peaks)/3.0
        avg_time = sum(peak_times)/3.0
        f.write(f"peak_value,{peaks[0]},{peaks[1]},{peaks[2]},{avg_peak:.1f}\n")
        f.write(f"peak_time_s,{peak_times[0]:.3f},{peak_times[1]:.3f},{peak_times[2]:.3f},{avg_time:.3f}\n")
        f.write("\n")
        f.write(f"label,{label}\n")
        f.write(f"friction_offset,{offset}\n")
        f.write(f"counts_per_newton,{cpn}\n")

def synthesize_run(bad_run, good_run1, good_run2, offset, cpn):
    """Averages the two good runs, interpolating times to match the bad run."""
    t_bad = [r['time_s'] for r in bad_run]
    t_g1, n_g1 = [r['time_s'] for r in good_run1], [r['newtons'] for r in good_run1]
    t_g2, n_g2 = [r['time_s'] for r in good_run2], [r['newtons'] for r in good_run2]

    # Interpolate both good runs onto the anomalous run's timestamps
    interp_g1 = np.interp(t_bad, t_g1, n_g1)
    interp_g2 = np.interp(t_bad, t_g2, n_g2)

    # Average the newtons
    synth_newtons = (interp_g1 + interp_g2) / 2.0

    synth_rows = []
    for i, row in enumerate(bad_run):
        new_n = synth_newtons[i]
        new_val = int(round(new_n * cpn))
        new_raw = int(round(new_val + offset))

        synth_rows.append({
            'index': row['index'],
            'time_s': row['time_s'],
            'value': new_val,
            'newtons': round(new_n, 4),
            'raw_value': new_raw
        })
    return synth_rows

def main():
    print("=" * 50)
    print("  Data Cleaner: Anomaly Fixer & Auto-Plotter")
    print("=" * 50)

    # Find all result folders in the script directory (ignoring existing cleaner folders)
    folders = [f.path for f in os.scandir(SCRIPT_DIR) if f.is_dir() and "cleaner" not in f.name.lower()]

    if not folders:
        print("\n  ❌ No result folders found. Run this next to your test folders.")
        sys.exit(1)

    for folder in folders:
        folder_name = os.path.basename(folder)
        csv_files = sorted(glob.glob(os.path.join(folder, "*_[123].csv")))
        
        if len(csv_files) != 3:
            continue
            
        print(f"\nAnalyzing: {folder_name}")
        
        datasets = []
        for file in csv_files:
            headers, meta, offset, cpn, rows = read_csv_full(file)
            datasets.append({'file': file, 'headers': headers, 'meta': meta, 'offset': offset, 'cpn': cpn, 'rows': rows})

        # 1. Detect Anomaly
        peaks = [max([abs(r['newtons']) for r in ds['rows']]) for ds in datasets]
        median_peak = np.median(peaks)
        distances = [abs(p - median_peak) for p in peaks]
        bad_idx = np.argmax(distances)
        
        good_indices = [i for i in range(3) if i != bad_idx]
        bad_ds = datasets[bad_idx]
        g1_ds = datasets[good_indices[0]]
        g2_ds = datasets[good_indices[1]]
        
        print(f"  -> Outlier detected in Run {bad_idx + 1} (Peak diff: {distances[bad_idx]:.2f}N)")
        
        # 2. Synthesize replacement
        print(f"  -> Fixing Run {bad_idx + 1} by averaging Runs {good_indices[0]+1} & {good_indices[1]+1}...")
        fixed_rows = synthesize_run(bad_ds['rows'], g1_ds['rows'], g2_ds['rows'], bad_ds['offset'], bad_ds['cpn'])

        # 3. Create 'cleaner' folder
        cleaner_dir = os.path.join(folder, "cleaner")
        os.makedirs(cleaner_dir, exist_ok=True)
        
        # 4. Write out the files
        all_final_rows = []
        for i, ds in enumerate(datasets):
            out_name = os.path.basename(ds['file'])
            out_path = os.path.join(cleaner_dir, out_name)
            
            if i == bad_idx:
                write_csv(out_path, ds['headers'], ds['meta'], fixed_rows)
                all_final_rows.append(fixed_rows)
            else:
                write_csv(out_path, ds['headers'], ds['meta'], ds['rows'])
                all_final_rows.append(ds['rows'])
                
        # 5. Write the updated avg_max.csv
        write_avg_max(cleaner_dir, folder_name, datasets[0]['offset'], datasets[0]['cpn'], all_final_rows)
        print(f"  ✅ Saved clean CSVs to {folder_name}/cleaner/")

        # 6. Have plotter.py generate the PNGs right inside the cleaner folder!
        if CAN_PLOT:
            print(f"  -> Generating plots for cleaned data...")
            # We pass the new directory but keep the same base folder_name so it finds the files
            plotter.process_folder(cleaner_dir, folder_name)

    print("\n  🎉 All done! Check the 'cleaner' folders for your new CSVs and PNGs.\n")

if __name__ == "__main__":
    main()