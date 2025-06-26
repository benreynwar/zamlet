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


def main(argv):
    output = argv[0]
    
    # Load all JSON config files
    study_list = []
    config_files = []
    results_files = []
    
    # Separate config files from results files
    for arg in argv[1:]:
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

    # Load results files
    for file in results_files:
        with open(file, "r") as f:
            data = yaml.safe_load(f)

        study[data["name"]] |= data

    # Analyze NetworkNode area scaling with channel count
    names = list(study.keys())
    inputs = ["nChannels", "width", "networkMemoryDepth"]
    exclude = inputs + ["name", "nSlowNetworkControlSlots", "nFastNetworkControlSlots", 
                        "maxNetworkControlDelay", "maxPacketLength", "networkIdentWidth", 
                        "ddmAddrWidth", "nColumns", "nRows"]
    variables = set([
        key for name in names for key in study[name].keys()
        if key not in exclude
    ])

    # Group by buffer depth for comparison
    depth_8_samples = []
    depth_16_samples = []
    
    for s in study.values():
        channels = s["nChannels"]
        area = s["area"]
        depth = s["networkMemoryDepth"]
        
        if depth == 8:
            depth_8_samples.append((channels, area))
        elif depth == 16:
            depth_16_samples.append((channels, area))

    # Sort by channel count
    depth_8_samples.sort(key=lambda x: x[0])
    depth_16_samples.sort(key=lambda x: x[0])

    # Extract x,y data
    channels_8, areas_8 = zip(*depth_8_samples) if depth_8_samples else ([], [])
    channels_16, areas_16 = zip(*depth_16_samples) if depth_16_samples else ([], [])

    plt.figure(figsize=(12, 12))
    
    # Plot area vs channel count (log-log)
    plt.subplot(3, 1, 1)
    if channels_8 and areas_8:
        plt.plot(channels_8, areas_8, 'bo-', label='8-deep buffers', linewidth=2, markersize=8)
    if channels_16 and areas_16:
        plt.plot(channels_16, areas_16, 'ro-', label='16-deep buffers', linewidth=2, markersize=8)
    
    plt.xlabel("Number of Channels")
    plt.ylabel("Area (μm²)")
    plt.title("NetworkNode Area vs Channel Count (Log-Log)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.yscale('log')
    plt.xscale('log', base=2)
    
    # Plot area vs channel count (linear)
    plt.subplot(3, 1, 2)
    if channels_8 and areas_8:
        plt.plot(channels_8, areas_8, 'bo-', label='8-deep buffers', linewidth=2, markersize=8)
    if channels_16 and areas_16:
        plt.plot(channels_16, areas_16, 'ro-', label='16-deep buffers', linewidth=2, markersize=8)
    
    plt.xlabel("Number of Channels")
    plt.ylabel("Area (μm²)")
    plt.title("NetworkNode Area vs Channel Count (Linear)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    # Plot area scaling ratio
    plt.subplot(3, 1, 3)
    if len(channels_8) > 1:
        ratios_8 = [areas_8[i] / areas_8[i-1] for i in range(1, len(areas_8))]
        channels_8_ratios = channels_8[1:]
        plt.plot(channels_8_ratios, ratios_8, 'bo-', label='8-deep buffers', linewidth=2, markersize=8)
    
    if len(channels_16) > 1:
        ratios_16 = [areas_16[i] / areas_16[i-1] for i in range(1, len(areas_16))]
        channels_16_ratios = channels_16[1:]
        plt.plot(channels_16_ratios, ratios_16, 'ro-', label='16-deep buffers', linewidth=2, markersize=8)
    
    plt.xlabel("Number of Channels")
    plt.ylabel("Area Scaling Ratio")
    plt.title("Area Scaling Factor (vs Previous Channel Count)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xscale('log', base=2)
    plt.axhline(y=2.0, color='k', linestyle='--', alpha=0.5, label='Linear scaling')
    
    plt.tight_layout()
    plt.savefig(output, dpi=300, bbox_inches='tight')
    
    # Print summary statistics
    print("\n=== NetworkNode Area Scaling Analysis ===")
    print(f"Study configurations: {len(study)}")
    print(f"Channel counts tested: {sorted(set(s['nChannels'] for s in study.values()))}")
    print(f"Buffer depths tested: {sorted(set(s['networkMemoryDepth'] for s in study.values()))}")
    
    if channels_8 and areas_8:
        print(f"\n8-deep buffers:")
        print(f"  1 channel:  {areas_8[0]:.1f} μm²")
        print(f"  {channels_8[-1]} channels: {areas_8[-1]:.1f} μm²")
        print(f"  Total scaling: {areas_8[-1]/areas_8[0]:.2f}x")
    
    if channels_16 and areas_16:
        print(f"\n16-deep buffers:")
        print(f"  1 channel:  {areas_16[0]:.1f} μm²")
        print(f"  {channels_16[-1]} channels: {areas_16[-1]:.1f} μm²")
        print(f"  Total scaling: {areas_16[-1]/areas_16[0]:.2f}x")


if __name__ == "__main__":
    main(sys.argv[1:])