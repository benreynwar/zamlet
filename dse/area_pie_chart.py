#!/usr/bin/env python3
"""
Generate a pie chart of component areas from DSE results.
Categorizes components into: Instruction Memory, Data Memory, Execution Units, 
RegisterFile, RS + Initial Reorder, and Network.
"""

import os
import matplotlib.pyplot as plt
from python.runfiles import runfiles

def parse_stats_file(filepath):
    """Parse a stats file and extract area."""
    try:
        with open(filepath, 'r') as f:
            for line in f:
                if line.startswith('area:'):
                    return int(line.split(':')[1].strip())
    except FileNotFoundError:
        print(f"Warning: {filepath} not found")
        return 0
    return 0

def get_component_area(component_name, component_type, pdk="sky130hd"):
    """Get area for a component using bazel runfiles."""
    r = runfiles.Create()
    path = r.Rlocation(f"zamlet/dse/{component_type}/{component_name}_default__{pdk}_stats")
    return parse_stats_file(path)

def main():
    n_amlets = 4
    
    # Component mappings to categories with their types
    categories = {
        "Instruction Memory": [("InstructionMemory", "bamlet")],
        "Data Memory": [("DataMemory", "amlet")],
        "Execution Units": [("ALU", "amlet"), ("ALULite", "amlet"), ("ALUPredicate", "amlet")],
        "RegisterFile": [("RegisterFileAndRename", "amlet")],
        "Reordering": [
            ("ALURS", "amlet"), ("ALULiteRS", "amlet"), ("ALUPredicateRS", "amlet"), 
            ("LoadStoreRS", "amlet"), ("SendPacketRS", "amlet"), ("ReceivePacketRS", "amlet"), 
            ("Control", "bamlet"), ("DependencyTracker", "bamlet")
        ],
        "Network": [("NetworkNode", "amlet"), ("SendPacketInterface", "amlet"), ("ReceivePacketInterface", "amlet")]
    }
    
    # Calculate total area for each category
    category_areas = {}
    total_area = 0
    
    for category, components in categories.items():
        area = 0
        for component_name, component_type in components:
            component_area = get_component_area(component_name, component_type)
            # Multiply amlet components by n_amlets
            if component_type == "amlet":
                component_area *= n_amlets
            area += component_area
            if component_area > 0:
                print(f"{component_name}: {component_area}")
        
        category_areas[category] = area
        total_area += area
        print(f"{category} total: {area}")
    
    print(f"\nTotal area: {total_area}")
    
    # Filter out categories with zero area
    filtered_areas = {k: v for k, v in category_areas.items() if v > 0}
    
    if not filtered_areas:
        print("Error: No area data found. Make sure to build the DSE results first:")
        print("bazel build //dse/amlet:all_default__sky130hd_results")
        print("bazel build //dse/bamlet:all_default__sky130hd_results")
        return
    
    # Create pie chart
    plt.figure(figsize=(10, 8))
    colors = ['#8B4513', '#2E8B57', '#4682B4', '#8FBC8F', '#D2691E', '#5F9EA0']
    
    wedges, texts, autotexts = plt.pie(
        filtered_areas.values(),
        labels=filtered_areas.keys(),
        autopct='%1.1f%%',
        startangle=90,
        colors=colors[:len(filtered_areas)],
        textprops={'fontsize': 14}
    )
    
    plt.title('Bamlet Area', fontsize=20, fontweight='bold')
    
    # Add area values to legend (convert µm² to mm²)
    legend_labels = [f'{k}: {v/1000000:.2f} mm²' for k, v in filtered_areas.items()]
    plt.legend(wedges, legend_labels, title="Components", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1), fontsize=12, title_fontsize=14)
    
    plt.tight_layout()
    plt.savefig('zamlet_area_pie_chart.png', dpi=300, bbox_inches='tight')
    # Don't show interactive plot when running in bazel
    # plt.show()
    
    print(f"\nPie chart saved as 'zamlet_area_pie_chart.png'")

if __name__ == "__main__":
    main()