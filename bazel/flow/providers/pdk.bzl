# PdkInfo provider - PDK configuration

PdkInfo = provider(
    doc = "PDK information for the flow.",
    fields = {
        # Core identity
        "name": "PDK name (e.g., 'sky130A')",
        "std_cell_library": "Standard cell library name",

        # Power/ground
        "vdd_pin": "Power pin name (e.g., 'VPWR')",
        "gnd_pin": "Ground pin name (e.g., 'VGND')",
        "vdd_pin_voltage": "Power pin voltage (Decimal)",
        "scl_power_pins": "List of SCL power pin names",
        "scl_ground_pins": "List of SCL ground pin names",

        # Cell libraries - files
        "cell_lefs": "List of cell LEF Files",
        "cell_gds": "List of cell GDS Files",
        "cell_verilog_models": "List of cell Verilog model Files (optional)",
        "cell_bb_verilog_models": "List of cell black-box Verilog model Files (optional)",
        "cell_spice_models": "List of cell SPICE model Files (optional)",
        "pad_verilog_models": "List of pad Verilog model Files (optional)",

        # Technology LEFs - dict of corner -> File
        "tech_lefs": "Dict of corner pattern to tech LEF File",

        # Timing libraries - dict of corner -> list of Files
        "lib": "Dict of corner pattern to list of liberty Files",

        # GPIO pads
        "gpio_pads_lef": "List of GPIO pad LEF Files (optional)",
        "gpio_pads_lef_core_side": "List of GPIO pad LEF Files for core side (optional)",
        "gpio_pads_verilog": "List of GPIO pad Verilog Files (optional)",
        "gpio_pad_cells": "List of GPIO pad cell name prefixes (optional)",

        # Floorplanning
        "fp_flip_sites": "List of placement sites to flip vertically (optional)",
        "fp_tracks_info": "Tracks info File",
        "fp_tapcell_dist": "Distance between tap cells (Decimal, um)",
        "fp_prune_threshold": "Minimum row width to preserve during row cutting (optional)",
        "io_pin_h_layer": "Metal layer for horizontal IO pins",
        "io_pin_v_layer": "Metal layer for vertical IO pins",

        # Routing
        "rt_min_layer": "Minimum routing layer",
        "rt_max_layer": "Maximum routing layer",
        "grt_layer_adjustments": "List of layer adjustment factors for global routing",

        # Placement
        "gpl_cell_padding": "Cell padding for global placement",
        "dpl_cell_padding": "Cell padding for detailed placement",
        "extra_sites": "List of extra placement sites",

        # CTS (Clock Tree Synthesis)
        "cts_root_buffer": "Root buffer cell for CTS",
        "cts_clk_buffers": "List of clock buffer cells for CTS",

        # IO
        "io_pin_h_length": "Horizontal IO pin length",
        "io_pin_v_length": "Vertical IO pin length",
        "io_pin_min_distance": "Minimum distance between IO pins",

        # PDN (Power Distribution Network)
        "pdn_rail_layer": "PDN rail layer",
        "pdn_rail_width": "PDN rail width",
        "pdn_rail_offset": "PDN rail offset",
        "pdn_horizontal_layer": "PDN horizontal strap layer",
        "pdn_vertical_layer": "PDN vertical strap layer",
        "pdn_core_horizontal_layer": "PDN core ring horizontal layer (optional)",
        "pdn_core_vertical_layer": "PDN core ring vertical layer (optional)",
        "pdn_hoffset": "PDN horizontal offset",
        "pdn_voffset": "PDN vertical offset",
        "pdn_hpitch": "PDN horizontal pitch",
        "pdn_vpitch": "PDN vertical pitch",
        "pdn_hspacing": "PDN horizontal spacing",
        "pdn_vspacing": "PDN vertical spacing",
        "pdn_hwidth": "PDN horizontal width",
        "pdn_vwidth": "PDN vertical width",
        "pdn_core_ring_hoffset": "PDN core ring horizontal offset",
        "pdn_core_ring_voffset": "PDN core ring vertical offset",
        "pdn_core_ring_hspacing": "PDN core ring horizontal spacing",
        "pdn_core_ring_vspacing": "PDN core ring vertical spacing",
        "pdn_core_ring_hwidth": "PDN core ring horizontal width",
        "pdn_core_ring_vwidth": "PDN core ring vertical width",
        "pdn_core_ring_connect_to_pads": "Connect core ring to pad pins",
        "pdn_core_ring_allow_out_of_die": "Allow core ring shapes outside die",
        "pdn_extend_to": "PDN stripe/ring extension mode",
        "pdn_enable_pins": "Promote power straps to block pins",

        # Antenna
        "heuristic_antenna_threshold": "Threshold for heuristic antenna insertion",

        # Magic
        "magicrc": "Magic RC file",
        "magic_tech": "Magic tech file",
        "magic_pdk_setup": "Magic PDK setup file",
        "cell_mags": "List of cell Magic files",
        "cell_maglefs": "List of cell Magic LEF files",

        # KLayout
        "klayout_tech": "KLayout tech file",
        "klayout_properties": "KLayout properties file",
        "klayout_def_layer_map": "KLayout DEF layer map file",
        "klayout_drc_runset": "KLayout DRC runset file",
        "klayout_drc_options": "Dict of KLayout DRC options (feol, beol, floating_metal, offgrid, seal)",
        "klayout_xor_ignore_layers": "List of layers to ignore in KLayout XOR",
        "klayout_xor_tile_size": "KLayout XOR tile size",

        # Netgen
        "netgen_setup": "Netgen setup file",

        # RCX
        "rcx_rulesets": "Dict of corner to RCX ruleset file",

        # Synthesis maps
        "synth_latch_map": "Synthesis latch map file",
        "synth_tristate_map": "Synthesis tristate map file",
        "synth_csa_map": "Synthesis CSA map file",
        "synth_rca_map": "Synthesis RCA map file",
        "synth_fa_map": "Synthesis FA map file",
        "synth_mux_map": "Synthesis MUX map file",
        "synth_mux4_map": "Synthesis MUX4 map file",
        "synth_clockgate_posedge_icg": "Positive-edge clock-gate ICG cell (optional)",
        "synth_clockgate_negedge_icg": "Negative-edge clock-gate ICG cell (optional)",

        # Misc
        "ignore_disconnected_modules": "List of modules to ignore disconnection errors",
        "timing_violation_corners": "List of corners for timing violation checks",

        # Timing corners
        "default_corner": "Default timing corner",
        "sta_corners": "List of STA corner names",
        "pnr_corners": "List of PnR corner names (optional)",

        # Wire RC
        "layers_rc": "Layer resistance/capacitance values by corner (optional)",
        "vias_r": "Via resistance values by corner (optional)",
        "signal_wire_rc_layers": "List of layers for signal wire RC (optional)",
        "clock_wire_rc_layers": "List of layers for clock wire RC (optional)",

        # Constraints
        "default_max_tran": "Default max transition (Decimal, ns, optional)",
        "output_cap_load": "Output capacitive load (Decimal, fF)",
        "max_fanout_constraint": "Max fanout constraint (int)",
        "max_transition_constraint": "Max transition constraint (Decimal, ns, optional)",
        "max_capacitance_constraint": "Max capacitance constraint (Decimal, pF, optional)",
        "clock_uncertainty_constraint": "Clock uncertainty (Decimal, ns)",
        "clock_transition_constraint": "Clock transition (Decimal, ns)",
        "time_derating_constraint": "Time derating (Decimal, %)",
        "io_delay_constraint": "IO delay (Decimal, %)",
        "wire_length_threshold": "Wire length warning threshold (Decimal, um, optional)",

        # Synthesis cells
        "synth_driving_cell": "Driving cell for synthesis (cell/port format)",
        "synth_clk_driving_cell": "Clock driving cell (cell/port format, optional)",
        "synth_tiehi_cell": "Tie-high cell (cell/port format)",
        "synth_tielo_cell": "Tie-low cell (cell/port format)",
        "synth_buffer_cell": "Buffer cell (cell/in/out format)",
        "synth_excluded_cell_file": "File listing cells excluded from synthesis",
        "pnr_excluded_cell_file": "File listing cells excluded from PnR",

        # Placement cells
        "welltap_cell": "Well tap cell name",
        "endcap_cell": "End cap cell name",
        "place_site": "Placement site name",
        "fill_cells": "List of fill cell names/patterns",
        "decap_cells": "List of decap cell names/patterns",
        "cell_pad_exclude": "List of cells excluded from padding",
        "diode_cell": "Diode cell (cell/port format, optional)",
        "tristate_cells": "List of tristate buffer cell patterns (optional)",

        # Signoff
        "primary_gdsii_streamout_tool": "Primary GDSII tool (e.g., 'magic')",
    },
)
