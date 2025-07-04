#!/usr/bin/env python3
"""
Convert JSON configuration to OpenRAM Python config file.
Usage: json_to_config.py <input.json> <output.py>
"""

import json
import sys
import os

def json_to_python_config(json_file, python_file):
    """Convert JSON config to Python config file using template."""
    
    with open(json_file, 'r') as f:
        config = json.load(f)
    
    # Read template
    template_path = '/workspace/dse/openram_scripts/config_template.py'
    with open(template_path, 'r') as f:
        template = f.read()
    
    # Format the template with JSON values
    python_config = template.format(
        word_size=config['word_size'],
        num_words=config['num_words'],
        write_size=config['write_size'],
        num_rw_ports=config['num_rw_ports'],
        num_r_ports=config['num_r_ports'],
        num_w_ports=config['num_w_ports'],
        num_spare_rows=config.get('num_spare_rows', 1),
        num_spare_cols=config.get('num_spare_cols', 1),
        output_path=os.getcwd(),
    )
    
    # Write the Python config file
    with open(python_file, 'w') as f:
        f.write(python_config)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: json_to_config.py <input.json> <output.py>")
        sys.exit(1)
    
    json_file = sys.argv[1]
    python_file = sys.argv[2]
    
    if not os.path.exists(json_file):
        print(f"Error: JSON file not found: {json_file}")
        sys.exit(1)
    
    try:
        json_to_python_config(json_file, python_file)
        print(f"Successfully converted {json_file} to {python_file}")
    except Exception as e:
        print(f"Error converting config: {e}")
        sys.exit(1)
