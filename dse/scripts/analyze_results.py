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
    
    # Separate data by component type
    networknode_data = {name: data for name, data in pdk_study.items() 
                       if data.get("top_level") == "NetworkNode"}
    alu_data = {name: data for name, data in pdk_study.items() 
               if data.get("top_level") == "LaneALU"}
    crossbar_data = {name: data for name, data in pdk_study.items() 
                    if data.get("top_level") == "NetworkCrossbar"}
    switch_data = {name: data for name, data in pdk_study.items() 
                  if data.get("top_level") == "NetworkSwitch"}
    
    # Collect NetworkNode samples
    networknode_samples = []
    for s in networknode_data.values():
        channels = s["nChannels"]
        area = s["area"]
        networknode_samples.append((channels, area))

    # Collect NetworkCrossbar samples
    crossbar_samples = []
    for s in crossbar_data.values():
        channels = s["nChannels"]
        area = s["area"]
        crossbar_samples.append((channels, area))

    # Collect NetworkSwitch samples
    switch_samples = []
    for s in switch_data.values():
        channels = s["nChannels"]
        area = s["area"]
        switch_samples.append((channels, area))

    # Sort by channel count
    networknode_samples.sort(key=lambda x: x[0])
    crossbar_samples.sort(key=lambda x: x[0])
    switch_samples.sort(key=lambda x: x[0])
    
    nn_channels, nn_areas = zip(*networknode_samples) if networknode_samples else ([], [])
    cb_channels, cb_areas = zip(*crossbar_samples) if crossbar_samples else ([], [])
    sw_channels, sw_areas = zip(*switch_samples) if switch_samples else ([], [])
    
    # Get ALU area (single data point)
    alu_area = None
    if alu_data:
        alu_area = list(alu_data.values())[0]["area"]

    plt.figure(figsize=(12, 9))
    
    # Plot area vs channel count (log-log)
    plt.subplot(2, 1, 1)
    if nn_channels and nn_areas:
        plt.plot(nn_channels, nn_areas, 'bo-', linewidth=2, markersize=8, label='NetworkNode')
    if cb_channels and cb_areas:
        plt.plot(cb_channels, cb_areas, 'go-', linewidth=2, markersize=6, label='NetworkCrossbar')
    if sw_channels and sw_areas:
        plt.plot(sw_channels, sw_areas, 'mo-', linewidth=2, markersize=6, label='NetworkSwitch')
    if alu_area:
        plt.axhline(y=alu_area, color='r', linestyle='--', linewidth=2, label='LaneALU')
    
    plt.xlabel("Number of Channels")
    plt.ylabel("Area (μm²)")
    plt.title(f"Component Area Comparison - {pdk_name.upper()} PDK (Log-Log)")
    plt.grid(True, alpha=0.3)
    plt.yscale('log')
    plt.xscale('log', base=2)
    plt.legend()
    
    # Plot area vs channel count (linear)
    plt.subplot(2, 1, 2)
    if nn_channels and nn_areas:
        plt.plot(nn_channels, nn_areas, 'bo-', linewidth=2, markersize=8, label='NetworkNode')
    if cb_channels and cb_areas:
        plt.plot(cb_channels, cb_areas, 'go-', linewidth=2, markersize=6, label='NetworkCrossbar')
    if sw_channels and sw_areas:
        plt.plot(sw_channels, sw_areas, 'mo-', linewidth=2, markersize=6, label='NetworkSwitch')
    if alu_area:
        plt.axhline(y=alu_area, color='r', linestyle='--', linewidth=2, label='LaneALU')
    
    plt.xlabel("Number of Channels")
    plt.ylabel("Area (μm²)")
    plt.title(f"Component Area Comparison - {pdk_name.upper()} PDK (Linear)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()
    
    # Print summary statistics
    print(f"\n=== Component Area Analysis - {pdk_name.upper()} PDK ===")
    print(f"NetworkNode configurations: {len(networknode_data)}")
    print(f"NetworkCrossbar configurations: {len(crossbar_data)}")
    print(f"NetworkSwitch configurations: {len(switch_data)}")
    print(f"ALU configurations: {len(alu_data)}")
    
    if nn_channels and nn_areas:
        print(f"\nNetworkNode Channel Scaling:")
        for ch, area in zip(nn_channels, nn_areas):
            unit = "channel" if ch == 1 else "channels"
            print(f"  {ch} {unit}: {area:.1f} μm²")
        print(f"  Total scaling: {nn_areas[-1]/nn_areas[0]:.2f}x")
    
    if cb_channels and cb_areas:
        print(f"\nNetworkCrossbar Channel Scaling:")
        for ch, area in zip(cb_channels, cb_areas):
            unit = "channel" if ch == 1 else "channels"
            print(f"  {ch} {unit}: {area:.1f} μm²")
        print(f"  Total scaling: {cb_areas[-1]/cb_areas[0]:.2f}x")
    
    if sw_channels and sw_areas:
        print(f"\nNetworkSwitch Channel Scaling:")
        for ch, area in zip(sw_channels, sw_areas):
            unit = "channel" if ch == 1 else "channels"
            print(f"  {ch} {unit}: {area:.1f} μm²")
        print(f"  Total scaling: {sw_areas[-1]/sw_areas[0]:.2f}x")
    
    if alu_area:
        print(f"\nLaneALU Area: {alu_area:.1f} μm²")
        if nn_areas:
            print(f"ALU vs NetworkNode 1ch: {alu_area/nn_areas[0]:.2f}x")
            print(f"ALU vs NetworkNode 4ch: {alu_area/nn_areas[-1]:.2f}x")
    
    # Component breakdown analysis for 1-channel case
    if nn_areas and cb_areas and sw_areas:
        print(f"\n=== 1-Channel Component Breakdown ===")
        nn_1ch = nn_areas[0]
        cb_1ch = cb_areas[0] 
        sw_1ch = sw_areas[0]
        other_1ch = nn_1ch - cb_1ch - sw_1ch
        
        print(f"NetworkNode (1ch):     {nn_1ch:.1f} μm² (100.0%)")
        print(f"  NetworkCrossbar:     {cb_1ch:.1f} μm² ({100*cb_1ch/nn_1ch:.1f}%)")
        print(f"  NetworkSwitch:       {sw_1ch:.1f} μm² ({100*sw_1ch/nn_1ch:.1f}%)")
        print(f"  Other components:    {other_1ch:.1f} μm² ({100*other_1ch/nn_1ch:.1f}%)")


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