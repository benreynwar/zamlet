"""
OpenRAM SRAM Configuration Template
Generated from JSON input
"""

# Core SRAM specifications
word_size = {word_size}  # Bits
num_words = {num_words}

# Write granularity
write_size = {write_size}  # Bits

# Port configuration
num_rw_ports = {num_rw_ports}
num_r_ports = {num_r_ports}
num_w_ports = {num_w_ports}

# Spare cells (optional)
num_spare_rows = {num_spare_rows}
num_spare_cols = {num_spare_cols}

# Technology constants (same for all Sky130 SRAMs)
tech_name = "sky130"
nominal_corner_only = True
route_supplies = "ring"
check_lvsdrc = True
uniquify = True

# Calculated values
human_byte_size = "{{:.0f}}kbytes".format((word_size * num_words)/1024/8)

# Determine port configuration string
if num_rw_ports == 1 and num_r_ports == 0 and num_w_ports == 0:
    ports_human = '1rw'
elif num_rw_ports == 1 and num_r_ports == 1 and num_w_ports == 0:
    ports_human = '1rw1r'
elif num_rw_ports == 0 and num_r_ports == 1 and num_w_ports == 1:
    ports_human = '1r1w'
else:
    ports_human = f'{{num_rw_ports}}rw{{num_r_ports}}r{{num_w_ports}}w'

# Output configuration
output_name = "{{tech_name}}_sram_{{human_byte_size}}_{{ports_human}}_{{word_size}}x{{num_words}}_{{write_size}}".format(**locals())
output_path = "{output_path}"
