# Common utilities for librelane flow rules

load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo", "PdkInfo", "MacroInfo")

# Universal config keys required by all steps (from librelane's flow_common_variables)
# These must always be present - steps add their own keys on top of these
# Derived from librelane/config/flow.py: pdk_variables + scl_variables + option_variables
BASE_CONFIG_KEYS = [
    # pdk_variables (required)
    "PDK",
    "STD_CELL_LIBRARY",
    "VDD_PIN",
    "VDD_PIN_VOLTAGE",
    "GND_PIN",
    "TECH_LEFS",
    "PRIMARY_GDSII_STREAMOUT_TOOL",
    "DEFAULT_CORNER",
    "STA_CORNERS",
    "FP_TRACKS_INFO",
    "FP_TAPCELL_DIST",
    "FP_IO_HLAYER",
    "FP_IO_VLAYER",
    "RT_MIN_LAYER",
    "RT_MAX_LAYER",
    # scl_variables (required)
    "SCL_GROUND_PINS",
    "SCL_POWER_PINS",
    "FILL_CELL",
    "DECAP_CELL",
    "LIB",
    "CELL_LEFS",
    "CELL_GDS",
    "SYNTH_EXCLUDED_CELL_FILE",
    "PNR_EXCLUDED_CELL_FILE",
    "OUTPUT_CAP_LOAD",
    "MAX_FANOUT_CONSTRAINT",
    "CLOCK_UNCERTAINTY_CONSTRAINT",
    "CLOCK_TRANSITION_CONSTRAINT",
    "TIME_DERATING_CONSTRAINT",
    "IO_DELAY_CONSTRAINT",
    "SYNTH_DRIVING_CELL",
    "SYNTH_TIEHI_CELL",
    "SYNTH_TIELO_CELL",
    "SYNTH_BUFFER_CELL",
    "WELLTAP_CELL",
    "ENDCAP_CELL",
    "DIODE_CELL",
    "PLACE_SITE",
    "CELL_PAD_EXCLUDE",
    # option_variables (required)
    "DESIGN_NAME",
    "CLOCK_PORT",
    "CLOCK_PERIOD",
]

def _add_optional(config, key, value):
    """Add a value to config if it's not None."""
    if value != None:
        config[key] = value

def _add_optional_file(config, key, f):
    """Add a file path to config if the file is not None."""
    if f != None:
        config[key] = f.path

def _add_optional_file_list(config, key, files):
    """Add a list of file paths to config if the list is not None/empty."""
    if files:
        config[key] = [f.path for f in files]

def _add_optional_file_dict(config, key, file_dict):
    """Add a dict of file paths to config if the dict is not None/empty."""
    if file_dict:
        config[key] = {k: f.path for k, f in file_dict.items()}

def create_librelane_config(input_info, state_info, required_keys):
    """Create a config dict for librelane.

    Args:
        input_info: LibrelaneInput with flow configuration
        state_info: LibrelaneInfo with current design state (can be None for init)
        required_keys: List of config keys this step uses. Each step must declare
            which config keys it uses, matching librelane's config_vars. This
            enables better Bazel caching - changing a config value only
            invalidates steps that use it.
    """
    pdk = input_info.pdk_info

    config = {
        # Design-level config
        "DESIGN_NAME": input_info.top,
        "CLOCK_PORT": input_info.clock_port,
        "CLOCK_PERIOD": float(input_info.clock_period),
        "VERILOG_FILES": get_verilog_paths(input_info, state_info),

        # PDK identity
        "PDK": pdk.name,
        "STD_CELL_LIBRARY": pdk.scl,

        # PDK config - power/ground
        "VDD_PIN": pdk.vdd_pin,
        "GND_PIN": pdk.gnd_pin,
        "SCL_POWER_PINS": pdk.scl_power_pins,
        "SCL_GROUND_PINS": pdk.scl_ground_pins,

        # PDK config - cells (as paths for librelane)
        "CELL_LEFS": [f.path for f in pdk.cell_lefs],
        "CELL_GDS": [f.path for f in pdk.cell_gds],

        # PDK config - tech LEFs (corner -> path)
        "TECH_LEFS": {corner: f.path for corner, f in pdk.tech_lefs.items()},

        # PDK config - timing
        "DEFAULT_CORNER": pdk.default_corner,
        "STA_CORNERS": pdk.sta_corners,

        # PDK config - floorplanning
        "FP_TRACKS_INFO": pdk.fp_tracks_info.path,
        "FP_TAPCELL_DIST": pdk.fp_tapcell_dist,
        "FP_IO_HLAYER": pdk.fp_io_hlayer,
        "FP_IO_VLAYER": pdk.fp_io_vlayer,
        "PLACE_SITE": pdk.place_site,

        # PDK config - routing
        "RT_MIN_LAYER": pdk.rt_min_layer,
        "RT_MAX_LAYER": pdk.rt_max_layer,
        "GRT_LAYER_ADJUSTMENTS": pdk.grt_layer_adjustments,

        # PDK config - placement
        "GPL_CELL_PADDING": pdk.gpl_cell_padding,
        "DPL_CELL_PADDING": pdk.dpl_cell_padding,

        # PDK config - CTS
        "CTS_ROOT_BUFFER": pdk.cts_root_buffer,
        "CTS_CLK_BUFFERS": pdk.cts_clk_buffers,

        # PDK config - synthesis cells
        "SYNTH_DRIVING_CELL": pdk.synth_driving_cell,
        "SYNTH_TIEHI_CELL": pdk.synth_tiehi_cell,
        "SYNTH_TIELO_CELL": pdk.synth_tielo_cell,
        "SYNTH_BUFFER_CELL": pdk.synth_buffer_cell,
        "SYNTH_EXCLUDED_CELL_FILE": pdk.synth_excluded_cell_file.path,
        "PNR_EXCLUDED_CELL_FILE": pdk.pnr_excluded_cell_file.path,

        # PDK config - placement cells
        "WELLTAP_CELL": pdk.welltap_cell,
        "ENDCAP_CELL": pdk.endcap_cell,
        "FILL_CELL": pdk.fill_cell,
        "DECAP_CELL": pdk.decap_cell,
        "DIODE_CELL": pdk.diode_cell,
        "CELL_PAD_EXCLUDE": pdk.cell_pad_exclude,

        # PDK config - constraints
        "OUTPUT_CAP_LOAD": pdk.output_cap_load,
        "MAX_FANOUT_CONSTRAINT": pdk.max_fanout_constraint,
        "CLOCK_UNCERTAINTY_CONSTRAINT": pdk.clock_uncertainty_constraint,
        "CLOCK_TRANSITION_CONSTRAINT": pdk.clock_transition_constraint,
        "TIME_DERATING_CONSTRAINT": pdk.time_derating_constraint,
        "IO_DELAY_CONSTRAINT": pdk.io_delay_constraint,

        # PDK config - signoff
        "PRIMARY_GDSII_STREAMOUT_TOOL": pdk.primary_gdsii_streamout_tool,
    }

    # Add optional fields if present
    if pdk.max_transition_constraint:
        config["MAX_TRANSITION_CONSTRAINT"] = pdk.max_transition_constraint
    if pdk.max_capacitance_constraint:
        config["MAX_CAPACITANCE_CONSTRAINT"] = pdk.max_capacitance_constraint
    if pdk.vdd_pin_voltage:
        config["VDD_PIN_VOLTAGE"] = pdk.vdd_pin_voltage

    # Step-specific optional fields
    _add_optional(config, "EXTRA_SITES", pdk.extra_sites)
    _add_optional(config, "FP_IO_HLENGTH", pdk.fp_io_hlength)
    _add_optional(config, "FP_IO_VLENGTH", pdk.fp_io_vlength)
    _add_optional(config, "FP_IO_MIN_DISTANCE", pdk.fp_io_min_distance)
    _add_optional(config, "FP_PDN_RAIL_LAYER", pdk.fp_pdn_rail_layer)
    _add_optional(config, "FP_PDN_RAIL_WIDTH", pdk.fp_pdn_rail_width)
    _add_optional(config, "FP_PDN_RAIL_OFFSET", pdk.fp_pdn_rail_offset)
    _add_optional(config, "FP_PDN_HORIZONTAL_LAYER", pdk.fp_pdn_horizontal_layer)
    _add_optional(config, "FP_PDN_VERTICAL_LAYER", pdk.fp_pdn_vertical_layer)
    _add_optional(config, "FP_PDN_HOFFSET", pdk.fp_pdn_hoffset)
    _add_optional(config, "FP_PDN_VOFFSET", pdk.fp_pdn_voffset)
    _add_optional(config, "FP_PDN_HPITCH", pdk.fp_pdn_hpitch)
    _add_optional(config, "FP_PDN_VPITCH", pdk.fp_pdn_vpitch)
    _add_optional(config, "FP_PDN_HSPACING", pdk.fp_pdn_hspacing)
    _add_optional(config, "FP_PDN_VSPACING", pdk.fp_pdn_vspacing)
    _add_optional(config, "FP_PDN_HWIDTH", pdk.fp_pdn_hwidth)
    _add_optional(config, "FP_PDN_VWIDTH", pdk.fp_pdn_vwidth)
    _add_optional(config, "FP_PDN_CORE_RING_HOFFSET", pdk.fp_pdn_core_ring_hoffset)
    _add_optional(config, "FP_PDN_CORE_RING_VOFFSET", pdk.fp_pdn_core_ring_voffset)
    _add_optional(config, "FP_PDN_CORE_RING_HSPACING", pdk.fp_pdn_core_ring_hspacing)
    _add_optional(config, "FP_PDN_CORE_RING_VSPACING", pdk.fp_pdn_core_ring_vspacing)
    _add_optional(config, "FP_PDN_CORE_RING_HWIDTH", pdk.fp_pdn_core_ring_hwidth)
    _add_optional(config, "FP_PDN_CORE_RING_VWIDTH", pdk.fp_pdn_core_ring_vwidth)
    _add_optional(config, "HEURISTIC_ANTENNA_THRESHOLD", pdk.heuristic_antenna_threshold)
    _add_optional_file(config, "MAGICRC", pdk.magicrc)
    _add_optional_file(config, "MAGIC_TECH", pdk.magic_tech)
    _add_optional_file(config, "MAGIC_PDK_SETUP", pdk.magic_pdk_setup)
    _add_optional_file_list(config, "CELL_MAGS", pdk.cell_mags)
    _add_optional_file_list(config, "CELL_MAGLEFS", pdk.cell_maglefs)
    _add_optional_file(config, "KLAYOUT_TECH", pdk.klayout_tech)
    _add_optional_file(config, "KLAYOUT_PROPERTIES", pdk.klayout_properties)
    _add_optional_file(config, "KLAYOUT_DEF_LAYER_MAP", pdk.klayout_def_layer_map)
    _add_optional_file(config, "KLAYOUT_DRC_RUNSET", pdk.klayout_drc_runset)
    _add_optional(config, "KLAYOUT_XOR_IGNORE_LAYERS", pdk.klayout_xor_ignore_layers)
    _add_optional(config, "KLAYOUT_XOR_TILE_SIZE", pdk.klayout_xor_tile_size)
    _add_optional_file(config, "NETGEN_SETUP", pdk.netgen_setup)
    _add_optional_file_dict(config, "RCX_RULESETS", pdk.rcx_rulesets)
    _add_optional_file(config, "SYNTH_LATCH_MAP", pdk.synth_latch_map)
    _add_optional_file(config, "SYNTH_TRISTATE_MAP", pdk.synth_tristate_map)
    _add_optional_file(config, "SYNTH_CSA_MAP", pdk.synth_csa_map)
    _add_optional_file(config, "SYNTH_RCA_MAP", pdk.synth_rca_map)
    _add_optional_file(config, "SYNTH_FA_MAP", pdk.synth_fa_map)
    _add_optional_file(config, "SYNTH_MUX_MAP", pdk.synth_mux_map)
    _add_optional_file(config, "SYNTH_MUX4_MAP", pdk.synth_mux4_map)
    _add_optional(config, "IGNORE_DISCONNECTED_MODULES", pdk.ignore_disconnected_modules)
    _add_optional(config, "TIMING_VIOLATION_CORNERS", pdk.timing_violation_corners)

    # Add LIB dict (corner -> list of file paths)
    config["LIB"] = {corner: [f.path for f in files] for corner, files in pdk.lib.items()}

    # Add macros config
    macros = get_macros_config(input_info)
    if macros:
        config["MACROS"] = macros

    # Add custom SDC files if provided
    if input_info.pnr_sdc_file:
        config["PNR_SDC_FILE"] = input_info.pnr_sdc_file.path
    if input_info.signoff_sdc_file:
        config["SIGNOFF_SDC_FILE"] = input_info.signoff_sdc_file.path

    # Add optional Verilog source configuration
    if input_info.verilog_include_dirs:
        config["VERILOG_INCLUDE_DIRS"] = input_info.verilog_include_dirs
    if input_info.verilog_defines:
        config["VERILOG_DEFINES"] = input_info.verilog_defines

    # Verilator.Lint config (from librelane/steps/verilator.py lines 39-87)
    config["VERILOG_POWER_DEFINE"] = input_info.verilog_power_define
    config["LINTER_INCLUDE_PDK_MODELS"] = input_info.linter_include_pdk_models
    config["LINTER_RELATIVE_INCLUDES"] = input_info.linter_relative_includes
    config["LINTER_ERROR_ON_LATCH"] = input_info.linter_error_on_latch
    if input_info.linter_defines:
        config["LINTER_DEFINES"] = input_info.linter_defines
    # CELL_VERILOG_MODELS comes from PDK
    _add_optional_file_list(config, "CELL_VERILOG_MODELS", pdk.cell_verilog_models)
    # EXTRA_VERILOG_MODELS from user input
    if input_info.extra_verilog_models:
        config["EXTRA_VERILOG_MODELS"] = [f.path for f in input_info.extra_verilog_models]

    # Checker config (from librelane/steps/checker.py)
    config["ERROR_ON_LINTER_TIMING_CONSTRUCTS"] = input_info.error_on_linter_timing_constructs
    config["ERROR_ON_LINTER_ERRORS"] = input_info.error_on_linter_errors
    config["ERROR_ON_LINTER_WARNINGS"] = input_info.error_on_linter_warnings

    # Yosys config (from librelane/steps/pyosys.py)
    if input_info.synth_parameters:
        config["SYNTH_PARAMETERS"] = input_info.synth_parameters
    config["USE_SYNLIG"] = input_info.use_synlig
    config["SYNLIG_DEFER"] = input_info.synlig_defer
    config["USE_LIGHTER"] = input_info.use_lighter
    _add_optional_file(config, "LIGHTER_DFF_MAP", input_info.lighter_dff_map)
    config["YOSYS_LOG_LEVEL"] = input_info.yosys_log_level

    # Yosys.Synthesis config (from librelane/steps/pyosys.py SynthesisCommon)
    _add_optional(config, "TRISTATE_CELLS", pdk.tristate_cells)
    config["SYNTH_CHECKS_ALLOW_TRISTATE"] = input_info.synth_checks_allow_tristate
    config["SYNTH_AUTONAME"] = input_info.synth_autoname
    config["SYNTH_STRATEGY"] = input_info.synth_strategy
    config["SYNTH_ABC_BUFFERING"] = input_info.synth_abc_buffering
    config["SYNTH_ABC_LEGACY_REFACTOR"] = input_info.synth_abc_legacy_refactor
    config["SYNTH_ABC_LEGACY_REWRITE"] = input_info.synth_abc_legacy_rewrite
    config["SYNTH_ABC_DFF"] = input_info.synth_abc_dff
    config["SYNTH_ABC_USE_MFS3"] = input_info.synth_abc_use_mfs3
    config["SYNTH_ABC_AREA_USE_NF"] = input_info.synth_abc_area_use_nf
    config["SYNTH_DIRECT_WIRE_BUFFERING"] = input_info.synth_direct_wire_buffering
    config["SYNTH_SPLITNETS"] = input_info.synth_splitnets
    config["SYNTH_SIZING"] = input_info.synth_sizing
    config["SYNTH_HIERARCHY_MODE"] = input_info.synth_hierarchy_mode
    config["SYNTH_SHARE_RESOURCES"] = input_info.synth_share_resources
    config["SYNTH_ADDER_TYPE"] = input_info.synth_adder_type
    _add_optional_file(config, "SYNTH_EXTRA_MAPPING_FILE", input_info.synth_extra_mapping_file)
    config["SYNTH_ELABORATE_ONLY"] = input_info.synth_elaborate_only
    config["SYNTH_ELABORATE_FLATTEN"] = input_info.synth_elaborate_flatten
    config["SYNTH_MUL_BOOTH"] = input_info.synth_mul_booth
    if input_info.synth_tie_undefined:
        config["SYNTH_TIE_UNDEFINED"] = input_info.synth_tie_undefined
    config["SYNTH_WRITE_NOATTR"] = input_info.synth_write_noattr

    # Post-synthesis checker config (from librelane/steps/checker.py)
    config["ERROR_ON_UNMAPPED_CELLS"] = input_info.error_on_unmapped_cells
    config["ERROR_ON_SYNTH_CHECKS"] = input_info.error_on_synth_checks
    config["ERROR_ON_NL_ASSIGN_STATEMENTS"] = input_info.error_on_nl_assign_statements
    config["ERROR_ON_PDN_VIOLATIONS"] = input_info.error_on_pdn_violations
    config["ERROR_ON_TR_DRC"] = input_info.error_on_tr_drc
    config["ERROR_ON_DISCONNECTED_PINS"] = input_info.error_on_disconnected_pins
    config["ERROR_ON_LONG_WIRE"] = input_info.error_on_long_wire
    _add_optional(config, "WIRE_LENGTH_THRESHOLD", pdk.wire_length_threshold)

    # OpenROADStep config (from librelane/steps/openroad.py lines 192-223)
    config["PDN_CONNECT_MACROS_TO_GRID"] = input_info.pdn_connect_macros_to_grid
    if input_info.pdn_macro_connections:
        config["PDN_MACRO_CONNECTIONS"] = input_info.pdn_macro_connections
    config["PDN_ENABLE_GLOBAL_CONNECTIONS"] = input_info.pdn_enable_global_connections
    _add_optional_file(config, "FP_DEF_TEMPLATE", input_info.fp_def_template)
    _add_optional_file(config, "FP_PIN_ORDER_CFG", input_info.fp_pin_order_cfg)

    # ApplyDEFTemplate config (odb.py lines 249-259)
    config["FP_TEMPLATE_MATCH_MODE"] = input_info.fp_template_match_mode
    config["FP_TEMPLATE_COPY_POWER_PINS"] = input_info.fp_template_copy_power_pins

    # OpenROADStep.prepare_env() config (from librelane/steps/openroad.py lines 242-258)
    if input_info.extra_excluded_cells:
        config["EXTRA_EXCLUDED_CELLS"] = input_info.extra_excluded_cells
    # FALLBACK_SDC_FILE - use pnr_sdc_file as fallback (Bazel always sets this)
    if input_info.pnr_sdc_file:
        config["FALLBACK_SDC_FILE"] = input_info.pnr_sdc_file.path

    # MultiCornerSTA config (from librelane/steps/openroad.py lines 534-556)
    config["STA_MACRO_PRIORITIZE_NL"] = input_info.sta_macro_prioritize_nl
    if input_info.sta_max_violator_count:
        config["STA_MAX_VIOLATOR_COUNT"] = input_info.sta_max_violator_count
    if input_info.sta_threads:
        config["STA_THREADS"] = input_info.sta_threads

    # OpenROAD.IRDropReport config (openroad.py:1813-1819)
    if input_info.vsrc_loc_files:
        config["VSRC_LOC_FILES"] = {net: f.path for net, f in input_info.vsrc_loc_files.items()}

    # MagicStep config (magic.py:76-142)
    config["MAGIC_DEF_LABELS"] = input_info.magic_def_labels
    config["MAGIC_GDS_POLYGON_SUBCELLS"] = input_info.magic_gds_polygon_subcells
    config["MAGIC_DEF_NO_BLOCKAGES"] = input_info.magic_def_no_blockages
    config["MAGIC_INCLUDE_GDS_POINTERS"] = input_info.magic_include_gds_pointers
    config["MAGIC_CAPTURE_ERRORS"] = input_info.magic_capture_errors
    # Magic.StreamOut config (magic.py:264-293)
    config["MAGIC_ZEROIZE_ORIGIN"] = input_info.magic_zeroize_origin
    config["MAGIC_DISABLE_CIF_INFO"] = input_info.magic_disable_cif_info
    config["MAGIC_MACRO_STD_CELL_SOURCE"] = input_info.magic_macro_std_cell_source

    # OpenROAD.RCX config (openroad.py:1679-1702)
    config["RCX_MERGE_VIA_WIRE_RES"] = input_info.rcx_merge_via_wire_res
    _add_optional_file(config, "RCX_SDC_FILE", input_info.rcx_sdc_file)

    # OpenROAD.CutRows config (from librelane/steps/openroad.py lines 1916-1933)
    config["FP_MACRO_HORIZONTAL_HALO"] = float(input_info.fp_macro_horizontal_halo)
    config["FP_MACRO_VERTICAL_HALO"] = float(input_info.fp_macro_vertical_halo)

    # Odb.AddPDNObstructions / Odb.RemovePDNObstructions
    if input_info.pdn_obstructions:
        config["PDN_OBSTRUCTIONS"] = input_info.pdn_obstructions

    # Odb.AddRoutingObstructions / Odb.RemoveRoutingObstructions
    if input_info.routing_obstructions:
        config["ROUTING_OBSTRUCTIONS"] = input_info.routing_obstructions

    # io_layer_variables (common_variables.py lines 19-46) - IOPlacement, CustomIOPlacement
    config["FP_IO_VEXTEND"] = float(input_info.fp_io_vextend)
    config["FP_IO_HEXTEND"] = float(input_info.fp_io_hextend)
    config["FP_IO_VTHICKNESS_MULT"] = float(input_info.fp_io_vthickness_mult)
    config["FP_IO_HTHICKNESS_MULT"] = float(input_info.fp_io_hthickness_mult)

    # CustomIOPlacement config (odb.py lines 673-680)
    config["ERRORS_ON_UNMATCHED_IO"] = input_info.errors_on_unmatched_io

    # GlobalPlacement config
    if input_info.pl_target_density_pct:
        config["PL_TARGET_DENSITY_PCT"] = int(input_info.pl_target_density_pct)
    config["FP_PPL_MODE"] = input_info.fp_ppl_mode
    config["PL_SKIP_INITIAL_PLACEMENT"] = input_info.pl_skip_initial_placement
    config["PL_WIRE_LENGTH_COEF"] = float(input_info.pl_wire_length_coef)
    if input_info.pl_min_phi_coefficient:
        config["PL_MIN_PHI_COEFFICIENT"] = float(input_info.pl_min_phi_coefficient)
    if input_info.pl_max_phi_coefficient:
        config["PL_MAX_PHI_COEFFICIENT"] = float(input_info.pl_max_phi_coefficient)
    if input_info.rt_clock_min_layer:
        config["RT_CLOCK_MIN_LAYER"] = input_info.rt_clock_min_layer
    if input_info.rt_clock_max_layer:
        config["RT_CLOCK_MAX_LAYER"] = input_info.rt_clock_max_layer
    config["GRT_ADJUSTMENT"] = float(input_info.grt_adjustment)
    config["GRT_MACRO_EXTENSION"] = input_info.grt_macro_extension

    # GlobalPlacement-specific config (openroad.py lines 1282-1300)
    config["PL_TIME_DRIVEN"] = input_info.pl_time_driven
    config["PL_ROUTABILITY_DRIVEN"] = input_info.pl_routability_driven
    if input_info.pl_routability_overflow_threshold:
        config["PL_ROUTABILITY_OVERFLOW_THRESHOLD"] = float(
            input_info.pl_routability_overflow_threshold)
    config["FP_CORE_UTIL"] = int(input_info.fp_core_util)

    # OpenROAD.GeneratePDN (pdn_variables)
    config["FP_PDN_SKIPTRIM"] = input_info.fp_pdn_skiptrim
    config["FP_PDN_CORE_RING"] = input_info.fp_pdn_core_ring
    config["FP_PDN_ENABLE_RAILS"] = input_info.fp_pdn_enable_rails
    config["FP_PDN_HORIZONTAL_HALO"] = float(input_info.fp_pdn_horizontal_halo)
    config["FP_PDN_VERTICAL_HALO"] = float(input_info.fp_pdn_vertical_halo)
    config["FP_PDN_MULTILAYER"] = input_info.fp_pdn_multilayer
    _add_optional_file(config, "FP_PDN_CFG", input_info.fp_pdn_cfg)

    # grt_variables (common_variables.py:285-319) - ResizerStep subclasses
    if input_info.diode_padding:
        config["DIODE_PADDING"] = input_info.diode_padding
    config["GRT_ALLOW_CONGESTION"] = input_info.grt_allow_congestion
    config["GRT_ANTENNA_ITERS"] = input_info.grt_antenna_iters
    config["GRT_OVERFLOW_ITERS"] = input_info.grt_overflow_iters
    config["GRT_ANTENNA_MARGIN"] = input_info.grt_antenna_margin

    # dpl_variables (common_variables.py:255-283) - ResizerStep subclasses
    config["PL_OPTIMIZE_MIRRORING"] = input_info.pl_optimize_mirroring
    config["PL_MAX_DISPLACEMENT_X"] = int(input_info.pl_max_displacement_x)
    config["PL_MAX_DISPLACEMENT_Y"] = int(input_info.pl_max_displacement_y)

    # rsz_variables (common_variables.py:321-340) - ResizerStep subclasses
    config["RSZ_DONT_TOUCH_RX"] = input_info.rsz_dont_touch_rx
    if input_info.rsz_dont_touch_list:
        config["RSZ_DONT_TOUCH_LIST"] = input_info.rsz_dont_touch_list
    if input_info.rsz_corners:
        config["RSZ_CORNERS"] = input_info.rsz_corners

    # RepairDesignPostGPL config_vars (openroad.py:2119-2178)
    config["DESIGN_REPAIR_BUFFER_INPUT_PORTS"] = input_info.design_repair_buffer_input_ports
    config["DESIGN_REPAIR_BUFFER_OUTPUT_PORTS"] = input_info.design_repair_buffer_output_ports
    config["DESIGN_REPAIR_TIE_FANOUT"] = input_info.design_repair_tie_fanout
    config["DESIGN_REPAIR_TIE_SEPARATION"] = input_info.design_repair_tie_separation
    config["DESIGN_REPAIR_MAX_WIRE_LENGTH"] = float(input_info.design_repair_max_wire_length)
    config["DESIGN_REPAIR_MAX_SLEW_PCT"] = float(input_info.design_repair_max_slew_pct)
    config["DESIGN_REPAIR_MAX_CAP_PCT"] = float(input_info.design_repair_max_cap_pct)
    config["DESIGN_REPAIR_REMOVE_BUFFERS"] = input_info.design_repair_remove_buffers

    # Odb.ManualGlobalPlacement config (odb.py:987-993)
    if input_info.manual_global_placements:
        config["MANUAL_GLOBAL_PLACEMENTS"] = json.decode(input_info.manual_global_placements)

    # OpenROAD.CTS config_vars (openroad.py:2016-2084)
    config["CTS_SINK_CLUSTERING_SIZE"] = input_info.cts_sink_clustering_size
    config["CTS_SINK_CLUSTERING_MAX_DIAMETER"] = float(input_info.cts_sink_clustering_max_diameter)
    config["CTS_CLK_MAX_WIRE_LENGTH"] = float(input_info.cts_clk_max_wire_length)
    config["CTS_DISABLE_POST_PROCESSING"] = input_info.cts_disable_post_processing
    config["CTS_DISTANCE_BETWEEN_BUFFERS"] = float(input_info.cts_distance_between_buffers)
    if input_info.cts_corners:
        config["CTS_CORNERS"] = input_info.cts_corners
    if input_info.cts_max_cap:
        config["CTS_MAX_CAP"] = float(input_info.cts_max_cap)
    if input_info.cts_max_slew:
        config["CTS_MAX_SLEW"] = float(input_info.cts_max_slew)

    # ResizerTimingPostCTS/PostGRT config_vars (openroad.py:2254-2302)
    config["PL_RESIZER_HOLD_SLACK_MARGIN"] = float(input_info.pl_resizer_hold_slack_margin)
    config["PL_RESIZER_SETUP_SLACK_MARGIN"] = float(input_info.pl_resizer_setup_slack_margin)
    config["PL_RESIZER_HOLD_MAX_BUFFER_PCT"] = float(input_info.pl_resizer_hold_max_buffer_pct)
    config["PL_RESIZER_SETUP_MAX_BUFFER_PCT"] = float(input_info.pl_resizer_setup_max_buffer_pct)
    config["PL_RESIZER_ALLOW_SETUP_VIOS"] = input_info.pl_resizer_allow_setup_vios
    config["PL_RESIZER_GATE_CLONING"] = input_info.pl_resizer_gate_cloning
    config["PL_RESIZER_FIX_HOLD_FIRST"] = input_info.pl_resizer_fix_hold_first

    # RepairDesignPostGRT config_vars (openroad.py:2203-2234)
    config["GRT_DESIGN_REPAIR_RUN_GRT"] = input_info.grt_design_repair_run_grt
    config["GRT_DESIGN_REPAIR_MAX_WIRE_LENGTH"] = float(input_info.grt_design_repair_max_wire_length)
    config["GRT_DESIGN_REPAIR_MAX_SLEW_PCT"] = float(input_info.grt_design_repair_max_slew_pct)
    config["GRT_DESIGN_REPAIR_MAX_CAP_PCT"] = float(input_info.grt_design_repair_max_cap_pct)

    # ResizerTimingPostGRT config_vars (openroad.py:2323-2381)
    config["GRT_RESIZER_HOLD_SLACK_MARGIN"] = float(input_info.grt_resizer_hold_slack_margin)
    config["GRT_RESIZER_SETUP_SLACK_MARGIN"] = float(input_info.grt_resizer_setup_slack_margin)
    config["GRT_RESIZER_HOLD_MAX_BUFFER_PCT"] = float(input_info.grt_resizer_hold_max_buffer_pct)
    config["GRT_RESIZER_SETUP_MAX_BUFFER_PCT"] = float(input_info.grt_resizer_setup_max_buffer_pct)
    config["GRT_RESIZER_ALLOW_SETUP_VIOS"] = input_info.grt_resizer_allow_setup_vios
    config["GRT_RESIZER_GATE_CLONING"] = input_info.grt_resizer_gate_cloning
    config["GRT_RESIZER_RUN_GRT"] = input_info.grt_resizer_run_grt
    config["GRT_RESIZER_FIX_HOLD_FIRST"] = input_info.grt_resizer_fix_hold_first

    # Odb.DiodesOnPorts config_vars (odb.py:738-744)
    config["DIODE_ON_PORTS"] = input_info.diode_on_ports

    # DetailedRouting config_vars (openroad.py:1593-1616)
    if input_info.drt_threads > 0:
        config["DRT_THREADS"] = input_info.drt_threads
    if input_info.drt_min_layer:
        config["DRT_MIN_LAYER"] = input_info.drt_min_layer
    if input_info.drt_max_layer:
        config["DRT_MAX_LAYER"] = input_info.drt_max_layer
    config["DRT_OPT_ITERS"] = input_info.drt_opt_iters

    # Filter to only include required_keys
    # Steps that need BASE_CONFIG_KEYS must explicitly include them
    return {k: v for k, v in config.items() if k in required_keys}

# Mapping of LibrelaneInfo field names to librelane state keys
# Most are identical, but this allows for any future differences
STATE_FIELD_MAPPING = {
    "nl": "nl",
    "pnl": "pnl",
    "def": "def",
    "odb": "odb",
    "sdc": "sdc",
    "sdf": "sdf",
    "spef": "spef",
    "lib": "lib",
    "gds": "gds",
    "mag_gds": "mag_gds",
    "klayout_gds": "klayout_gds",
    "lef": "lef",
    "mag": "mag",
    "spice": "spice",
    "json_h": "json_h",
    "vh": "vh",
}

# Reverse mapping for deserialize
STATE_KEY_TO_FIELD = {v: k for k, v in STATE_FIELD_MAPPING.items()}

# Fields that can have multiple files (dict keyed by corner name)
MULTI_FILE_FIELDS = ["sdf", "spef", "lib"]

def serialize_state(src_info):
    """Serialize LibrelaneInfo to a state dict for librelane.

    Converts File objects to their paths. Does NOT include metrics -
    those are merged from state_out.json at execution time.

    Args:
        src_info: LibrelaneInfo provider

    Returns:
        Dict suitable for JSON encoding as state_in.json (without metrics)
    """
    state = {}

    # Serialize each view field
    for field, state_key in STATE_FIELD_MAPPING.items():
        value = getattr(src_info, field, None)
        if value == None:
            state[state_key] = None
        elif field in MULTI_FILE_FIELDS:
            # Multi-file fields are dicts
            if type(value) == "dict":
                state[state_key] = {k: v.path for k, v in value.items()}
            else:
                state[state_key] = None
        else:
            # Single file
            state[state_key] = value.path

    # Metrics will be merged from previous state_out.json at execution time
    state["metrics"] = {}

    return state

def deserialize_state(state_out_content, declared_outputs, prev_info):
    """Deserialize librelane state_out.json to LibrelaneInfo fields.

    Validates that all paths in state_out match either:
    - A declared Bazel output file
    - An unchanged path from the input state

    Args:
        state_out_content: JSON string of state_out.json
        declared_outputs: Dict mapping basename to declared File object
        prev_info: Previous LibrelaneInfo (for unchanged values)

    Returns:
        Dict of field values for new LibrelaneInfo

    Fails if state_out contains unknown keys or paths that can't be mapped.
    """
    state = json.decode(state_out_content)

    # Extract and remove metrics
    metrics = state.pop("metrics", {})
    result = {
        "metrics": json.encode(metrics) if metrics else None,
    }

    # Process each state key
    for state_key, value in state.items():
        if state_key not in STATE_KEY_TO_FIELD:
            fail("Unknown state key from librelane: '{}'. Add it to STATE_FIELD_MAPPING.".format(state_key))

        field = STATE_KEY_TO_FIELD[state_key]

        if value == None:
            result[field] = None
            continue

        if field in MULTI_FILE_FIELDS:
            # Multi-file: value is a dict
            if type(value) == "dict":
                file_dict = {}
                for corner, path in value.items():
                    file_dict[corner] = _resolve_path(path, declared_outputs, prev_info, field)
                result[field] = file_dict
            else:
                result[field] = None
        else:
            # Single file
            result[field] = _resolve_path(value, declared_outputs, prev_info, field)

    return result

def _resolve_path(path, declared_outputs, prev_info, field):
    """Resolve a path from state_out to a Bazel File.

    First checks if it matches a declared output (by basename).
    Then checks if it matches the previous value (unchanged).
    Fails if neither matches.
    """
    basename = path.rsplit("/", 1)[-1] if "/" in path else path

    # Check declared outputs first
    if basename in declared_outputs:
        return declared_outputs[basename]

    # Check if unchanged from previous state
    prev_value = getattr(prev_info, field, None) if prev_info else None
    if prev_value != None and prev_value.path == path:
        return prev_value

    # Also check if prev_value has same basename (path may differ between steps)
    if prev_value != None and prev_value.basename == basename:
        return prev_value

    fail("Cannot resolve path '{}' for field '{}'. Not in declared outputs or previous state.".format(path, field))

def get_pdk_files(pdk_info):
    """Get all files from a PdkInfo provider.

    Returns a list of File objects that should be inputs to the action.
    """
    files = []

    # Single files - core
    if pdk_info.fp_tracks_info:
        files.append(pdk_info.fp_tracks_info)
    if pdk_info.synth_excluded_cell_file:
        files.append(pdk_info.synth_excluded_cell_file)
    if pdk_info.pnr_excluded_cell_file:
        files.append(pdk_info.pnr_excluded_cell_file)

    # Single files - Magic
    if pdk_info.magicrc:
        files.append(pdk_info.magicrc)
    if pdk_info.magic_tech:
        files.append(pdk_info.magic_tech)
    if pdk_info.magic_pdk_setup:
        files.append(pdk_info.magic_pdk_setup)

    # Single files - KLayout
    if pdk_info.klayout_tech:
        files.append(pdk_info.klayout_tech)
    if pdk_info.klayout_properties:
        files.append(pdk_info.klayout_properties)
    if pdk_info.klayout_def_layer_map:
        files.append(pdk_info.klayout_def_layer_map)
    if pdk_info.klayout_drc_runset:
        files.append(pdk_info.klayout_drc_runset)

    # Single files - Netgen
    if pdk_info.netgen_setup:
        files.append(pdk_info.netgen_setup)

    # Single files - Synthesis maps
    if pdk_info.synth_latch_map:
        files.append(pdk_info.synth_latch_map)
    if pdk_info.synth_tristate_map:
        files.append(pdk_info.synth_tristate_map)
    if pdk_info.synth_csa_map:
        files.append(pdk_info.synth_csa_map)
    if pdk_info.synth_rca_map:
        files.append(pdk_info.synth_rca_map)
    if pdk_info.synth_fa_map:
        files.append(pdk_info.synth_fa_map)
    if pdk_info.synth_mux_map:
        files.append(pdk_info.synth_mux_map)
    if pdk_info.synth_mux4_map:
        files.append(pdk_info.synth_mux4_map)

    # List of files - core
    if pdk_info.cell_lefs:
        files.extend(pdk_info.cell_lefs)
    if pdk_info.cell_gds:
        files.extend(pdk_info.cell_gds)
    if pdk_info.cell_verilog_models:
        files.extend(pdk_info.cell_verilog_models)
    if pdk_info.cell_bb_verilog_models:
        files.extend(pdk_info.cell_bb_verilog_models)
    if pdk_info.cell_spice_models:
        files.extend(pdk_info.cell_spice_models)
    if pdk_info.gpio_pads_lef:
        files.extend(pdk_info.gpio_pads_lef)
    if pdk_info.gpio_pads_lef_core_side:
        files.extend(pdk_info.gpio_pads_lef_core_side)
    if pdk_info.gpio_pads_verilog:
        files.extend(pdk_info.gpio_pads_verilog)

    # List of files - Magic
    if pdk_info.cell_mags:
        files.extend(pdk_info.cell_mags)
    if pdk_info.cell_maglefs:
        files.extend(pdk_info.cell_maglefs)

    # Dict of corner -> File (tech_lefs)
    if pdk_info.tech_lefs:
        files.extend(pdk_info.tech_lefs.values())

    # Dict of corner -> File (rcx_rulesets)
    if pdk_info.rcx_rulesets:
        files.extend(pdk_info.rcx_rulesets.values())

    # Dict of corner -> list of Files (lib)
    if pdk_info.lib:
        for lib_files in pdk_info.lib.values():
            files.extend(lib_files)

    return files

def get_input_files(input_info, state_info):
    """Get all input files for a librelane step.

    Args:
        input_info: LibrelaneInput with flow configuration
        state_info: LibrelaneInfo with current design state (can be None for init)

    Returns a list of File objects that should be inputs to the action.
    """
    inputs = []

    # Add PDK files
    inputs.extend(get_pdk_files(input_info.pdk_info))

    # Add verilog files if present
    if input_info.verilog_files:
        inputs.extend(input_info.verilog_files.to_list())

    # Add custom SDC files if provided
    if input_info.pnr_sdc_file:
        inputs.append(input_info.pnr_sdc_file)
    if input_info.signoff_sdc_file:
        inputs.append(input_info.signoff_sdc_file)

    # Add Lighter DFF map if provided
    if input_info.lighter_dff_map:
        inputs.append(input_info.lighter_dff_map)

    # Add extra synthesis mapping file if provided
    if input_info.synth_extra_mapping_file:
        inputs.append(input_info.synth_extra_mapping_file)

    # Add custom PDN config if provided
    if input_info.fp_pdn_cfg:
        inputs.append(input_info.fp_pdn_cfg)

    # Add DEF template if provided
    if input_info.fp_def_template:
        inputs.append(input_info.fp_def_template)

    # Add pin order config if provided
    if input_info.fp_pin_order_cfg:
        inputs.append(input_info.fp_pin_order_cfg)

    # Add VSRC location files for IR drop analysis
    if input_info.vsrc_loc_files:
        inputs.extend(input_info.vsrc_loc_files.values())

    # Add macro files
    if input_info.macros:
        for macro in input_info.macros:
            if macro.lef:
                inputs.append(macro.lef)
            if macro.gds:
                inputs.append(macro.gds)
            if macro.netlist:
                inputs.append(macro.netlist)

    # Add state files if we have state from a previous step
    if state_info:
        # Add state_out from previous step (for metrics)
        if state_info.state_out:
            inputs.append(state_info.state_out)

        # Add single-file design views
        for field in STATE_FIELD_MAPPING.keys():
            if field in MULTI_FILE_FIELDS:
                continue
            value = getattr(state_info, field, None)
            if value != None:
                inputs.append(value)

        # Add multi-file design views (dicts)
        for field in MULTI_FILE_FIELDS:
            value = getattr(state_info, field, None)
            if value != None and type(value) == "dict":
                inputs.extend(value.values())

    return inputs


def get_verilog_paths(input_info, state_info):
    """Get verilog file paths - either synthesized netlist or input RTL."""
    if state_info and state_info.nl:
        return [state_info.nl.path]
    elif input_info.verilog_files:
        return [f.path for f in input_info.verilog_files.to_list()]
    else:
        return []

def get_macros_config(input_info):
    """Build MACROS config dict from MacroInfo list."""
    if not input_info.macros:
        return None

    macros_config = {}
    for macro in input_info.macros:
        macros_config[macro.name] = {
            "lef": [macro.lef.path] if macro.lef else [],
            "gds": [macro.gds.path] if macro.gds else [],
            "nl": [macro.netlist.path] if macro.netlist else [],
        }
    return macros_config

def librelane_output_path(filename, subdir = ""):
    """Get the path where librelane.steps writes a file (relative to design_dir).

    Args:
        filename: The filename to locate
        subdir: Subdirectory within runs/bazel/ where the file is written.
            Empty for most steps. CompositeSteps write to subdirectories
            (e.g., "1-diodeinsertion" for RepairAntennas).
    """
    if subdir:
        return "runs/bazel/" + subdir + "/" + filename
    return "runs/bazel/" + filename

def relative_path(file_path, base_dir):
    """Get the relative path of a file from a base directory."""
    if not file_path.startswith(base_dir + "/"):
        fail("File '{}' is not under base directory '{}'".format(file_path, base_dir))
    return file_path[len(base_dir) + 1:]

def run_librelane_step(
        ctx,
        step_id,
        outputs,
        config_content,
        inputs,
        input_info,
        state_info,
        output_subdir = ""):
    """Run a librelane step.

    Args:
        ctx: Rule context
        step_id: Librelane step ID (e.g., "Yosys.Synthesis")
        outputs: List of declared output Files (in target directory)
        config_content: JSON string for config
        inputs: List of input Files
        input_info: LibrelaneInput with flow configuration
        state_info: LibrelaneInfo from previous step (can be None for init)
        output_subdir: Subdirectory within runs/bazel/ where outputs are written.
            Empty for most steps, but CompositeSteps write to subdirectories
            (e.g., "1-diodeinsertion" for RepairAntennas).

    Returns:
        File - the state_out.json from this step
    """
    # Write config file in target-specific directory
    config_file = ctx.actions.declare_file(ctx.label.name + "/config.json")
    ctx.actions.write(output = config_file, content = config_content)

    # Design directory is the target-specific output directory
    design_dir = config_file.dirname

    # Generate state_in from state_info (has correct Bazel paths, no metrics yet)
    state_content = json.encode(serialize_state(state_info))
    state_in_base = ctx.actions.declare_file(ctx.label.name + "/state_in_base.json")
    ctx.actions.write(output = state_in_base, content = state_content)

    # Declare state_out as an output (we'll copy it from librelane)
    state_out = ctx.actions.declare_file(ctx.label.name + "/state_out.json")

    # Build copy commands to move files from librelane output to declared outputs
    copy_commands = []

    # Copy state_out.json (always at runs/bazel/state_out.json)
    copy_commands.append('cp "{design_dir}/{src}" "{dst}"'.format(
        design_dir = design_dir,
        src = librelane_output_path("state_out.json"),
        dst = state_out.path,
    ))

    # Copy each declared output from librelane's output location
    for output in outputs:
        rel_path = relative_path(output.path, design_dir)
        librelane_path = librelane_output_path(rel_path, output_subdir)
        copy_commands.append('mkdir -p "$(dirname "{dst}")" && cp "{design_dir}/{src}" "{dst}"'.format(
            design_dir = design_dir,
            src = librelane_path,
            dst = output.path,
        ))

    # Merge metrics from previous state_out into state_in at execution time
    if state_info and state_info.state_out:
        prev_state_out = state_info.state_out.path
        merge_metrics_cmd = 'jq -s \'.[0] * {{"metrics": .[1].metrics}}\' "{state_in_base}" "{prev_state_out}" > "{design_dir}/state_in.json"'.format(
            state_in_base = state_in_base.path,
            prev_state_out = prev_state_out,
            design_dir = design_dir,
        )
        state_in_path = design_dir + "/state_in.json"
    else:
        merge_metrics_cmd = ""
        state_in_path = state_in_base.path

    ctx.actions.run_shell(
        outputs = outputs + [state_out],
        inputs = inputs + [config_file, state_in_base],
        command = """
            set -e
            {merge_metrics_cmd}
            LOGFILE="$(pwd)/{design_dir}/librelane.log"
            HOME="$(pwd)/{design_dir}" librelane.steps run \\
                --manual-pdk \\
                --pdk-root "$PDK_ROOT" \\
                --pdk {pdk} \\
                --scl {scl} \\
                --id {step_id} \\
                -c {config_file} \\
                -i "{state_in}" \\
                -o "$(pwd)/{design_dir}/runs/bazel" 2>&1 | tee "$LOGFILE"
            # Check for unused config warnings (indicates config_keys mismatch)
            # Note: librelane wraps long lines, so we search for partial match
            if grep -q "provided is unused" "$LOGFILE"; then
                echo ""
                echo "ERROR: Config contains keys unused by step {step_id}:"
                grep "provided is unused" "$LOGFILE"
                echo ""
                echo "Fix: Remove unused keys from config_keys list for this step."
                exit 1
            fi
            {copy_commands}
        """.format(
            merge_metrics_cmd = merge_metrics_cmd,
            pdk = input_info.pdk_info.name,
            scl = input_info.pdk_info.scl,
            config_file = config_file.path,
            state_in = state_in_path,
            step_id = step_id,
            design_dir = design_dir,
            copy_commands = "\n            ".join(copy_commands),
        ),
        use_default_shell_env = True,
    )

    return state_out

def single_step_impl(ctx, step_id, config_keys, step_outputs, extra_config = {}, extra_inputs = [],
                     output_subdir = "", extra_outputs = []):
    """Run a librelane step with configurable outputs.

    Args:
        ctx: Rule context (must have 'src' and 'input' attributes)
        step_id: Librelane step ID
        config_keys: List of config keys this step uses. Must match librelane's
            config_vars for this step. Enables proper Bazel caching.
        step_outputs: List of outputs this step produces. Valid values:
            "def", "odb", "nl", "pnl", "sdc", "vh", "spef", "gds", "lef", etc.
            Use [] for checkers/reporters that don't produce outputs.
        extra_config: Additional config entries to merge (must be in config_keys)
        extra_inputs: Additional input files (e.g., config files)
        output_subdir: Subdirectory within runs/bazel/ where outputs are written.
            Empty for most steps. CompositeSteps write to subdirectories
            (e.g., "1-diodeinsertion" for RepairAntennas).
        extra_outputs: List of additional output file paths relative to step dir
            (e.g., ["summary.rpt", "nom/max.rpt"]). These are auxiliary outputs
            like reports that don't affect state.

    Returns:
        List of providers [DefaultInfo, LibrelaneInfo]
    """
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]
    top = input_info.top

    outputs = []

    # Declare outputs based on step_outputs list
    if "def" in step_outputs:
        def_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".def")
        outputs.append(def_out)
    else:
        def_out = getattr(state_info, "def", None)

    if "odb" in step_outputs:
        odb_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".odb")
        outputs.append(odb_out)
    else:
        odb_out = state_info.odb

    if "nl" in step_outputs:
        nl_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".nl.v")
        outputs.append(nl_out)
    else:
        nl_out = state_info.nl

    if "pnl" in step_outputs:
        pnl_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".pnl.v")
        outputs.append(pnl_out)
    else:
        pnl_out = state_info.pnl

    if "sdc" in step_outputs:
        sdc_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".sdc")
        outputs.append(sdc_out)
    else:
        sdc_out = state_info.sdc

    if "vh" in step_outputs:
        vh_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".vh")
        outputs.append(vh_out)
    else:
        vh_out = state_info.vh

    if "spef" in step_outputs:
        spef_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".spef")
        outputs.append(spef_out)
    else:
        spef_out = state_info.spef

    if "gds" in step_outputs:
        gds_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".gds")
        outputs.append(gds_out)
    else:
        gds_out = state_info.gds

    if "klayout_gds" in step_outputs:
        klayout_gds_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".klayout.gds")
        outputs.append(klayout_gds_out)
    else:
        klayout_gds_out = state_info.klayout_gds

    if "lef" in step_outputs:
        lef_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".lef")
        outputs.append(lef_out)
    else:
        lef_out = state_info.lef

    if "spice" in step_outputs:
        spice_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".spice")
        outputs.append(spice_out)
    else:
        spice_out = state_info.spice

    # Declare extra outputs (reports, etc.)
    extra_output_files = []
    for path in extra_outputs:
        extra_output_files.append(ctx.actions.declare_file(ctx.label.name + "/" + path))
    outputs.extend(extra_output_files)

    # Get input files
    inputs = get_input_files(input_info, state_info) + extra_inputs

    # Create config (filtered to only keys this step uses)
    config = create_librelane_config(input_info, state_info, config_keys)
    config.update(extra_config)

    # Run step
    state_out = run_librelane_step(
        ctx = ctx,
        step_id = step_id,
        outputs = outputs,
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
        output_subdir = output_subdir,
    )

    # Build new LibrelaneInfo (state only - config stays in LibrelaneInput)
    # Include extra outputs in DefaultInfo but not in LibrelaneInfo (they're auxiliary)
    default_files = outputs + [state_out] if outputs else [state_out]
    return [
        DefaultInfo(files = depset(default_files)),
        LibrelaneInfo(
            state_out = state_out,
            nl = nl_out,
            pnl = pnl_out,
            odb = odb_out,
            sdc = sdc_out,
            sdf = state_info.sdf,
            spef = spef_out,
            lib = state_info.lib,
            gds = gds_out,
            mag_gds = state_info.mag_gds,
            klayout_gds = klayout_gds_out,
            lef = lef_out,
            mag = state_info.mag,
            spice = spice_out,
            json_h = state_info.json_h,
            vh = vh_out,
            **{"def": def_out}
        ),
    ]

# Common attributes for rules that take a previous step as input
FLOW_ATTRS = {
    "src": attr.label(
        doc = "Previous flow step providing LibrelaneInfo (state)",
        mandatory = True,
        providers = [LibrelaneInfo],
    ),
    "input": attr.label(
        doc = "Init step providing LibrelaneInput (config)",
        mandatory = True,
        providers = [LibrelaneInput],
    ),
}

# Attributes for entry-point rules (init)
ENTRY_ATTRS = {
    "verilog_files": attr.label_list(
        doc = "Verilog/SystemVerilog source files",
        allow_files = [".v", ".sv"],
        mandatory = True,
    ),
    "top": attr.string(
        doc = "Top module name",
        mandatory = True,
    ),
    "clock_period": attr.string(
        doc = "Clock period in nanoseconds",
        default = "10.0",
    ),
    "clock_port": attr.string(
        doc = "Clock port name",
        default = "clock",
    ),
    "pdk": attr.label(
        doc = "PDK target providing PdkInfo",
        mandatory = True,
        providers = [PdkInfo],
    ),
    "macros": attr.label_list(
        doc = "Hard macro targets providing MacroInfo",
        default = [],
        providers = [MacroInfo],
    ),
    "pnr_sdc_file": attr.label(
        doc = "Custom SDC file for PnR timing constraints (optional)",
        allow_single_file = [".sdc"],
    ),
    "signoff_sdc_file": attr.label(
        doc = "Custom SDC file for signoff STA (optional)",
        allow_single_file = [".sdc"],
    ),
    "verilog_include_dirs": attr.string_list(
        doc = "Verilog include directories for `include directives",
        default = [],
    ),
    "verilog_defines": attr.string_list(
        doc = "Verilog preprocessor defines (e.g., 'FOO' or 'FOO=bar')",
        default = [],
    ),
    # Verilator.Lint config (from librelane/steps/verilator.py lines 39-87)
    "verilog_power_define": attr.string(
        doc = "Power guard define name for Verilog preprocessing",
        default = "USE_POWER_PINS",
    ),
    "linter_include_pdk_models": attr.bool(
        doc = "Include PDK Verilog models in linting",
        default = False,
    ),
    "linter_relative_includes": attr.bool(
        doc = "Resolve includes relative to referencing file",
        default = True,
    ),
    "linter_error_on_latch": attr.bool(
        doc = "Error on inferred latches not marked always_latch",
        default = True,
    ),
    "linter_defines": attr.string_list(
        doc = "Linter-specific preprocessor defines (overrides verilog_defines for lint)",
        default = [],
    ),
    "extra_verilog_models": attr.label_list(
        doc = "Extra Verilog models for linting and synthesis",
        allow_files = [".v", ".sv"],
        default = [],
    ),
    # Checker.LintTimingConstructs config (checker.py line 385-391)
    "error_on_linter_timing_constructs": attr.bool(
        doc = "Quit immediately on timing constructs in RTL",
        default = True,
    ),
    # Checker.LintErrors config (checker.py line 345-351)
    "error_on_linter_errors": attr.bool(
        doc = "Quit immediately on linter errors",
        default = True,
    ),
    # Checker.LintWarnings config (checker.py line 365-371)
    "error_on_linter_warnings": attr.bool(
        doc = "Raise an error on linter warnings",
        default = False,
    ),
    # Yosys config (from librelane/steps/pyosys.py verilog_rtl_cfg_vars + PyosysStep.config_vars)
    "synth_parameters": attr.string_list(
        doc = "Key-value pairs to be chparam'd in Yosys (format: key1=value1)",
        default = [],
    ),
    "use_synlig": attr.bool(
        doc = "Use Synlig plugin for better SystemVerilog parsing",
        default = False,
    ),
    "synlig_defer": attr.bool(
        doc = "Use -defer flag with Synlig (experimental)",
        default = False,
    ),
    "use_lighter": attr.bool(
        doc = "Use Lighter plugin to optimize clock-gated flip-flops",
        default = False,
    ),
    "lighter_dff_map": attr.label(
        doc = "Custom DFF map file for Lighter plugin",
        allow_single_file = True,
    ),
    "yosys_log_level": attr.string(
        doc = "Yosys log level: ALL, WARNING, or ERROR",
        default = "ALL",
        values = ["ALL", "WARNING", "ERROR"],
    ),
    # Yosys.Synthesis config (from librelane/steps/pyosys.py SynthesisCommon.config_vars)
    "synth_checks_allow_tristate": attr.bool(
        doc = "Ignore multiple-driver warnings for tri-state buffers",
        default = True,
    ),
    "synth_autoname": attr.bool(
        doc = "Generate human-readable names for netlist instances",
        default = False,
    ),
    "synth_strategy": attr.string(
        doc = "ABC synthesis strategy: AREA 0-3 or DELAY 0-4",
        default = "AREA 0",
        values = ["AREA 0", "AREA 1", "AREA 2", "AREA 3",
                  "DELAY 0", "DELAY 1", "DELAY 2", "DELAY 3", "DELAY 4"],
    ),
    "synth_abc_buffering": attr.bool(
        doc = "Enable ABC cell buffering",
        default = False,
    ),
    "synth_abc_legacy_refactor": attr.bool(
        doc = "Use legacy ABC refactor command (less stable)",
        default = False,
    ),
    "synth_abc_legacy_rewrite": attr.bool(
        doc = "Use legacy ABC rewrite command (less stable)",
        default = False,
    ),
    "synth_abc_dff": attr.bool(
        doc = "Pass D-flipflops through ABC for optimization",
        default = False,
    ),
    "synth_abc_use_mfs3": attr.bool(
        doc = "Experimental: SAT-based remapping before retime",
        default = False,
    ),
    "synth_abc_area_use_nf": attr.bool(
        doc = "Experimental: use &nf mapper instead of amap for area",
        default = False,
    ),
    "synth_direct_wire_buffering": attr.bool(
        doc = "Insert buffer cells for directly connected wires",
        default = True,
    ),
    "synth_splitnets": attr.bool(
        doc = "Split multi-bit nets into single-bit nets",
        default = True,
    ),
    "synth_sizing": attr.bool(
        doc = "Enable ABC cell sizing instead of buffering",
        default = False,
    ),
    "synth_hierarchy_mode": attr.string(
        doc = "Hierarchy handling: flatten, deferred_flatten, or keep",
        default = "flatten",
        values = ["flatten", "deferred_flatten", "keep"],
    ),
    "synth_share_resources": attr.bool(
        doc = "Merge shareable resources to reduce cell count",
        default = True,
    ),
    "synth_adder_type": attr.string(
        doc = "Adder mapping: YOSYS, FA, RCA, or CSA",
        default = "YOSYS",
        values = ["YOSYS", "FA", "RCA", "CSA"],
    ),
    "synth_extra_mapping_file": attr.label(
        doc = "Extra techmap file for Yosys",
        allow_single_file = True,
    ),
    "synth_elaborate_only": attr.bool(
        doc = "Elaborate design without logic mapping",
        default = False,
    ),
    "synth_elaborate_flatten": attr.bool(
        doc = "Flatten top level during elaborate-only mode",
        default = True,
    ),
    "synth_mul_booth": attr.bool(
        doc = "Use Booth encoding for multipliers",
        default = False,
    ),
    "synth_tie_undefined": attr.string(
        doc = "Tie undefined values: high, low, or empty for undriven",
        default = "low",
        values = ["high", "low", ""],
    ),
    "synth_write_noattr": attr.bool(
        doc = "Omit Verilog-2001 attributes from output netlists",
        default = True,
    ),
    # Post-synthesis checker config (from librelane/steps/checker.py)
    "error_on_unmapped_cells": attr.bool(
        doc = "Error on unmapped cells after synthesis",
        default = True,
    ),
    "error_on_synth_checks": attr.bool(
        doc = "Error on synthesis check failures (combinational loops, no drivers)",
        default = True,
    ),
    "error_on_nl_assign_statements": attr.bool(
        doc = "Error on assign statements in netlist",
        default = True,
    ),
    "error_on_pdn_violations": attr.bool(
        doc = "Error on power grid violations (unconnected nodes)",
        default = True,
    ),
    "error_on_tr_drc": attr.bool(
        doc = "Error on routing DRC violations (Step 49)",
        default = True,
    ),
    "error_on_disconnected_pins": attr.bool(
        doc = "Error on critical disconnected pins (Step 51)",
        default = True,
    ),
    "error_on_long_wire": attr.bool(
        doc = "Error on wires exceeding threshold (Step 53)",
        default = True,
    ),
    # OpenROADStep config (from librelane/steps/openroad.py lines 192-223)
    "pdn_connect_macros_to_grid": attr.bool(
        doc = "Enable connection of macros to top level power grid",
        default = True,
    ),
    "pdn_macro_connections": attr.string_list(
        doc = "Explicit macro power connections: instance_rx vdd_net gnd_net vdd_pin gnd_pin",
        default = [],
    ),
    "pdn_enable_global_connections": attr.bool(
        doc = "Enable creation of global connections in PDN generation",
        default = True,
    ),
    "fp_def_template": attr.label(
        doc = "DEF file to use as floorplan template",
        allow_single_file = [".def"],
    ),
    "fp_pin_order_cfg": attr.label(
        doc = "Pin order configuration file for custom IO placement",
        allow_single_file = True,
    ),
    # ApplyDEFTemplate config (odb.py lines 249-259)
    "fp_template_match_mode": attr.string(
        doc = "DEF template pin matching: strict or permissive",
        default = "strict",
        values = ["strict", "permissive"],
    ),
    "fp_template_copy_power_pins": attr.bool(
        doc = "Always copy power pins from DEF template",
        default = False,
    ),
    # OpenROADStep.prepare_env() config (from librelane/steps/openroad.py lines 242-258)
    "extra_excluded_cells": attr.string_list(
        doc = "Additional cell wildcards to exclude from synthesis and PnR",
        default = [],
    ),
    # MultiCornerSTA config (from librelane/steps/openroad.py lines 534-556)
    "sta_macro_prioritize_nl": attr.bool(
        doc = "Prioritize netlists+SPEF over LIB for macro timing",
        default = True,
    ),
    "sta_max_violator_count": attr.int(
        doc = "Max violators to list in violator_list.rpt (0 = unlimited)",
        default = 0,
    ),
    "sta_threads": attr.int(
        doc = "Max STA corners to run in parallel (0 = auto)",
        default = 0,
    ),
    # OpenROAD.IRDropReport config (openroad.py:1813-1819)
    "vsrc_loc_files": attr.label_keyed_string_dict(
        doc = "Map of PSM location files to power/ground net names for IR drop analysis",
        allow_files = True,
    ),
    # OpenROAD.RCX config (openroad.py:1679-1702)
    "rcx_merge_via_wire_res": attr.bool(
        doc = "Merge via and wire resistances in RCX",
        default = True,
    ),
    "rcx_sdc_file": attr.label(
        doc = "SDC file for RCX-based STA (optional, different from implementation SDC)",
        allow_single_file = True,
    ),
    # OpenROAD.CutRows config (from librelane/steps/openroad.py lines 1916-1933)
    "fp_macro_horizontal_halo": attr.string(
        doc = "Horizontal halo size around macros while cutting rows (µm)",
        default = "10",
    ),
    "fp_macro_vertical_halo": attr.string(
        doc = "Vertical halo size around macros while cutting rows (µm)",
        default = "10",
    ),
    # Odb.AddPDNObstructions / Odb.RemovePDNObstructions
    "pdn_obstructions": attr.string_list(
        doc = "PDN obstructions. Format: layer llx lly urx ury (µm)",
        default = [],
    ),
    # OpenROAD.GeneratePDN (pdn_variables from common_variables.py)
    "fp_pdn_skiptrim": attr.bool(
        doc = "Skip metal trim step during pdngen",
        default = False,
    ),
    "fp_pdn_core_ring": attr.bool(
        doc = "Enable adding a core ring around the design",
        default = False,
    ),
    "fp_pdn_enable_rails": attr.bool(
        doc = "Enable creation of rails in the power grid",
        default = True,
    ),
    "fp_pdn_horizontal_halo": attr.string(
        doc = "Horizontal halo around macros during PDN insertion (µm)",
        default = "10",
    ),
    "fp_pdn_vertical_halo": attr.string(
        doc = "Vertical halo around macros during PDN insertion (µm)",
        default = "10",
    ),
    "fp_pdn_multilayer": attr.bool(
        doc = "Use multiple layers in power grid (False for macro hardening)",
        default = True,
    ),
    "fp_pdn_cfg": attr.label(
        doc = "Custom PDN configuration file",
        allow_single_file = True,
    ),
    # Odb.AddRoutingObstructions / Odb.RemoveRoutingObstructions
    "routing_obstructions": attr.string_list(
        doc = "Routing obstructions. Format: layer llx lly urx ury (µm)",
        default = [],
    ),
    # io_layer_variables (common_variables.py lines 19-46) - used by IOPlacement, CustomIOPlacement
    "fp_io_vextend": attr.string(
        doc = "Extend vertical IO pins outside die (µm)",
        default = "0",
    ),
    "fp_io_hextend": attr.string(
        doc = "Extend horizontal IO pins outside die (µm)",
        default = "0",
    ),
    "fp_io_vthickness_mult": attr.string(
        doc = "Vertical pin thickness multiplier (base is layer min width)",
        default = "2",
    ),
    "fp_io_hthickness_mult": attr.string(
        doc = "Horizontal pin thickness multiplier (base is layer min width)",
        default = "2",
    ),
    # CustomIOPlacement config (odb.py lines 673-680)
    "errors_on_unmatched_io": attr.string(
        doc = "Error on unmatched IO pins: none, unmatched_design, unmatched_cfg, or both",
        default = "unmatched_design",
        values = ["none", "unmatched_design", "unmatched_cfg", "both"],
    ),
    # GlobalPlacement config (routing_layer_variables + _GlobalPlacement + GlobalPlacementSkipIO)
    "pl_target_density_pct": attr.string(
        doc = "Target placement density percentage (if empty, calculated dynamically)",
        default = "",
    ),
    "fp_ppl_mode": attr.string(
        doc = "IO placement mode: matching, random_equidistant, or annealing",
        default = "matching",
    ),
    "pl_skip_initial_placement": attr.bool(
        doc = "Skip initial placement in global placer",
        default = False,
    ),
    "pl_wire_length_coef": attr.string(
        doc = "Global placement initial wirelength coefficient",
        default = "0.25",
    ),
    "pl_min_phi_coefficient": attr.string(
        doc = "Lower bound on µ_k variable in GPL algorithm",
        default = "",
    ),
    "pl_max_phi_coefficient": attr.string(
        doc = "Upper bound on µ_k variable in GPL algorithm",
        default = "",
    ),
    "pl_time_driven": attr.bool(
        doc = "Use time driven placement in global placer",
        default = True,
    ),
    "pl_routability_driven": attr.bool(
        doc = "Use routability driven placement in global placer",
        default = True,
    ),
    "pl_routability_overflow_threshold": attr.string(
        doc = "Overflow threshold for routability mode",
        default = "",
    ),
    "fp_core_util": attr.string(
        doc = "Core utilization percentage (used if PL_TARGET_DENSITY_PCT not set)",
        default = "50",
    ),
    "rt_clock_min_layer": attr.string(
        doc = "Lowest layer for clock net routing",
        default = "",
    ),
    "rt_clock_max_layer": attr.string(
        doc = "Highest layer for clock net routing",
        default = "",
    ),
    "grt_adjustment": attr.string(
        doc = "Global routing capacity reduction (0-1)",
        default = "0.3",
    ),
    "grt_macro_extension": attr.int(
        doc = "GCells added to macro blockage boundaries",
        default = 0,
    ),
    # grt_variables (common_variables.py:285-319) - used by ResizerStep subclasses
    "diode_padding": attr.int(
        doc = "Diode cell padding in sites (increases width during placement checks)",
        default = 0,
    ),
    "grt_allow_congestion": attr.bool(
        doc = "Allow congestion during global routing",
        default = False,
    ),
    "grt_antenna_iters": attr.int(
        doc = "Maximum iterations for global antenna repairs",
        default = 3,
    ),
    "grt_overflow_iters": attr.int(
        doc = "Maximum iterations waiting for overflow to reach desired value",
        default = 50,
    ),
    "grt_antenna_margin": attr.int(
        doc = "Margin percentage to over-fix antenna violations",
        default = 10,
    ),
    # dpl_variables (common_variables.py:255-283) - used by ResizerStep subclasses
    "pl_optimize_mirroring": attr.bool(
        doc = "Run optimize_mirroring pass during detailed placement",
        default = True,
    ),
    "pl_max_displacement_x": attr.string(
        doc = "Max X displacement when finding placement site (µm)",
        default = "500",
    ),
    "pl_max_displacement_y": attr.string(
        doc = "Max Y displacement when finding placement site (µm)",
        default = "100",
    ),
    # rsz_variables (common_variables.py:321-340) - used by ResizerStep subclasses
    "rsz_dont_touch_rx": attr.string(
        doc = "Regex for nets/instances marked don't touch by resizer",
        default = "$^",
    ),
    "rsz_dont_touch_list": attr.string_list(
        doc = "List of nets/instances marked don't touch by resizer",
        default = [],
    ),
    "rsz_corners": attr.string_list(
        doc = "IPVT corners for resizer (empty = use STA_CORNERS)",
        default = [],
    ),
    # RepairDesignPostGPL config_vars (openroad.py:2119-2178)
    "design_repair_buffer_input_ports": attr.bool(
        doc = "Insert buffers on input ports during design repair",
        default = True,
    ),
    "design_repair_buffer_output_ports": attr.bool(
        doc = "Insert buffers on output ports during design repair",
        default = True,
    ),
    "design_repair_tie_fanout": attr.bool(
        doc = "Repair tie cells fanout during design repair",
        default = True,
    ),
    "design_repair_tie_separation": attr.bool(
        doc = "Allow tie separation during design repair",
        default = False,
    ),
    "design_repair_max_wire_length": attr.string(
        doc = "Max wire length for buffer insertion during design repair (µm, 0=disabled)",
        default = "0",
    ),
    "design_repair_max_slew_pct": attr.string(
        doc = "Slew margin percentage during design repair",
        default = "20",
    ),
    "design_repair_max_cap_pct": attr.string(
        doc = "Capacitance margin percentage during design repair",
        default = "20",
    ),
    "design_repair_remove_buffers": attr.bool(
        doc = "Remove synthesis buffers to give resizer more flexibility",
        default = False,
    ),
    # Odb.ManualGlobalPlacement config (odb.py:987-993)
    "manual_global_placements": attr.string(
        doc = "JSON dict of instance name to placement {x, y, orientation}",
        default = "",
    ),
    # OpenROAD.CTS config_vars (openroad.py:2016-2084)
    "cts_sink_clustering_size": attr.int(
        doc = "Max sinks per cluster in CTS",
        default = 25,
    ),
    "cts_sink_clustering_max_diameter": attr.string(
        doc = "Max cluster diameter in µm",
        default = "50",
    ),
    "cts_clk_max_wire_length": attr.string(
        doc = "Max clock wire length in µm (0 = no limit)",
        default = "0",
    ),
    "cts_disable_post_processing": attr.bool(
        doc = "Disable post-CTS processing for outlier sinks",
        default = False,
    ),
    "cts_distance_between_buffers": attr.string(
        doc = "Distance between buffers in µm (0 = auto)",
        default = "0",
    ),
    "cts_corners": attr.string_list(
        doc = "IPVT corners for CTS (empty = use STA_CORNERS)",
        default = [],
    ),
    "cts_max_cap": attr.string(
        doc = "Max capacitance for CTS characterization in pF (empty = from lib)",
        default = "",
    ),
    "cts_max_slew": attr.string(
        doc = "Max slew for CTS characterization in ns (empty = from lib)",
        default = "",
    ),
    # ResizerTimingPostCTS/PostGRT config_vars (openroad.py:2254-2302)
    "pl_resizer_hold_slack_margin": attr.string(
        doc = "Hold slack margin in ns for resizer timing optimization",
        default = "0.1",
    ),
    "pl_resizer_setup_slack_margin": attr.string(
        doc = "Setup slack margin in ns for resizer timing optimization",
        default = "0.05",
    ),
    "pl_resizer_hold_max_buffer_pct": attr.string(
        doc = "Max hold buffers as percentage of instances",
        default = "50",
    ),
    "pl_resizer_setup_max_buffer_pct": attr.string(
        doc = "Max setup buffers as percentage of instances",
        default = "50",
    ),
    "pl_resizer_allow_setup_vios": attr.bool(
        doc = "Allow setup violations when fixing hold violations",
        default = False,
    ),
    "pl_resizer_gate_cloning": attr.bool(
        doc = "Enable gate cloning when fixing setup violations",
        default = True,
    ),
    "pl_resizer_fix_hold_first": attr.bool(
        doc = "Fix hold violations before setup (experimental)",
        default = False,
    ),
    # RepairDesignPostGRT config_vars (openroad.py:2203-2234)
    "grt_design_repair_run_grt": attr.bool(
        doc = "Run GRT before and after resizer during post-GRT repair",
        default = True,
    ),
    "grt_design_repair_max_wire_length": attr.string(
        doc = "Max wire length for buffer insertion during post-GRT repair (0 = no buffers)",
        default = "0",
    ),
    "grt_design_repair_max_slew_pct": attr.string(
        doc = "Slew margin percentage during post-GRT design repair",
        default = "10",
    ),
    "grt_design_repair_max_cap_pct": attr.string(
        doc = "Capacitance margin percentage during post-GRT design repair",
        default = "10",
    ),
    # ResizerTimingPostGRT config_vars (openroad.py:2323-2381)
    "grt_resizer_hold_slack_margin": attr.string(
        doc = "Time margin for hold slack when fixing violations (ns)",
        default = "0.05",
    ),
    "grt_resizer_setup_slack_margin": attr.string(
        doc = "Time margin for setup slack when fixing violations (ns)",
        default = "0.025",
    ),
    "grt_resizer_hold_max_buffer_pct": attr.string(
        doc = "Max buffers to insert for hold fixes (% of instances)",
        default = "50",
    ),
    "grt_resizer_setup_max_buffer_pct": attr.string(
        doc = "Max buffers to insert for setup fixes (% of instances)",
        default = "50",
    ),
    "grt_resizer_allow_setup_vios": attr.bool(
        doc = "Allow setup violations when fixing hold",
        default = False,
    ),
    "grt_resizer_gate_cloning": attr.bool(
        doc = "Enable gate cloning when fixing setup violations",
        default = True,
    ),
    "grt_resizer_run_grt": attr.bool(
        doc = "Run global routing after resizer steps",
        default = True,
    ),
    "grt_resizer_fix_hold_first": attr.bool(
        doc = "Experimental: fix hold before setup violations",
        default = False,
    ),
    # Odb.DiodesOnPorts config_vars (odb.py:738-744)
    "diode_on_ports": attr.string(
        doc = "Insert diodes on ports: none, in, out, or both",
        default = "none",
        values = ["none", "in", "out", "both"],
    ),
    # DetailedRouting config_vars (openroad.py:1593-1616)
    "drt_threads": attr.int(
        doc = "Number of threads for detailed routing (0 = machine thread count)",
        default = 0,
    ),
    "drt_min_layer": attr.string(
        doc = "Override lowest layer for detailed routing",
        default = "",
    ),
    "drt_max_layer": attr.string(
        doc = "Override highest layer for detailed routing",
        default = "",
    ),
    "drt_opt_iters": attr.int(
        doc = "Max optimization iterations in TritonRoute",
        default = 64,
    ),
    # MagicStep config (magic.py:76-142)
    "magic_def_labels": attr.bool(
        doc = "Read labels with DEF files in Magic",
        default = True,
    ),
    "magic_gds_polygon_subcells": attr.bool(
        doc = "Put non-Manhattan polygons in subcells for faster Magic",
        default = False,
    ),
    "magic_def_no_blockages": attr.bool(
        doc = "Ignore blockages in DEF files",
        default = True,
    ),
    "magic_include_gds_pointers": attr.bool(
        doc = "Include GDS pointers in generated mag files",
        default = False,
    ),
    "magic_capture_errors": attr.bool(
        doc = "Capture and quit on Magic fatal errors",
        default = True,
    ),
    # Magic.StreamOut config (magic.py:264-293)
    "magic_zeroize_origin": attr.bool(
        doc = "Move layout origin to 0,0 in LEF",
        default = False,
    ),
    "magic_disable_cif_info": attr.bool(
        doc = "Disable CIF hierarchy info in GDSII",
        default = True,
    ),
    "magic_macro_std_cell_source": attr.string(
        doc = "Source for macro std cells: PDK or macro",
        default = "macro",
        values = ["PDK", "macro"],
    ),
}

