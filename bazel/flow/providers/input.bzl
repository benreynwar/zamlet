# LibrelaneInput provider - flow configuration that doesn't change during the flow
#
# Field names match librelane's DesignFormat IDs where possible.
# See librelane/state/design_format.py for the full list.

LibrelaneInput = provider(
    doc = "Flow configuration - created once, used by all steps.",
    fields = {
        # Design metadata
        "top": "Top module name",
        "clock_port": "Clock port name",
        "clock_period": "Clock period in nanoseconds (string)",

        # PDK info
        "pdk_info": "PdkInfo provider with full PDK configuration",
        "default_corner": "Default timing corner override",
        "max_transition_constraint": "Max transition constraint override in ns",
        "max_capacitance_constraint": "Max capacitance constraint override in pF",

        # Input RTL (before synthesis)
        "verilog_files": "Depset of input verilog File objects",

        # Macro support for hierarchical designs
        "macros": "List of MacroInfo providers",

        # Custom SDC files (optional)
        "pnr_sdc_file": "File - Custom SDC for PnR timing constraints",
        "signoff_sdc_file": "File - Custom SDC for signoff STA",

        # Optional Verilog source configuration
        "verilog_include_dirs": "List of Verilog include directory paths (strings)",
        "verilog_defines": "List of Verilog preprocessor defines (strings)",

        # Verilator.Lint config (from librelane/steps/verilator.py lines 39-87)
        "verilog_power_define": "Power guard define name",
        "linter_include_pdk_models": "Include PDK Verilog models in linting",
        "linter_relative_includes": "Resolve includes relative to file",
        "linter_error_on_latch": "Error on inferred latches",
        "linter_error_on_multidriven": "Error on multiple-driver nets",
        "linter_defines": "Linter-specific preprocessor defines (list)",
        "linter_disable_warnings": "Verilator warning codes disabled globally",
        "linter_disable_warnings_blackbox": "Verilator warning codes disabled for blackbox models",
        "linter_vlt": "Extra Verilator configuration file",
        "extra_verilog_models": "Extra Verilog models (list of Files)",

        # Checker config (from librelane/steps/checker.py)
        "error_on_linter_timing_constructs": "Quit on timing constructs (Step 2)",
        "error_on_linter_errors": "Quit on linter errors (Step 3)",
        "error_on_linter_warnings": "Quit on linter warnings (Step 4)",

        # Yosys config (from librelane/steps/pyosys.py)
        "synth_parameters": "Key-value pairs for Yosys chparam (list)",
        "use_slang": "Use Slang frontend for SystemVerilog",
        "slang_arguments": "Arguments passed to the Slang frontend",
        "synth_clockgate_min_width": "Minimum group size for clock-gating",
        "synth_corner": "Synthesis timing corner override",
        "synth_show": "Generate Yosys graphviz output",
        "yosys_log_level": "Yosys log level (ALL, WARNING, ERROR)",

        # Yosys.Synthesis config (from librelane/steps/pyosys.py SynthesisCommon)
        "synth_checks_allow_tristate": "Ignore multi-driver warnings for tristate",
        "synth_autoname": "Generate human-readable instance names",
        "synth_strategy": "ABC synthesis strategy",
        "synth_abc_buffering": "Enable ABC cell buffering",
        "synth_abc_legacy_refactor": "Use legacy ABC refactor",
        "synth_abc_legacy_rewrite": "Use legacy ABC rewrite",
        "synth_abc_dff": "Pass DFFs through ABC",
        "synth_abc_use_mfs3": "Experimental SAT-based remapping",
        "synth_abc_area_use_nf": "Experimental &nf area mapper",
        "synth_direct_wire_buffering": "Buffer directly connected wires",
        "synth_splitnets": "Split multi-bit nets",
        "synth_sizing": "Enable ABC cell sizing",
        "synth_hierarchy_mode": "Hierarchy handling mode",
        "synth_keep_hierarchy_min_cost": "Keep hierarchy for modules above estimated gate cost",
        "synth_keep_hierarchy_instances": "Instances to mark keep_hierarchy",
        "synth_keep_hierarchy_modules": "Modules to mark keep_hierarchy",
        "synth_share_resources": "Merge shareable resources",
        "synth_adder_type": "Adder mapping type",
        "synth_extra_mapping_file": "File - Extra techmap file",
        "synth_elaborate_only": "Elaborate without logic mapping",
        "synth_mul_booth": "Use Booth encoding for multipliers",
        "synth_tie_undefined": "Tie undefined values (high/low/empty)",
        "synth_write_noattr": "Omit Verilog attributes from netlist",
        "synth_normalize_single_bit_vectors": "Normalize [0:0] vectors to scalar wires",

        # Post-synthesis checker config (from librelane/steps/checker.py)
        "error_on_unmapped_cells": "Error on unmapped cells (Step 7)",
        "error_on_synth_checks": "Error on synthesis check failures (Step 8)",
        "error_on_nl_assign_statements": "Error on assign statements in netlist (Step 9)",
        "error_on_pdn_violations": "bool - Error on power grid violations (Step 29)",
        "error_on_tr_drc": "bool - Error on routing DRC violations (Step 49)",
        "error_on_disconnected_pins": "bool - Error on critical disconnected pins (Step 51)",
        "error_on_long_wire": "bool - Error on wires exceeding threshold (Step 53)",
        "error_on_illegal_overlaps": "bool - Error on illegal overlaps (Step 70)",
        "error_on_lvs_error": "bool - Error on LVS errors (Step 72)",

        # OpenROADStep config (from librelane/steps/openroad.py lines 192-223)
        "set_rc_verbose": "bool - Echo set_rc commands",
        "pdn_connect_macros_to_grid": "bool - Connect macros to top level power grid",
        "pdn_macro_connections": "List[str] - Explicit macro power connections",
        "pdn_enable_global_connections": "bool - Enable global PDN connections",
        "sta_extra_corner_tcl_file": "File - Extra OpenROAD corner Tcl file (optional)",
        "deduplicate_corners": "bool - Deduplicate equivalent PnR corners",
        "fp_def_template": "File - DEF template for floorplan (optional)",
        "io_pin_order_cfg": "File - Pin order config for custom IO placement (optional)",

        # ApplyDEFTemplate config (odb.py lines 249-259)
        "fp_template_match_mode": "string - DEF template pin matching mode",
        "fp_template_copy_power_pins": "bool - Copy power pins from DEF template",

        # OpenROADStep.prepare_env() config (from librelane/steps/openroad.py lines 242-258)
        "extra_excluded_cells": "List[str] - Additional cells to exclude from PnR",

        # MultiCornerSTA config (from librelane/steps/openroad.py lines 534-556)
        "sta_macro_prioritize_nl": "bool - Prioritize netlists+SPEF over LIB for macros",
        "sta_max_violator_count": "int - Max violators in report (0 = unlimited)",
        "sta_threads": "int - Max parallel STA corners (0 = auto)",

        # OpenROAD.IRDropReport config (openroad.py:1813-1819)
        "vsrc_loc_files": "dict - Map of net names to PSM location files for IR drop",

        # MagicStep config (magic.py:76-142)
        "magic_def_labels": "bool - Read labels with DEF files",
        "magic_gds_polygon_subcells": "bool - Use polygon subcells for speed",
        "magic_def_no_blockages": "bool - Ignore DEF blockages",
        "magic_include_gds_pointers": "bool - Include GDS pointers in mag files",
        "magic_capture_errors": "bool - Capture and quit on Magic errors",
        # Magic.SpiceExtraction config (magic.py:435-472)
        "magic_ext_use_gds": "bool - Use GDS for SPICE extraction",
        "magic_ext_abstract_cells": "List[str] - Cells to abstract in extraction",
        "magic_no_ext_unique": "bool - Skip extract unique for label connections",
        "magic_ext_short_resistor": "bool - Add resistors to shorts",
        "magic_ext_abstract": "bool - Extract based on black-boxed cells",
        "magic_feedback_conversion_threshold": "int - Max feedback items for KLayout conversion",
        # Magic.StreamOut config (magic.py:264-293)
        "magic_zeroize_origin": "bool - Move layout origin to 0,0",
        "magic_disable_cif_info": "bool - Disable CIF info in GDSII",
        "magic_macro_std_cell_source": "string - Macro std cell source (PDK/macro)",
        # KLayout.StreamOut config
        "klayout_conflict_resolution": "string - KLayout stream-out cell conflict resolution",

        # OpenROAD.RCX config (openroad.py:1679-1702)
        "rcx_merge_via_wire_res": "bool - Merge via and wire resistances",
        "rcx_sdc_file": "File - SDC file for RCX-based STA (optional)",

        # OpenROAD.CutRows config (from librelane/steps/openroad.py lines 1916-1933)
        "fp_macro_horizontal_halo": "string - Horizontal halo around macros (um)",
        "fp_macro_vertical_halo": "string - Vertical halo around macros (um)",

        # Odb.AddPDNObstructions / Odb.RemovePDNObstructions
        "pdn_obstructions": "List[str] - PDN obstructions (layer llx lly urx ury)",

        # Odb.AddRoutingObstructions / Odb.RemoveRoutingObstructions
        "routing_obstructions": "List[str] - Routing obstructions (layer llx lly urx ury)",

        # io_layer_variables (common_variables.py lines 19-46) - IOPlacement, CustomIOPlacement
        "io_pin_v_extension": "string - Extend vertical IO pins outside die (um)",
        "io_pin_h_extension": "string - Extend horizontal IO pins outside die (um)",
        "io_pin_v_thickness_mult": "string - Vertical pin thickness multiplier",
        "io_pin_h_thickness_mult": "string - Horizontal pin thickness multiplier",

        # CustomIOPlacement config (odb.py lines 673-680)
        "errors_on_unmatched_io": "string - Error on unmatched IO pins",

        # GlobalPlacement config
        "pl_target_density_pct": "string - Target placement density percentage",
        "io_pin_placement_mode": "string - IO placement mode",
        "pl_skip_initial_placement": "bool - Skip initial placement",
        "pl_wire_length_coef": "string - Wirelength coefficient",
        "pl_min_phi_coefficient": "string - Min phi coefficient",
        "pl_max_phi_coefficient": "string - Max phi coefficient",
        "pl_keep_resize_below_overflow": "string - Keep resize changes below this overflow",
        "rt_clock_min_layer": "string - Min clock routing layer",
        "rt_clock_max_layer": "string - Max clock routing layer",
        "grt_adjustment": "string - Global routing adjustment",
        "grt_macro_extension": "int - Macro blockage extension",
        "pl_timing_driven": "bool - Timing driven placement",
        "pl_routability_driven": "bool - Routability driven placement",
        "pl_routability_overflow_threshold": "string - Routability overflow threshold",
        "fp_core_util": "string - Core utilization percentage",

        # OpenROAD.GeneratePDN (pdn_variables from common_variables.py)
        "pdn_skiptrim": "bool - Skip metal trim step during pdngen",
        "pdn_core_ring": "bool - Enable core ring around design",
        "pdn_enable_rails": "bool - Enable rails in power grid",
        "pdn_horizontal_halo": "string - Horizontal halo around macros for PDN (um)",
        "pdn_vertical_halo": "string - Vertical halo around macros for PDN (um)",
        "pdn_multilayer": "bool - Use multiple layers in power grid",
        "pdn_cfg": "File - Custom PDN configuration file",

        # grt_variables (common_variables.py:285-319) - ResizerStep subclasses
        "diode_padding": "int - Diode cell padding in sites",
        "grt_allow_congestion": "bool - Allow congestion during global routing",
        "grt_antenna_repair_iters": "int - Max iterations for global antenna repairs",
        "grt_overflow_iters": "int - Max iterations for overflow convergence",
        "grt_antenna_repair_margin": "int - Margin % to over-fix antenna violations",
        "grt_antenna_repair_jumper_only": "bool - Only use jumpers to fix antenna violations",
        "grt_antenna_repair_diode_only": "bool - Only use antenna diodes to fix antenna violations",

        # dpl_variables (common_variables.py:255-283) - ResizerStep subclasses
        "pl_optimize_mirroring": "bool - Run optimize_mirroring during detailed placement",
        "pl_max_displacement_x": "string - Max X displacement for placement (um)",
        "pl_max_displacement_y": "string - Max Y displacement for placement (um)",

        # rsz_variables (common_variables.py:321-340) - ResizerStep subclasses
        "rsz_dont_touch_rx": "string - Regex for don't touch nets/instances",
        "rsz_dont_touch_list": "List[str] - List of don't touch nets/instances",
        "rsz_corners": "List[str] - IPVT corners for resizer (empty = STA_CORNERS)",

        # RepairDesignPostGPL config_vars (openroad.py:2119-2178)
        "design_repair_buffer_input_ports": "bool - Buffer input ports during design repair",
        "design_repair_buffer_output_ports": "bool - Buffer output ports during design repair",
        "design_repair_tie_fanout": "bool - Repair tie cells fanout",
        "design_repair_tie_separation": "bool - Allow tie separation",
        "design_repair_max_wire_length": "string - Max wire length for buffering (um)",
        "design_repair_max_slew_pct": "string - Slew margin percentage",
        "design_repair_max_cap_pct": "string - Capacitance margin percentage",
        "design_repair_remove_buffers": "bool - Remove synthesis buffers",

        # Odb.ManualGlobalPlacement config (odb.py:987-993)
        "manual_global_placements": "string - JSON dict of instance to placement",

        # OpenROAD.CTS config_vars (openroad.py:2016-2084)
        "cts_sink_clustering_size": "int - Max sinks per cluster (default 25)",
        "cts_sink_clustering_max_diameter": "string - Max cluster diameter in um (default 50)",
        "cts_balance_levels": "string - Balance CTS levels override",
        "cts_sink_buffer_max_cap_derate_pct": "string - CTS sink buffer max cap derate percentage",
        "cts_delay_buffer_derate_pct": "string - CTS delay buffer derate percentage",
        "cts_obstruction_aware": "string - CTS obstruction-aware buffering override",
        "cts_sink_clustering_enable": "bool - Enable CTS sink clustering",
        "cts_macro_clustering_size": "string - Max macro sinks per cluster",
        "cts_macro_clustering_max_diameter": "string - Max macro cluster diameter in um",
        "cts_clk_max_wire_length": "string - Max clock wire length in um (default 0)",
        "cts_disable_post_processing": "bool - Disable post-CTS outlier processing",
        "cts_distance_between_buffers": "string - Distance between buffers in um (default 0)",
        "cts_corners": "List[str] - IPVT corners for CTS (empty = STA_CORNERS)",
        "cts_max_cap": "string - Max capacitance for CTS characterization in pF",
        "cts_max_slew": "string - Max slew for CTS characterization in ns",
        "cts_apply_ndr": "string - CTS non-default-rule strategy",

        # ResizerTimingPostCTS/PostGRT config_vars (openroad.py:2254-2302)
        "pl_resizer_hold_slack_margin": "string - Hold slack margin in ns (default 0.1)",
        "pl_resizer_setup_slack_margin": "string - Setup slack margin in ns (default 0.05)",
        "pl_resizer_hold_max_buffer_pct": "string - Max hold buffers as % of instances (default 50)",
        "pl_resizer_setup_max_buffer_pct": "string - Max setup buffers as % of instances (default 50)",
        "pl_resizer_allow_setup_vios": "bool - Allow setup violations when fixing hold",
        "pl_resizer_setup_gate_cloning": "bool - Enable gate cloning for setup fixes (default True)",
        "pl_resizer_setup_buffering": "bool - Enable setup rebuffering and load splitting",
        "pl_resizer_setup_buffer_removal": "bool - Enable setup buffer removal",
        "pl_resizer_setup_repair_tns_pct": "string - Percentage of setup violating endpoints to repair",
        "pl_resizer_setup_max_util_pct": "string - Max setup repair utilization percentage",
        "pl_resizer_hold_repair_tns_pct": "string - Percentage of hold violating endpoints to repair",
        "pl_resizer_hold_max_util_pct": "string - Max hold repair utilization percentage",
        "pl_resizer_fix_hold_first": "bool - Fix hold before setup (experimental)",
        # RepairDesignPostGRT config_vars
        "grt_design_repair_run_grt": "bool - Run GRT before/after resizer in post-GRT repair",
        "grt_design_repair_max_wire_length": "string - Max wire length for buffer insertion (0=none)",
        "grt_design_repair_max_slew_pct": "string - Slew margin % during post-GRT repair",
        "grt_design_repair_max_cap_pct": "string - Cap margin % during post-GRT repair",
        # ResizerTimingPostGRT config_vars
        "grt_resizer_hold_slack_margin": "string - Hold slack margin (ns)",
        "grt_resizer_setup_slack_margin": "string - Setup slack margin (ns)",
        "grt_resizer_hold_max_buffer_pct": "string - Max buffers for hold fixes (%)",
        "grt_resizer_setup_max_buffer_pct": "string - Max buffers for setup fixes (%)",
        "grt_resizer_allow_setup_vios": "bool - Allow setup violations when fixing hold",
        "grt_resizer_setup_gate_cloning": "bool - Enable gate cloning for setup fixes",
        "grt_resizer_run_grt": "bool - Run GRT after resizer steps",
        "grt_resizer_setup_buffering": "bool - Enable setup rebuffering and load splitting",
        "grt_resizer_setup_buffer_removal": "bool - Enable setup buffer removal",
        "grt_resizer_setup_repair_tns_pct": "string - Percentage of setup violating endpoints to repair",
        "grt_resizer_setup_max_util_pct": "string - Max setup repair utilization percentage",
        "grt_resizer_hold_repair_tns_pct": "string - Percentage of hold violating endpoints to repair",
        "grt_resizer_hold_max_util_pct": "string - Max hold repair utilization percentage",
        "grt_resizer_fix_hold_first": "bool - Fix hold before setup (experimental)",
        # Odb.DiodesOnPorts config_vars
        "diode_on_ports": "string - Insert diodes on ports: none, in, out, both",
        # DetailedRouting config_vars
        "drt_threads": "int - Threads for detailed routing (0=auto)",
        "drt_opt_iters": "int - Max optimization iterations",
        "drt_save_snapshots": "bool - Save detailed routing iteration ODB snapshots",
        "drt_antenna_repair_iters": "int - Max post-DRT antenna repair iterations",
        "drt_antenna_repair_margin": "int - Margin % to over-fix post-DRT antenna violations",
        "drt_antenna_repair_jumper_only": "bool - Only use jumpers for post-DRT antenna repair",
        "drt_antenna_repair_diode_only": "bool - Only use diodes for post-DRT antenna repair",
        "drt_save_drc_report_iters": "string - Iteration interval for DRT DRC reports",
        "non_default_rules": "string - JSON object of non-default routing rules",
        "drt_assign_ndr": "string - JSON object mapping net regexes to NDR names",
        # KLayout/Magic/OpenROAD extra files (flow.py:456-480)
        "extra_lefs": "List[File] - Extra LEF files for macros",
        "extra_gds_files": "List[File] - Extra GDS files for macros",
        # Magic.WriteLEF config (magic.py:218-237)
        "magic_lef_write_use_gds": "bool - Use GDS for LEF writing",
        "magic_write_full_lef": "bool - Include all shapes in macro LEF",
        "magic_write_lef_pinonly": "bool - Mark only port labels as pins",
        # KLayout.XOR config (klayout.py:258-262)
        "klayout_xor_threads": "int - Number of threads for KLayout XOR (0=auto)",
        # Checker.XOR config (checker.py:288-294)
        "error_on_xor_error": "bool - Error on XOR differences",
        # Magic.DRC config (magic.py:380-386)
        "magic_drc_use_gds": "bool - Run Magic DRC on GDS instead of DEF",
        "magic_gds_flatglob": "List[str] - Magic GDS cell-name patterns to flatten for DRC",
        "magic_drc_maglefs": "List[File] - Magic abstract LEF views to load before DRC",
        # Magic.DRC gating (classic.py:239-242)
        "run_magic_drc": "bool - Enable Magic DRC step",
        # Checker.MagicDRC config (checker.py:205-211)
        "error_on_magic_drc": "bool - Error on Magic DRC violations",
        # KLayout.DRC config (klayout.py:363-368)
        "klayout_drc_threads": "int - Number of threads for KLayout DRC (0=auto)",
        # KLayout.DRC gating (classic.py:247-250)
        "run_klayout_drc": "bool - Enable KLayout DRC step",
        # Checker.KLayoutDRC config (checker.py:421-427)
        "error_on_klayout_drc": "bool - Error on KLayout DRC violations",
        # Netgen.LVS config (Step 71)
        "run_lvs": "bool - Enable Netgen LVS step",
        "lvs_include_marco_netlists": "bool - Include macro netlists in LVS",
        "lvs_flatten_cells": "List[str] - Cells to flatten during LVS",
        "lvs_ignore_cells": "List[str] - Cells to ignore during LVS",
        "extra_spice_models": "List[File] - Extra SPICE models for LVS",
        # Yosys.EQY config (Step 73)
        "run_eqy": "bool - Enable EQY formal equivalence check (default: False)",
        "eqy_script": "File - Custom EQY script",
        "eqy_force_accept_pdk": "bool - Force EQY on unsupported PDK",
        "macro_placement_cfg": "File - Deprecated macro placement config",
        # TimingViolations checker config (Steps 74-77)
        "setup_violation_corners": "List[str] - Corners for setup violation checking",
        "hold_violation_corners": "List[str] - Corners for hold violation checking",
        "max_slew_violation_corners": "List[str] - Corners for max slew checking",
        "max_cap_violation_corners": "List[str] - Corners for max cap checking",
    },
)
