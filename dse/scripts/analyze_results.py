#!/usr/bin/env python3
"""
NetworkNode area analysis for FMVPU DSE study.
Adapted from RegFileStudy: https://github.com/Pinata-Consulting/RegFileStudy
"""

import sys
import json
import yaml
import matplotlib.pyplot as plt
import numpy as np
import os


def make_pdk_plot(study, pdk_name, output_file):
    """Generate area scaling plots for a specific PDK"""
    # Filter study data for this PDK
    pdk_study = {name: data for name, data in study.items() 
                 if data.get("pdk") == pdk_name}
    
    if not pdk_study:
        print(f"No data found for PDK: {pdk_name}")
        return
    
    # Collect all samples (single depth)
    samples = []
    for s in pdk_study.values():
        channels = s["nChannels"]
        area = s["area"]
        samples.append((channels, area))

    # Sort by channel count
    samples.sort(key=lambda x: x[0])
    channels, areas = zip(*samples) if samples else ([], [])

    plt.figure(figsize=(12, 9))
    
    # Plot area vs channel count (log-log)
    plt.subplot(2, 1, 1)
    if channels and areas:
        plt.plot(channels, areas, 'bo-', linewidth=2, markersize=8)
    
    plt.xlabel("Number of Channels")
    plt.ylabel("Area (μm²)")
    plt.title(f"NetworkNode Area vs Channel Count - {pdk_name.upper()} PDK (Log-Log)")
    plt.grid(True, alpha=0.3)
    plt.yscale('log')
    plt.xscale('log', base=2)
    
    # Plot area vs channel count (linear)
    plt.subplot(2, 1, 2)
    if channels and areas:
        plt.plot(channels, areas, 'bo-', linewidth=2, markersize=8)
    
    plt.xlabel("Number of Channels")
    plt.ylabel("Area (μm²)")
    plt.title(f"NetworkNode Area vs Channel Count - {pdk_name.upper()} PDK (Linear)")
    plt.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()
    
    # Print summary statistics
    print(f"\n=== NetworkNode Area Scaling Analysis - {pdk_name.upper()} PDK ===")
    print(f"Study configurations: {len(pdk_study)}")
    print(f"Channel counts tested: {sorted(set(s['nChannels'] for s in pdk_study.values()))}")
    
    if channels and areas:
        for ch, area in zip(channels, areas):
            unit = "channel" if ch == 1 else "channels"
            print(f"  {ch} {unit}: {area:.1f} μm²")
        print(f"  Total scaling: {areas[-1]/areas[0]:.2f}x")


def main(argv):
    if len(argv) < 3:
        print("Usage: analyze_results.py <output_file> <target_pdk> <config_files...> <results_files...>")
        sys.exit(1)
    
    output = argv[0]
    target_pdk = argv[1]
    
    # Load all JSON config files
    study_list = []
    config_files = []
    results_files = []
    
    # Separate config files from results files
    for arg in argv[2:]:
        if arg.endswith('.json'):
            config_files.append(arg)
        else:
            results_files.append(arg)
    
    # Load all study configurations
    for config_file in config_files:
        with open(config_file, "r") as file:
            study_config = json.load(file)
            study_list.append(study_config)

    study = {study["name"]: study for study in study_list}
    print(f"DEBUG: Loaded {len(study_list)} study configurations")
    print(f"DEBUG: Study names: {list(study.keys())}")

    # Load results files
    print(f"DEBUG: Loading {len(results_files)} result files")
    for file in results_files:
        print(f"DEBUG: Loading result file: {file}")
        with open(file, "r") as f:
            data = yaml.safe_load(f)
        print(f"DEBUG: Result data name: {data['name']}")
        
        # Extract PDK from filename
        filename = os.path.basename(file)
        if "__" in filename:
            # Extract PDK from filename (e.g., NetworkNode_1ch_32b_16d__sky130hd_stats -> sky130hd)
            pdk_part = filename.split("__")[1].split("_")[0]  # Get part between __ and next _
            data["pdk"] = pdk_part
            print(f"DEBUG: Extracted PDK '{pdk_part}' from filename")
        else:
            raise ValueError(f"Could not extract PDK from filename: {filename}")
            
        study[data["name"]] |= data

    print(f"DEBUG: Final study data names: {list(study.keys())}")
    
    # Debug PDK extraction
    print(f"DEBUG: Looking for PDK: {target_pdk}")
    pdks_found = set()
    for name, data in study.items():
        pdk = data["pdk"]
        pdks_found.add(pdk)
        print(f"DEBUG: Study '{name}' -> PDK '{pdk}'")
    
    print(f"DEBUG: PDKs found: {sorted(pdks_found)}")

    # Generate plot for the specified PDK
    make_pdk_plot(study, target_pdk, output)
    print(f"Generated plot: {output}")


if __name__ == "__main__":
    main(sys.argv[1:])