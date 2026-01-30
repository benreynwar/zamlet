# Init rule - entry point for the flow

load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo", "MacroInfo", "PdkInfo")
load("//bazel/flow/config:core.bzl", "CORE_ATTRS")
load("//bazel/flow/config:synth.bzl", "SynthConfig", "SYNTH_DEFAULTS")
load("//bazel/flow/config:pnr.bzl", "PnRConfig", "PNR_DEFAULTS")
load("//bazel/flow/config:signoff.bzl", "SignoffConfig", "SIGNOFF_DEFAULTS")


def _get_synth_val(ctx, synth_config, name):
    """Get synthesis config value from config rule or default."""
    if synth_config:
        return getattr(synth_config, name)
    return SYNTH_DEFAULTS[name]


def _get_pnr_val(ctx, pnr_config, name):
    """Get PnR config value from config rule or default."""
    if pnr_config:
        return getattr(pnr_config, name)
    return PNR_DEFAULTS[name]


def _get_signoff_val(ctx, signoff_config, name):
    """Get signoff config value from config rule or default."""
    if signoff_config:
        return getattr(signoff_config, name)
    return SIGNOFF_DEFAULTS[name]


def _init_impl(ctx):
    """Package verilog files and config into LibrelaneInput and LibrelaneInfo."""
    pdk_info = ctx.attr.pdk[PdkInfo]

    # Get optional config providers
    synth_config = ctx.attr.synth_config[SynthConfig] if ctx.attr.synth_config else None
    pnr_config = ctx.attr.pnr_config[PnRConfig] if ctx.attr.pnr_config else None
    signoff_config = ctx.attr.signoff_config[SignoffConfig] if ctx.attr.signoff_config else None

    # Collect macros if provided
    macros = []
    if ctx.attr.macros:
        for macro_target in ctx.attr.macros:
            macros.append(macro_target[MacroInfo])

    # Get optional SDC files
    pnr_sdc = ctx.file.pnr_sdc_file if ctx.attr.pnr_sdc_file else None
    signoff_sdc = ctx.file.signoff_sdc_file if ctx.attr.signoff_sdc_file else None

    return [
        DefaultInfo(files = depset(ctx.files.verilog_files)),
        # LibrelaneInput - configuration that doesn't change
        LibrelaneInput(
            # Core config (from CORE_ATTRS)
            top = ctx.attr.top,
            clock_port = ctx.attr.clock_port,
            clock_period = ctx.attr.clock_period,
            pdk_info = pdk_info,
            verilog_files = depset(ctx.files.verilog_files),
            macros = macros,
            pnr_sdc_file = pnr_sdc,
            signoff_sdc_file = signoff_sdc,
            verilog_include_dirs = ctx.attr.verilog_include_dirs,
            verilog_defines = ctx.attr.verilog_defines,

            # Synth config
            verilog_power_define = _get_synth_val(ctx, synth_config, "verilog_power_define"),
            linter_include_pdk_models = _get_synth_val(ctx, synth_config, "linter_include_pdk_models"),
            linter_relative_includes = _get_synth_val(ctx, synth_config, "linter_relative_includes"),
            linter_error_on_latch = _get_synth_val(ctx, synth_config, "linter_error_on_latch"),
            linter_defines = _get_synth_val(ctx, synth_config, "linter_defines"),
            extra_verilog_models = _get_synth_val(ctx, synth_config, "extra_verilog_models"),
            synth_parameters = _get_synth_val(ctx, synth_config, "synth_parameters"),
            use_synlig = _get_synth_val(ctx, synth_config, "use_synlig"),
            synlig_defer = _get_synth_val(ctx, synth_config, "synlig_defer"),
            use_lighter = _get_synth_val(ctx, synth_config, "use_lighter"),
            lighter_dff_map = _get_synth_val(ctx, synth_config, "lighter_dff_map"),
            yosys_log_level = _get_synth_val(ctx, synth_config, "yosys_log_level"),
            synth_checks_allow_tristate = _get_synth_val(ctx, synth_config, "synth_checks_allow_tristate"),
            synth_autoname = _get_synth_val(ctx, synth_config, "synth_autoname"),
            synth_strategy = _get_synth_val(ctx, synth_config, "synth_strategy"),
            synth_abc_buffering = _get_synth_val(ctx, synth_config, "synth_abc_buffering"),
            synth_abc_legacy_refactor = _get_synth_val(ctx, synth_config, "synth_abc_legacy_refactor"),
            synth_abc_legacy_rewrite = _get_synth_val(ctx, synth_config, "synth_abc_legacy_rewrite"),
            synth_abc_dff = _get_synth_val(ctx, synth_config, "synth_abc_dff"),
            synth_abc_use_mfs3 = _get_synth_val(ctx, synth_config, "synth_abc_use_mfs3"),
            synth_abc_area_use_nf = _get_synth_val(ctx, synth_config, "synth_abc_area_use_nf"),
            synth_direct_wire_buffering = _get_synth_val(ctx, synth_config, "synth_direct_wire_buffering"),
            synth_splitnets = _get_synth_val(ctx, synth_config, "synth_splitnets"),
            synth_sizing = _get_synth_val(ctx, synth_config, "synth_sizing"),
            synth_hierarchy_mode = _get_synth_val(ctx, synth_config, "synth_hierarchy_mode"),
            synth_share_resources = _get_synth_val(ctx, synth_config, "synth_share_resources"),
            synth_adder_type = _get_synth_val(ctx, synth_config, "synth_adder_type"),
            synth_extra_mapping_file = _get_synth_val(ctx, synth_config, "synth_extra_mapping_file"),
            synth_elaborate_only = _get_synth_val(ctx, synth_config, "synth_elaborate_only"),
            synth_elaborate_flatten = _get_synth_val(ctx, synth_config, "synth_elaborate_flatten"),
            synth_mul_booth = _get_synth_val(ctx, synth_config, "synth_mul_booth"),
            synth_tie_undefined = _get_synth_val(ctx, synth_config, "synth_tie_undefined"),
            synth_write_noattr = _get_synth_val(ctx, synth_config, "synth_write_noattr"),
            run_eqy = _get_synth_val(ctx, synth_config, "run_eqy"),
            eqy_script = _get_synth_val(ctx, synth_config, "eqy_script"),
            eqy_force_accept_pdk = _get_synth_val(ctx, synth_config, "eqy_force_accept_pdk"),

            # PnR config
            fp_def_template = _get_pnr_val(ctx, pnr_config, "fp_def_template"),
            fp_pin_order_cfg = _get_pnr_val(ctx, pnr_config, "fp_pin_order_cfg"),
            fp_template_match_mode = _get_pnr_val(ctx, pnr_config, "fp_template_match_mode"),
            fp_template_copy_power_pins = _get_pnr_val(ctx, pnr_config, "fp_template_copy_power_pins"),
            fp_core_util = _get_pnr_val(ctx, pnr_config, "fp_core_util"),
            fp_macro_horizontal_halo = _get_pnr_val(ctx, pnr_config, "fp_macro_horizontal_halo"),
            fp_macro_vertical_halo = _get_pnr_val(ctx, pnr_config, "fp_macro_vertical_halo"),
            fp_io_vextend = _get_pnr_val(ctx, pnr_config, "fp_io_vextend"),
            fp_io_hextend = _get_pnr_val(ctx, pnr_config, "fp_io_hextend"),
            fp_io_vthickness_mult = _get_pnr_val(ctx, pnr_config, "fp_io_vthickness_mult"),
            fp_io_hthickness_mult = _get_pnr_val(ctx, pnr_config, "fp_io_hthickness_mult"),
            fp_ppl_mode = _get_pnr_val(ctx, pnr_config, "fp_ppl_mode"),
            errors_on_unmatched_io = _get_pnr_val(ctx, pnr_config, "errors_on_unmatched_io"),
            fp_pdn_skiptrim = _get_pnr_val(ctx, pnr_config, "fp_pdn_skiptrim"),
            fp_pdn_core_ring = _get_pnr_val(ctx, pnr_config, "fp_pdn_core_ring"),
            fp_pdn_enable_rails = _get_pnr_val(ctx, pnr_config, "fp_pdn_enable_rails"),
            fp_pdn_horizontal_halo = _get_pnr_val(ctx, pnr_config, "fp_pdn_horizontal_halo"),
            fp_pdn_vertical_halo = _get_pnr_val(ctx, pnr_config, "fp_pdn_vertical_halo"),
            fp_pdn_multilayer = _get_pnr_val(ctx, pnr_config, "fp_pdn_multilayer"),
            fp_pdn_cfg = _get_pnr_val(ctx, pnr_config, "fp_pdn_cfg"),
            pdn_connect_macros_to_grid = _get_pnr_val(ctx, pnr_config, "pdn_connect_macros_to_grid"),
            pdn_macro_connections = _get_pnr_val(ctx, pnr_config, "pdn_macro_connections"),
            pdn_enable_global_connections = _get_pnr_val(ctx, pnr_config, "pdn_enable_global_connections"),
            pdn_obstructions = _get_pnr_val(ctx, pnr_config, "pdn_obstructions"),
            routing_obstructions = _get_pnr_val(ctx, pnr_config, "routing_obstructions"),
            pl_target_density_pct = _get_pnr_val(ctx, pnr_config, "pl_target_density_pct"),
            pl_skip_initial_placement = _get_pnr_val(ctx, pnr_config, "pl_skip_initial_placement"),
            pl_wire_length_coef = _get_pnr_val(ctx, pnr_config, "pl_wire_length_coef"),
            pl_min_phi_coefficient = _get_pnr_val(ctx, pnr_config, "pl_min_phi_coefficient"),
            pl_max_phi_coefficient = _get_pnr_val(ctx, pnr_config, "pl_max_phi_coefficient"),
            pl_time_driven = _get_pnr_val(ctx, pnr_config, "pl_time_driven"),
            pl_routability_driven = _get_pnr_val(ctx, pnr_config, "pl_routability_driven"),
            pl_routability_overflow_threshold = _get_pnr_val(ctx, pnr_config, "pl_routability_overflow_threshold"),
            pl_optimize_mirroring = _get_pnr_val(ctx, pnr_config, "pl_optimize_mirroring"),
            pl_max_displacement_x = _get_pnr_val(ctx, pnr_config, "pl_max_displacement_x"),
            pl_max_displacement_y = _get_pnr_val(ctx, pnr_config, "pl_max_displacement_y"),
            manual_global_placements = _get_pnr_val(ctx, pnr_config, "manual_global_placements"),
            cts_sink_clustering_size = _get_pnr_val(ctx, pnr_config, "cts_sink_clustering_size"),
            cts_sink_clustering_max_diameter = _get_pnr_val(ctx, pnr_config, "cts_sink_clustering_max_diameter"),
            cts_clk_max_wire_length = _get_pnr_val(ctx, pnr_config, "cts_clk_max_wire_length"),
            cts_disable_post_processing = _get_pnr_val(ctx, pnr_config, "cts_disable_post_processing"),
            cts_distance_between_buffers = _get_pnr_val(ctx, pnr_config, "cts_distance_between_buffers"),
            cts_corners = _get_pnr_val(ctx, pnr_config, "cts_corners"),
            cts_max_cap = _get_pnr_val(ctx, pnr_config, "cts_max_cap"),
            cts_max_slew = _get_pnr_val(ctx, pnr_config, "cts_max_slew"),
            rt_clock_min_layer = _get_pnr_val(ctx, pnr_config, "rt_clock_min_layer"),
            rt_clock_max_layer = _get_pnr_val(ctx, pnr_config, "rt_clock_max_layer"),
            grt_adjustment = _get_pnr_val(ctx, pnr_config, "grt_adjustment"),
            grt_macro_extension = _get_pnr_val(ctx, pnr_config, "grt_macro_extension"),
            grt_allow_congestion = _get_pnr_val(ctx, pnr_config, "grt_allow_congestion"),
            grt_antenna_iters = _get_pnr_val(ctx, pnr_config, "grt_antenna_iters"),
            grt_overflow_iters = _get_pnr_val(ctx, pnr_config, "grt_overflow_iters"),
            grt_antenna_margin = _get_pnr_val(ctx, pnr_config, "grt_antenna_margin"),
            drt_threads = _get_pnr_val(ctx, pnr_config, "drt_threads"),
            drt_min_layer = _get_pnr_val(ctx, pnr_config, "drt_min_layer"),
            drt_max_layer = _get_pnr_val(ctx, pnr_config, "drt_max_layer"),
            drt_opt_iters = _get_pnr_val(ctx, pnr_config, "drt_opt_iters"),
            rsz_dont_touch_rx = _get_pnr_val(ctx, pnr_config, "rsz_dont_touch_rx"),
            rsz_dont_touch_list = _get_pnr_val(ctx, pnr_config, "rsz_dont_touch_list"),
            rsz_corners = _get_pnr_val(ctx, pnr_config, "rsz_corners"),
            design_repair_buffer_input_ports = _get_pnr_val(ctx, pnr_config, "design_repair_buffer_input_ports"),
            design_repair_buffer_output_ports = _get_pnr_val(ctx, pnr_config, "design_repair_buffer_output_ports"),
            design_repair_tie_fanout = _get_pnr_val(ctx, pnr_config, "design_repair_tie_fanout"),
            design_repair_tie_separation = _get_pnr_val(ctx, pnr_config, "design_repair_tie_separation"),
            design_repair_max_wire_length = _get_pnr_val(ctx, pnr_config, "design_repair_max_wire_length"),
            design_repair_max_slew_pct = _get_pnr_val(ctx, pnr_config, "design_repair_max_slew_pct"),
            design_repair_max_cap_pct = _get_pnr_val(ctx, pnr_config, "design_repair_max_cap_pct"),
            design_repair_remove_buffers = _get_pnr_val(ctx, pnr_config, "design_repair_remove_buffers"),
            pl_resizer_hold_slack_margin = _get_pnr_val(ctx, pnr_config, "pl_resizer_hold_slack_margin"),
            pl_resizer_setup_slack_margin = _get_pnr_val(ctx, pnr_config, "pl_resizer_setup_slack_margin"),
            pl_resizer_hold_max_buffer_pct = _get_pnr_val(ctx, pnr_config, "pl_resizer_hold_max_buffer_pct"),
            pl_resizer_setup_max_buffer_pct = _get_pnr_val(ctx, pnr_config, "pl_resizer_setup_max_buffer_pct"),
            pl_resizer_allow_setup_vios = _get_pnr_val(ctx, pnr_config, "pl_resizer_allow_setup_vios"),
            pl_resizer_gate_cloning = _get_pnr_val(ctx, pnr_config, "pl_resizer_gate_cloning"),
            pl_resizer_fix_hold_first = _get_pnr_val(ctx, pnr_config, "pl_resizer_fix_hold_first"),
            grt_design_repair_run_grt = _get_pnr_val(ctx, pnr_config, "grt_design_repair_run_grt"),
            grt_design_repair_max_wire_length = _get_pnr_val(ctx, pnr_config, "grt_design_repair_max_wire_length"),
            grt_design_repair_max_slew_pct = _get_pnr_val(ctx, pnr_config, "grt_design_repair_max_slew_pct"),
            grt_design_repair_max_cap_pct = _get_pnr_val(ctx, pnr_config, "grt_design_repair_max_cap_pct"),
            grt_resizer_hold_slack_margin = _get_pnr_val(ctx, pnr_config, "grt_resizer_hold_slack_margin"),
            grt_resizer_setup_slack_margin = _get_pnr_val(ctx, pnr_config, "grt_resizer_setup_slack_margin"),
            grt_resizer_hold_max_buffer_pct = _get_pnr_val(ctx, pnr_config, "grt_resizer_hold_max_buffer_pct"),
            grt_resizer_setup_max_buffer_pct = _get_pnr_val(ctx, pnr_config, "grt_resizer_setup_max_buffer_pct"),
            grt_resizer_allow_setup_vios = _get_pnr_val(ctx, pnr_config, "grt_resizer_allow_setup_vios"),
            grt_resizer_gate_cloning = _get_pnr_val(ctx, pnr_config, "grt_resizer_gate_cloning"),
            grt_resizer_run_grt = _get_pnr_val(ctx, pnr_config, "grt_resizer_run_grt"),
            grt_resizer_fix_hold_first = _get_pnr_val(ctx, pnr_config, "grt_resizer_fix_hold_first"),
            diode_padding = _get_pnr_val(ctx, pnr_config, "diode_padding"),
            diode_on_ports = _get_pnr_val(ctx, pnr_config, "diode_on_ports"),
            extra_excluded_cells = _get_pnr_val(ctx, pnr_config, "extra_excluded_cells"),
            macro_placement_cfg = _get_pnr_val(ctx, pnr_config, "macro_placement_cfg"),

            # Signoff config
            sta_macro_prioritize_nl = _get_signoff_val(ctx, signoff_config, "sta_macro_prioritize_nl"),
            sta_max_violator_count = _get_signoff_val(ctx, signoff_config, "sta_max_violator_count"),
            sta_threads = _get_signoff_val(ctx, signoff_config, "sta_threads"),
            vsrc_loc_files = _get_signoff_val(ctx, signoff_config, "vsrc_loc_files"),
            rcx_merge_via_wire_res = _get_signoff_val(ctx, signoff_config, "rcx_merge_via_wire_res"),
            rcx_sdc_file = _get_signoff_val(ctx, signoff_config, "rcx_sdc_file"),
            magic_def_labels = _get_signoff_val(ctx, signoff_config, "magic_def_labels"),
            magic_gds_polygon_subcells = _get_signoff_val(ctx, signoff_config, "magic_gds_polygon_subcells"),
            magic_def_no_blockages = _get_signoff_val(ctx, signoff_config, "magic_def_no_blockages"),
            magic_include_gds_pointers = _get_signoff_val(ctx, signoff_config, "magic_include_gds_pointers"),
            magic_capture_errors = _get_signoff_val(ctx, signoff_config, "magic_capture_errors"),
            magic_ext_use_gds = _get_signoff_val(ctx, signoff_config, "magic_ext_use_gds"),
            magic_ext_abstract_cells = _get_signoff_val(ctx, signoff_config, "magic_ext_abstract_cells"),
            magic_no_ext_unique = _get_signoff_val(ctx, signoff_config, "magic_no_ext_unique"),
            magic_ext_short_resistor = _get_signoff_val(ctx, signoff_config, "magic_ext_short_resistor"),
            magic_ext_abstract = _get_signoff_val(ctx, signoff_config, "magic_ext_abstract"),
            magic_feedback_conversion_threshold = _get_signoff_val(ctx, signoff_config, "magic_feedback_conversion_threshold"),
            magic_zeroize_origin = _get_signoff_val(ctx, signoff_config, "magic_zeroize_origin"),
            magic_disable_cif_info = _get_signoff_val(ctx, signoff_config, "magic_disable_cif_info"),
            magic_macro_std_cell_source = _get_signoff_val(ctx, signoff_config, "magic_macro_std_cell_source"),
            magic_lef_write_use_gds = _get_signoff_val(ctx, signoff_config, "magic_lef_write_use_gds"),
            magic_write_full_lef = _get_signoff_val(ctx, signoff_config, "magic_write_full_lef"),
            magic_write_lef_pinonly = _get_signoff_val(ctx, signoff_config, "magic_write_lef_pinonly"),
            magic_drc_use_gds = _get_signoff_val(ctx, signoff_config, "magic_drc_use_gds"),
            run_magic_drc = _get_signoff_val(ctx, signoff_config, "run_magic_drc"),
            klayout_xor_threads = _get_signoff_val(ctx, signoff_config, "klayout_xor_threads"),
            klayout_drc_threads = _get_signoff_val(ctx, signoff_config, "klayout_drc_threads"),
            run_klayout_drc = _get_signoff_val(ctx, signoff_config, "run_klayout_drc"),
            run_lvs = _get_signoff_val(ctx, signoff_config, "run_lvs"),
            lvs_include_marco_netlists = _get_signoff_val(ctx, signoff_config, "lvs_include_marco_netlists"),
            lvs_flatten_cells = _get_signoff_val(ctx, signoff_config, "lvs_flatten_cells"),
            extra_lefs = _get_signoff_val(ctx, signoff_config, "extra_lefs"),
            extra_gds_files = _get_signoff_val(ctx, signoff_config, "extra_gds_files"),
            extra_spice_models = _get_signoff_val(ctx, signoff_config, "extra_spice_models"),
            error_on_linter_timing_constructs = _get_signoff_val(ctx, signoff_config, "error_on_linter_timing_constructs"),
            error_on_linter_errors = _get_signoff_val(ctx, signoff_config, "error_on_linter_errors"),
            error_on_linter_warnings = _get_signoff_val(ctx, signoff_config, "error_on_linter_warnings"),
            error_on_unmapped_cells = _get_signoff_val(ctx, signoff_config, "error_on_unmapped_cells"),
            error_on_synth_checks = _get_signoff_val(ctx, signoff_config, "error_on_synth_checks"),
            error_on_nl_assign_statements = _get_signoff_val(ctx, signoff_config, "error_on_nl_assign_statements"),
            error_on_pdn_violations = _get_signoff_val(ctx, signoff_config, "error_on_pdn_violations"),
            error_on_tr_drc = _get_signoff_val(ctx, signoff_config, "error_on_tr_drc"),
            error_on_disconnected_pins = _get_signoff_val(ctx, signoff_config, "error_on_disconnected_pins"),
            error_on_long_wire = _get_signoff_val(ctx, signoff_config, "error_on_long_wire"),
            error_on_illegal_overlaps = _get_signoff_val(ctx, signoff_config, "error_on_illegal_overlaps"),
            error_on_lvs_error = _get_signoff_val(ctx, signoff_config, "error_on_lvs_error"),
            error_on_xor_error = _get_signoff_val(ctx, signoff_config, "error_on_xor_error"),
            error_on_magic_drc = _get_signoff_val(ctx, signoff_config, "error_on_magic_drc"),
            error_on_klayout_drc = _get_signoff_val(ctx, signoff_config, "error_on_klayout_drc"),
            setup_violation_corners = _get_signoff_val(ctx, signoff_config, "setup_violation_corners"),
            hold_violation_corners = _get_signoff_val(ctx, signoff_config, "hold_violation_corners"),
            max_slew_violation_corners = _get_signoff_val(ctx, signoff_config, "max_slew_violation_corners"),
            max_cap_violation_corners = _get_signoff_val(ctx, signoff_config, "max_cap_violation_corners"),
        ),
        # LibrelaneInfo - initial state (all empty)
        LibrelaneInfo(
            state_out = None,
            nl = None,
            pnl = None,
            odb = None,
            sdc = None,
            sdf = None,
            spef = None,
            lib = None,
            gds = None,
            mag_gds = None,
            klayout_gds = None,
            lef = None,
            mag = None,
            spice = None,
            json_h = None,
            vh = None,
            **{"def": None}
        ),
    ]


# Attributes for init rule: core attrs + optional config rule refs
_INIT_ATTRS = dict(CORE_ATTRS)
_INIT_ATTRS.update({
    "synth_config": attr.label(
        doc = "Optional synthesis configuration (librelane_synth_config target)",
        providers = [SynthConfig],
    ),
    "pnr_config": attr.label(
        doc = "Optional PnR configuration (librelane_pnr_config target)",
        providers = [PnRConfig],
    ),
    "signoff_config": attr.label(
        doc = "Optional signoff configuration (librelane_signoff_config target)",
        providers = [SignoffConfig],
    ),
})

librelane_init = rule(
    implementation = _init_impl,
    attrs = _INIT_ATTRS,
    provides = [DefaultInfo, LibrelaneInput, LibrelaneInfo],
)
