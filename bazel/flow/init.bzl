# Init rule - entry point for the flow

load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo", "PdkInfo", "MacroInfo")
load(":common.bzl", "ENTRY_ATTRS")

def _init_impl(ctx):
    """Package verilog files and config into LibrelaneInput and LibrelaneInfo."""
    pdk_info = ctx.attr.pdk[PdkInfo]

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
            # Verilator.Lint config
            verilog_power_define = ctx.attr.verilog_power_define,
            linter_include_pdk_models = ctx.attr.linter_include_pdk_models,
            linter_relative_includes = ctx.attr.linter_relative_includes,
            linter_error_on_latch = ctx.attr.linter_error_on_latch,
            linter_defines = ctx.attr.linter_defines,
            extra_verilog_models = ctx.files.extra_verilog_models,
            # Checker config
            error_on_linter_timing_constructs = ctx.attr.error_on_linter_timing_constructs,
            error_on_linter_errors = ctx.attr.error_on_linter_errors,
            error_on_linter_warnings = ctx.attr.error_on_linter_warnings,
            # Yosys config
            synth_parameters = ctx.attr.synth_parameters,
            use_synlig = ctx.attr.use_synlig,
            synlig_defer = ctx.attr.synlig_defer,
            use_lighter = ctx.attr.use_lighter,
            lighter_dff_map = ctx.file.lighter_dff_map,
            yosys_log_level = ctx.attr.yosys_log_level,
            # Yosys.Synthesis config
            synth_checks_allow_tristate = ctx.attr.synth_checks_allow_tristate,
            synth_autoname = ctx.attr.synth_autoname,
            synth_strategy = ctx.attr.synth_strategy,
            synth_abc_buffering = ctx.attr.synth_abc_buffering,
            synth_abc_legacy_refactor = ctx.attr.synth_abc_legacy_refactor,
            synth_abc_legacy_rewrite = ctx.attr.synth_abc_legacy_rewrite,
            synth_abc_dff = ctx.attr.synth_abc_dff,
            synth_abc_use_mfs3 = ctx.attr.synth_abc_use_mfs3,
            synth_abc_area_use_nf = ctx.attr.synth_abc_area_use_nf,
            synth_direct_wire_buffering = ctx.attr.synth_direct_wire_buffering,
            synth_splitnets = ctx.attr.synth_splitnets,
            synth_sizing = ctx.attr.synth_sizing,
            synth_hierarchy_mode = ctx.attr.synth_hierarchy_mode,
            synth_share_resources = ctx.attr.synth_share_resources,
            synth_adder_type = ctx.attr.synth_adder_type,
            synth_extra_mapping_file = ctx.file.synth_extra_mapping_file,
            synth_elaborate_only = ctx.attr.synth_elaborate_only,
            synth_elaborate_flatten = ctx.attr.synth_elaborate_flatten,
            synth_mul_booth = ctx.attr.synth_mul_booth,
            synth_tie_undefined = ctx.attr.synth_tie_undefined,
            synth_write_noattr = ctx.attr.synth_write_noattr,
            # Post-synthesis checker config
            error_on_unmapped_cells = ctx.attr.error_on_unmapped_cells,
            error_on_synth_checks = ctx.attr.error_on_synth_checks,
            error_on_nl_assign_statements = ctx.attr.error_on_nl_assign_statements,
            error_on_pdn_violations = ctx.attr.error_on_pdn_violations,
            error_on_tr_drc = ctx.attr.error_on_tr_drc,
            error_on_disconnected_pins = ctx.attr.error_on_disconnected_pins,
            error_on_long_wire = ctx.attr.error_on_long_wire,
            error_on_illegal_overlaps = ctx.attr.error_on_illegal_overlaps,
            error_on_lvs_error = ctx.attr.error_on_lvs_error,
            # OpenROADStep config
            pdn_connect_macros_to_grid = ctx.attr.pdn_connect_macros_to_grid,
            pdn_macro_connections = ctx.attr.pdn_macro_connections,
            pdn_enable_global_connections = ctx.attr.pdn_enable_global_connections,
            fp_def_template = ctx.file.fp_def_template if ctx.attr.fp_def_template else None,
            fp_pin_order_cfg = ctx.file.fp_pin_order_cfg if ctx.attr.fp_pin_order_cfg else None,
            fp_template_match_mode = ctx.attr.fp_template_match_mode,
            fp_template_copy_power_pins = ctx.attr.fp_template_copy_power_pins,
            extra_excluded_cells = ctx.attr.extra_excluded_cells,
            # MultiCornerSTA config
            sta_macro_prioritize_nl = ctx.attr.sta_macro_prioritize_nl,
            sta_max_violator_count = ctx.attr.sta_max_violator_count,
            sta_threads = ctx.attr.sta_threads,
            # OpenROAD.IRDropReport config
            # attr.label_keyed_string_dict: Target -> net_name, invert to net_name -> File
            vsrc_loc_files = {net_name: target.files.to_list()[0] for target, net_name in ctx.attr.vsrc_loc_files.items()} if ctx.attr.vsrc_loc_files else {},
            # MagicStep config
            magic_def_labels = ctx.attr.magic_def_labels,
            magic_gds_polygon_subcells = ctx.attr.magic_gds_polygon_subcells,
            magic_def_no_blockages = ctx.attr.magic_def_no_blockages,
            magic_include_gds_pointers = ctx.attr.magic_include_gds_pointers,
            magic_capture_errors = ctx.attr.magic_capture_errors,
            # Magic.SpiceExtraction config
            magic_ext_use_gds = ctx.attr.magic_ext_use_gds,
            magic_ext_abstract_cells = ctx.attr.magic_ext_abstract_cells,
            magic_no_ext_unique = ctx.attr.magic_no_ext_unique,
            magic_ext_short_resistor = ctx.attr.magic_ext_short_resistor,
            magic_ext_abstract = ctx.attr.magic_ext_abstract,
            magic_feedback_conversion_threshold = ctx.attr.magic_feedback_conversion_threshold,
            # Magic.StreamOut config
            magic_zeroize_origin = ctx.attr.magic_zeroize_origin,
            magic_disable_cif_info = ctx.attr.magic_disable_cif_info,
            magic_macro_std_cell_source = ctx.attr.magic_macro_std_cell_source,
            # OpenROAD.RCX config
            rcx_merge_via_wire_res = ctx.attr.rcx_merge_via_wire_res,
            rcx_sdc_file = ctx.file.rcx_sdc_file if ctx.attr.rcx_sdc_file else None,
            # OpenROAD.CutRows config
            fp_macro_horizontal_halo = ctx.attr.fp_macro_horizontal_halo,
            fp_macro_vertical_halo = ctx.attr.fp_macro_vertical_halo,
            # Odb.AddPDNObstructions / Odb.RemovePDNObstructions
            pdn_obstructions = ctx.attr.pdn_obstructions,
            # Odb.AddRoutingObstructions / Odb.RemoveRoutingObstructions
            routing_obstructions = ctx.attr.routing_obstructions,
            # io_layer_variables (IOPlacement, CustomIOPlacement)
            fp_io_vextend = ctx.attr.fp_io_vextend,
            fp_io_hextend = ctx.attr.fp_io_hextend,
            fp_io_vthickness_mult = ctx.attr.fp_io_vthickness_mult,
            fp_io_hthickness_mult = ctx.attr.fp_io_hthickness_mult,
            # CustomIOPlacement config
            errors_on_unmatched_io = ctx.attr.errors_on_unmatched_io,
            # GlobalPlacement config
            pl_target_density_pct = ctx.attr.pl_target_density_pct,
            fp_ppl_mode = ctx.attr.fp_ppl_mode,
            pl_skip_initial_placement = ctx.attr.pl_skip_initial_placement,
            pl_wire_length_coef = ctx.attr.pl_wire_length_coef,
            pl_min_phi_coefficient = ctx.attr.pl_min_phi_coefficient,
            pl_max_phi_coefficient = ctx.attr.pl_max_phi_coefficient,
            rt_clock_min_layer = ctx.attr.rt_clock_min_layer,
            rt_clock_max_layer = ctx.attr.rt_clock_max_layer,
            grt_adjustment = ctx.attr.grt_adjustment,
            grt_macro_extension = ctx.attr.grt_macro_extension,
            pl_time_driven = ctx.attr.pl_time_driven,
            pl_routability_driven = ctx.attr.pl_routability_driven,
            pl_routability_overflow_threshold = ctx.attr.pl_routability_overflow_threshold,
            fp_core_util = ctx.attr.fp_core_util,
            # OpenROAD.GeneratePDN (pdn_variables)
            fp_pdn_skiptrim = ctx.attr.fp_pdn_skiptrim,
            fp_pdn_core_ring = ctx.attr.fp_pdn_core_ring,
            fp_pdn_enable_rails = ctx.attr.fp_pdn_enable_rails,
            fp_pdn_horizontal_halo = ctx.attr.fp_pdn_horizontal_halo,
            fp_pdn_vertical_halo = ctx.attr.fp_pdn_vertical_halo,
            fp_pdn_multilayer = ctx.attr.fp_pdn_multilayer,
            fp_pdn_cfg = ctx.file.fp_pdn_cfg if ctx.attr.fp_pdn_cfg else None,
            # grt_variables (ResizerStep subclasses)
            diode_padding = ctx.attr.diode_padding,
            grt_allow_congestion = ctx.attr.grt_allow_congestion,
            grt_antenna_iters = ctx.attr.grt_antenna_iters,
            grt_overflow_iters = ctx.attr.grt_overflow_iters,
            grt_antenna_margin = ctx.attr.grt_antenna_margin,
            # dpl_variables (ResizerStep subclasses)
            pl_optimize_mirroring = ctx.attr.pl_optimize_mirroring,
            pl_max_displacement_x = ctx.attr.pl_max_displacement_x,
            pl_max_displacement_y = ctx.attr.pl_max_displacement_y,
            # rsz_variables (ResizerStep subclasses)
            rsz_dont_touch_rx = ctx.attr.rsz_dont_touch_rx,
            rsz_dont_touch_list = ctx.attr.rsz_dont_touch_list,
            rsz_corners = ctx.attr.rsz_corners,
            # RepairDesignPostGPL config_vars
            design_repair_buffer_input_ports = ctx.attr.design_repair_buffer_input_ports,
            design_repair_buffer_output_ports = ctx.attr.design_repair_buffer_output_ports,
            design_repair_tie_fanout = ctx.attr.design_repair_tie_fanout,
            design_repair_tie_separation = ctx.attr.design_repair_tie_separation,
            design_repair_max_wire_length = ctx.attr.design_repair_max_wire_length,
            design_repair_max_slew_pct = ctx.attr.design_repair_max_slew_pct,
            design_repair_max_cap_pct = ctx.attr.design_repair_max_cap_pct,
            design_repair_remove_buffers = ctx.attr.design_repair_remove_buffers,
            # Odb.ManualGlobalPlacement config
            manual_global_placements = ctx.attr.manual_global_placements,
            # OpenROAD.CTS config_vars
            cts_sink_clustering_size = ctx.attr.cts_sink_clustering_size,
            cts_sink_clustering_max_diameter = ctx.attr.cts_sink_clustering_max_diameter,
            cts_clk_max_wire_length = ctx.attr.cts_clk_max_wire_length,
            cts_disable_post_processing = ctx.attr.cts_disable_post_processing,
            cts_distance_between_buffers = ctx.attr.cts_distance_between_buffers,
            cts_corners = ctx.attr.cts_corners,
            cts_max_cap = ctx.attr.cts_max_cap,
            cts_max_slew = ctx.attr.cts_max_slew,
            # ResizerTimingPostCTS/PostGRT config_vars
            pl_resizer_hold_slack_margin = ctx.attr.pl_resizer_hold_slack_margin,
            pl_resizer_setup_slack_margin = ctx.attr.pl_resizer_setup_slack_margin,
            pl_resizer_hold_max_buffer_pct = ctx.attr.pl_resizer_hold_max_buffer_pct,
            pl_resizer_setup_max_buffer_pct = ctx.attr.pl_resizer_setup_max_buffer_pct,
            pl_resizer_allow_setup_vios = ctx.attr.pl_resizer_allow_setup_vios,
            pl_resizer_gate_cloning = ctx.attr.pl_resizer_gate_cloning,
            pl_resizer_fix_hold_first = ctx.attr.pl_resizer_fix_hold_first,
            # RepairDesignPostGRT
            grt_design_repair_run_grt = ctx.attr.grt_design_repair_run_grt,
            grt_design_repair_max_wire_length = ctx.attr.grt_design_repair_max_wire_length,
            grt_design_repair_max_slew_pct = ctx.attr.grt_design_repair_max_slew_pct,
            grt_design_repair_max_cap_pct = ctx.attr.grt_design_repair_max_cap_pct,
            # ResizerTimingPostGRT
            grt_resizer_hold_slack_margin = ctx.attr.grt_resizer_hold_slack_margin,
            grt_resizer_setup_slack_margin = ctx.attr.grt_resizer_setup_slack_margin,
            grt_resizer_hold_max_buffer_pct = ctx.attr.grt_resizer_hold_max_buffer_pct,
            grt_resizer_setup_max_buffer_pct = ctx.attr.grt_resizer_setup_max_buffer_pct,
            grt_resizer_allow_setup_vios = ctx.attr.grt_resizer_allow_setup_vios,
            grt_resizer_gate_cloning = ctx.attr.grt_resizer_gate_cloning,
            grt_resizer_run_grt = ctx.attr.grt_resizer_run_grt,
            grt_resizer_fix_hold_first = ctx.attr.grt_resizer_fix_hold_first,
            # Odb.DiodesOnPorts
            diode_on_ports = ctx.attr.diode_on_ports,
            # DetailedRouting
            drt_threads = ctx.attr.drt_threads,
            drt_min_layer = ctx.attr.drt_min_layer,
            drt_max_layer = ctx.attr.drt_max_layer,
            drt_opt_iters = ctx.attr.drt_opt_iters,
            # KLayout/Magic/OpenROAD extra files
            extra_lefs = ctx.files.extra_lefs,
            extra_gds_files = ctx.files.extra_gds_files,
            # Magic.WriteLEF config
            magic_lef_write_use_gds = ctx.attr.magic_lef_write_use_gds,
            magic_write_full_lef = ctx.attr.magic_write_full_lef,
            magic_write_lef_pinonly = ctx.attr.magic_write_lef_pinonly,
            # KLayout.XOR config
            klayout_xor_threads = ctx.attr.klayout_xor_threads,
            # Checker.XOR config
            error_on_xor_error = ctx.attr.error_on_xor_error,
            # Magic.DRC config
            magic_drc_use_gds = ctx.attr.magic_drc_use_gds,
            # Magic.DRC gating
            run_magic_drc = ctx.attr.run_magic_drc,
            # Checker.MagicDRC config
            error_on_magic_drc = ctx.attr.error_on_magic_drc,
            # KLayout.DRC config
            klayout_drc_threads = ctx.attr.klayout_drc_threads,
            # KLayout.DRC gating
            run_klayout_drc = ctx.attr.run_klayout_drc,
            # Checker.KLayoutDRC config
            error_on_klayout_drc = ctx.attr.error_on_klayout_drc,
            # Netgen.LVS config
            run_lvs = ctx.attr.run_lvs,
            lvs_include_marco_netlists = ctx.attr.lvs_include_marco_netlists,
            lvs_flatten_cells = ctx.attr.lvs_flatten_cells,
            extra_spice_models = ctx.files.extra_spice_models,
            # Yosys.EQY config
            run_eqy = ctx.attr.run_eqy,
            eqy_script = ctx.file.eqy_script if ctx.attr.eqy_script else None,
            eqy_force_accept_pdk = ctx.attr.eqy_force_accept_pdk,
            macro_placement_cfg = ctx.file.macro_placement_cfg if ctx.attr.macro_placement_cfg else None,
            # TimingViolations checker config
            setup_violation_corners = ctx.attr.setup_violation_corners,
            hold_violation_corners = ctx.attr.hold_violation_corners,
            max_slew_violation_corners = ctx.attr.max_slew_violation_corners,
            max_cap_violation_corners = ctx.attr.max_cap_violation_corners,
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

librelane_init = rule(
    implementation = _init_impl,
    attrs = ENTRY_ATTRS,
    provides = [DefaultInfo, LibrelaneInput, LibrelaneInfo],
)
