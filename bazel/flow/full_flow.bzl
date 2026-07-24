# Full P&R flow macros - matches librelane Classic flow

load(":init.bzl", "librelane_init")
load("//bazel/flow/config:pnr.bzl", "librelane_pnr_config")
load("//bazel/flow/sdc:sdc_template.bzl", "sdc_template")
load(":verilator.bzl", "librelane_verilator_lint")
load(":checker.bzl",
    "librelane_lint_timing_constructs",
    "librelane_lint_errors",
    "librelane_lint_warnings",
    "librelane_yosys_unmapped_cells",
    "librelane_yosys_synth_checks",
    "librelane_netlist_assign_statements",
    "librelane_power_grid_violations",
    "librelane_tr_drc",
    "librelane_disconnected_pins",
    "librelane_wire_length",
    "librelane_xor",
    "librelane_magic_drc_checker",
    "librelane_klayout_drc_checker",
    "librelane_illegal_overlap",
    "librelane_lvs_checker",
    "librelane_setup_violations",
    "librelane_hold_violations",
    "librelane_max_slew_violations",
    "librelane_max_cap_violations",
    "zamlet_setup_wns_threshold",
    "zamlet_antenna_violations",
)
load(":synthesis.bzl", "librelane_synthesis", "librelane_json_header", "librelane_eqy")
load(":floorplan.bzl", "librelane_floorplan", "librelane_dump_rc_values")
load(":place.bzl",
    "librelane_cut_rows",
    "librelane_tap_endcap_insertion",
    "librelane_generate_pdn",
    "librelane_global_placement_skip_io",
    "librelane_io_placement",
    "librelane_custom_io_placement",
    "librelane_apply_def_template",
    "librelane_global_placement",
    "librelane_repair_design_post_gpl",
    "librelane_detailed_placement",
    "librelane_cts",
    "librelane_resizer_timing_post_cts",
    "librelane_manual_macro_placement",
)
load(":route.bzl",
    "librelane_global_routing",
    "librelane_repair_design_post_grt",
    "librelane_repair_antennas",
    "librelane_resizer_timing_post_grt",
    "librelane_detailed_routing",
    "librelane_check_antennas",
)
load(":sta.bzl",
    "librelane_rcx",
    "librelane_sta_post_pnr",
    "librelane_sta_mid_pnr",
    "librelane_check_sdc_files",
    "librelane_check_macro_instances",
    "librelane_sta_pre_pnr",
    "librelane_ir_drop_report",
)
load(":odb.bzl",
    "librelane_check_macro_antenna_properties",
    "librelane_check_design_antenna_properties",
    "librelane_set_power_connections",
    "librelane_add_pdn_obstructions",
    "librelane_remove_pdn_obstructions",
    "librelane_add_routing_obstructions",
    "librelane_remove_routing_obstructions",
    "librelane_write_verilog_header",
    "librelane_manual_global_placement",
    "librelane_report_disconnected_pins",
    "librelane_report_wire_length",
    "librelane_diodes_on_ports",
    "librelane_heuristic_diode_insertion",
    "librelane_cell_frequency_tables",
)
load(":macro.bzl",
    "librelane_fill",
    "librelane_gds",
    "librelane_lef",
    "librelane_magic_drc",
    "librelane_spice_extraction",
)
load(":klayout.bzl",
    "librelane_klayout_stream_out",
    "librelane_klayout_xor",
    "librelane_klayout_drc",
)
load(":netgen.bzl", "librelane_netgen_lvs")
load(":misc.bzl", "librelane_report_manufacturability")


def librelane_classic_flow(
    name,
    verilog_files,
    top,
    pdk,
    clock_period = "10.0",
    clock_port = "clock",
    fp_core_util = "50",
    pl_target_density_pct = "",
    die_area = None,
    macros = [],
    io_pin_order_cfg = None,
    io_pin_h_thickness_mult = None,
    io_pin_v_thickness_mult = None,
    fp_def_template = None,
    macro_placement_cfg = None,
    pdn_macro_connections = [],
    cts_clk_max_wire_length = None,
    default_corner = "",
    max_transition_constraint = "",
    max_capacitance_constraint = "",
    design_repair_max_wire_length = None,
    design_repair_max_slew_pct = None,
    design_repair_max_cap_pct = None,
    pl_resizer_hold_slack_margin = None,
    pl_resizer_setup_slack_margin = None,
    grt_resizer_hold_slack_margin = None,
    grt_design_repair_max_wire_length = None,
    run_cts = True,
    run_post_cts_resizer_timing = True,
    run_eqy = False,
    run_linter = True,
    run_tap_endcap_insertion = True,
    run_post_gpl_design_repair = True,
    run_post_grt_design_repair = False,
    pdn_obstructions = None,
    routing_obstructions = None,
    diode_on_ports = "none",
    run_heuristic_diode_insertion = False,
    run_antenna_repair = True,
    grt_antenna_repair_iters = None,
    grt_antenna_repair_margin = None,
    grt_antenna_repair_jumper_only = None,
    grt_antenna_repair_diode_only = None,
    run_post_grt_resizer_timing = False,
    run_drt = True,
    run_fill_insertion = True,
    run_spef_extraction = True,
    run_mcsta = True,
    run_irdrop_report = True,
    run_magic_streamout = True,
    run_klayout_streamout = True,
    run_magic_write_lef = True,
    run_klayout_xor = True,
    run_magic_drc = True,
    run_klayout_drc = True,
    run_lvs = True,
    mid_setup_wns_threshold = "0",
    manual_global_placements = None,
    pnr_sdc_file = None,
    signoff_sdc_file = None,
    sdc_fragments = [],
    input_delay_constraint = None,
    output_delay_constraint = None,
    synth_config = None):
    """Flow from Verilog through detailed routing and STA.

    Matches librelane Classic flow order:
    Synthesis -> Floorplan -> CutRows -> TapEndcap -> PDN ->
    GlobalPlacementSkipIO -> IOPlacement -> GlobalPlacement ->
    RepairDesignPostGPL -> DetailedPlacement -> CTS -> ResizerTimingPostCTS ->
    GlobalRouting -> RepairDesignPostGRT -> RepairAntennas -> ResizerTimingPostGRT ->
    DetailedRouting -> RCX -> STAPostPNR

    Args:
        name: Base name for all targets
        verilog_files: List of Verilog source files
        top: Top module name
        pdk: PDK target
        clock_period: Clock period in ns
        clock_port: Clock port name
        fp_core_util: Target core utilization (0-100), ignored if die_area specified
        pl_target_density_pct: Target placement density percentage (0-100), empty for dynamic
        die_area: Explicit die area as "x0 y0 x1 y1" in microns
        macros: List of hard macro targets (for hierarchical designs)
        io_pin_order_cfg: Pin order configuration file for custom IO placement
        io_pin_h_thickness_mult: Horizontal pin thickness as a multiple of layer minimum width
        io_pin_v_thickness_mult: Vertical pin thickness as a multiple of layer minimum width
        fp_def_template: DEF template file with die area and pin placements (alternative to io_pin_order_cfg)
        macro_placement_cfg: Macro placement configuration file (instance X Y orientation)
        pdn_macro_connections: Explicit macro power connections
        cts_clk_max_wire_length: Max clock wire length in µm before buffer insertion (0=disabled)
        default_corner: Override DEFAULT_CORNER from the PDK config
        max_transition_constraint: Override MAX_TRANSITION_CONSTRAINT from the PDK config
        max_capacitance_constraint: Override MAX_CAPACITANCE_CONSTRAINT from the PDK config
        design_repair_max_slew_pct: Override DESIGN_REPAIR_MAX_SLEW_PCT
        design_repair_max_cap_pct: Override DESIGN_REPAIR_MAX_CAP_PCT
        run_cts: Enable clock tree synthesis (default True)
        run_post_cts_resizer_timing: Enable timing optimization after CTS (default True, ignored if run_cts=False)
        run_eqy: Enable EQY formal equivalence check (default False)
        run_linter: Enable Verilator linting (default True)
        run_tap_endcap_insertion: Enable tap/endcap insertion (default True)
        run_post_gpl_design_repair: Enable design repair after global placement (default True)
        run_post_grt_design_repair: Enable design repair after global routing (default False, experimental)
        run_spef_extraction: Enable parasitic extraction before final STA (default True)
        run_mcsta: Enable final multi-corner STA after extraction (default True)
        run_irdrop_report: Enable IR drop reporting (default True)
        run_magic_streamout: Enable Magic GDS stream-out (default True)
        run_klayout_streamout: Enable KLayout GDS stream-out (default True)
        run_magic_write_lef: Enable Magic LEF generation (default True)
        run_klayout_xor: Enable KLayout-vs-Magic XOR check (default True)
        run_magic_drc: Enable Magic DRC and Magic DRC checker (default True)
        run_klayout_drc: Enable KLayout DRC and KLayout DRC checker (default True)
    """

    # Generate templated SDC with delay constraints
    effective_pnr_sdc = pnr_sdc_file
    effective_signoff_sdc = signoff_sdc_file
    sdc_template(
        name = name + "_sdc",
        template = "//bazel/flow/sdc:base.sdc",
        input_delay_constraint = input_delay_constraint if input_delay_constraint else "60",
        output_delay_constraint = output_delay_constraint if output_delay_constraint else "60",
        fragments = sdc_fragments,
    )
    if not pnr_sdc_file:
        effective_pnr_sdc = ":" + name + "_sdc"
    if not signoff_sdc_file:
        effective_signoff_sdc = ":" + name + "_sdc"

    # PnR config - create if any PnR params are non-default
    pnr_config_kwargs = {}
    if pl_target_density_pct:
        pnr_config_kwargs["pl_target_density_pct"] = pl_target_density_pct
    if io_pin_order_cfg:
        pnr_config_kwargs["io_pin_order_cfg"] = io_pin_order_cfg
    if io_pin_h_thickness_mult != None:
        pnr_config_kwargs["io_pin_h_thickness_mult"] = io_pin_h_thickness_mult
    if io_pin_v_thickness_mult != None:
        pnr_config_kwargs["io_pin_v_thickness_mult"] = io_pin_v_thickness_mult
    if fp_def_template:
        pnr_config_kwargs["fp_def_template"] = fp_def_template
    if cts_clk_max_wire_length:
        pnr_config_kwargs["cts_clk_max_wire_length"] = cts_clk_max_wire_length
    if fp_core_util != "50":
        pnr_config_kwargs["fp_core_util"] = fp_core_util
    if pdn_obstructions:
        pnr_config_kwargs["pdn_obstructions"] = pdn_obstructions
    if routing_obstructions:
        pnr_config_kwargs["routing_obstructions"] = routing_obstructions
    if manual_global_placements:
        pnr_config_kwargs["manual_global_placements"] = manual_global_placements
    if diode_on_ports != "none":
        pnr_config_kwargs["diode_on_ports"] = diode_on_ports
    if macro_placement_cfg:
        pnr_config_kwargs["macro_placement_cfg"] = macro_placement_cfg
    if pdn_macro_connections:
        pnr_config_kwargs["pdn_macro_connections"] = pdn_macro_connections
    if grt_antenna_repair_iters != None:
        pnr_config_kwargs["grt_antenna_repair_iters"] = grt_antenna_repair_iters
    if grt_antenna_repair_margin != None:
        pnr_config_kwargs["grt_antenna_repair_margin"] = grt_antenna_repair_margin
    if grt_antenna_repair_jumper_only != None:
        pnr_config_kwargs["grt_antenna_repair_jumper_only"] = grt_antenna_repair_jumper_only
    if grt_antenna_repair_diode_only != None:
        pnr_config_kwargs["grt_antenna_repair_diode_only"] = grt_antenna_repair_diode_only
    if design_repair_max_wire_length != None:
        pnr_config_kwargs["design_repair_max_wire_length"] = design_repair_max_wire_length
    if design_repair_max_slew_pct != None:
        pnr_config_kwargs["design_repair_max_slew_pct"] = design_repair_max_slew_pct
    if design_repair_max_cap_pct != None:
        pnr_config_kwargs["design_repair_max_cap_pct"] = design_repair_max_cap_pct
    if pl_resizer_hold_slack_margin != None:
        pnr_config_kwargs["pl_resizer_hold_slack_margin"] = pl_resizer_hold_slack_margin
    if pl_resizer_setup_slack_margin != None:
        pnr_config_kwargs["pl_resizer_setup_slack_margin"] = pl_resizer_setup_slack_margin
    if grt_resizer_hold_slack_margin != None:
        pnr_config_kwargs["grt_resizer_hold_slack_margin"] = grt_resizer_hold_slack_margin
    if grt_design_repair_max_wire_length != None:
        pnr_config_kwargs["grt_design_repair_max_wire_length"] = grt_design_repair_max_wire_length

    pnr_config_target = None
    if pnr_config_kwargs:
        librelane_pnr_config(
            name = name + "_pnr_config",
            **pnr_config_kwargs
        )
        pnr_config_target = ":" + name + "_pnr_config"

    # Init - package inputs (creates both LibrelaneInput and LibrelaneInfo)
    librelane_init(
        name = name + "_init",
        verilog_files = verilog_files,
        top = top,
        pdk = pdk,
        clock_period = clock_period,
        clock_port = clock_port,
        macros = macros,
        pnr_sdc_file = effective_pnr_sdc if effective_pnr_sdc else "//bazel/flow/sdc:base.sdc",
        signoff_sdc_file = effective_signoff_sdc if effective_signoff_sdc else "//bazel/flow/sdc:base.sdc",
        pnr_config = pnr_config_target,
        synth_config = synth_config,
        default_corner = default_corner,
        max_transition_constraint = max_transition_constraint,
        max_capacitance_constraint = max_capacitance_constraint,
    )

    # Common input reference for all steps
    input_target = ":" + name + "_init"

    # Linting (gated by run_linter)
    if run_linter:
        librelane_verilator_lint(
            name = name + "_lint",
            input = input_target,
            src = ":" + name + "_init",
        )
        librelane_lint_timing_constructs(
            name = name + "_lint_timing",
            input = input_target,
            src = ":" + name + "_lint",
        )
        librelane_lint_errors(
            name = name + "_lint_errors",
            input = input_target,
            src = ":" + name + "_lint_timing",
        )
        librelane_lint_warnings(
            name = name + "_lint_warnings",
            input = input_target,
            src = ":" + name + "_lint_errors",
        )
        pre_synth_src = ":" + name + "_lint_warnings"
    else:
        pre_synth_src = ":" + name + "_init"

    # JSON header (power connection info for later steps)
    librelane_json_header(
        name = name + "_json_header",
        input = input_target,
        src = pre_synth_src,
    )

    # Synthesis
    librelane_synthesis(
        name = name + "_synth",
        input = input_target,
        src = ":" + name + "_json_header",
    )

    # Post-synthesis checks
    librelane_yosys_unmapped_cells(
        name = name + "_chk_unmapped",
        input = input_target,
        src = ":" + name + "_synth",
    )
    librelane_yosys_synth_checks(
        name = name + "_chk_synth",
        input = input_target,
        src = ":" + name + "_chk_unmapped",
    )
    librelane_netlist_assign_statements(
        name = name + "_chk_assign",
        input = input_target,
        src = ":" + name + "_chk_synth",
    )

    # Pre-PnR validation
    librelane_check_sdc_files(
        name = name + "_chk_sdc",
        input = input_target,
        src = ":" + name + "_chk_assign",
    )
    librelane_check_macro_instances(
        name = name + "_chk_macros",
        input = input_target,
        src = ":" + name + "_chk_sdc",
    )
    librelane_sta_pre_pnr(
        name = name + "_sta_pre",
        input = input_target,
        src = ":" + name + "_chk_macros",
    )

    # Floorplan
    if die_area:
        librelane_floorplan(
            name = name + "_floorplan",
            input = input_target,
            src = ":" + name + "_sta_pre",
            die_area = die_area,
        )
    else:
        librelane_floorplan(
            name = name + "_floorplan",
            input = input_target,
            src = ":" + name + "_sta_pre",
            fp_core_util = fp_core_util,
        )

    # Post-floorplan checks and setup
    librelane_dump_rc_values(
        name = name + "_dump_rc",
        input = input_target,
        src = ":" + name + "_floorplan",
    )
    librelane_check_macro_antenna_properties(
        name = name + "_chk_macro_ant",
        input = input_target,
        src = ":" + name + "_dump_rc",
    )
    librelane_set_power_connections(
        name = name + "_power_conn",
        input = input_target,
        src = ":" + name + "_chk_macro_ant",
    )

    # Manual macro placement self-skips when no placement config is present.
    librelane_manual_macro_placement(
        name = name + "_mpl",
        input = input_target,
        src = ":" + name + "_power_conn",
    )

    # Cut rows (for macro placement clearance)
    librelane_cut_rows(
        name = name + "_cutrows",
        input = input_target,
        src = ":" + name + "_mpl",
    )

    # Tap and endcap cell insertion (gated)
    if run_tap_endcap_insertion:
        librelane_tap_endcap_insertion(
            name = name + "_tapendcap",
            input = input_target,
            src = ":" + name + "_cutrows",
        )
        pre_pdn_src = ":" + name + "_tapendcap"
    else:
        pre_pdn_src = ":" + name + "_cutrows"

    # PDN obstructions self-skip when no obstruction config is present.
    librelane_add_pdn_obstructions(
        name = name + "_add_pdn_obs",
        input = input_target,
        src = pre_pdn_src,
    )

    # Power delivery network
    librelane_generate_pdn(
        name = name + "_pdn",
        input = input_target,
        src = ":" + name + "_add_pdn_obs",
    )

    librelane_remove_pdn_obstructions(
        name = name + "_rm_pdn_obs",
        input = input_target,
        src = ":" + name + "_pdn",
    )
    post_pdn_src = ":" + name + "_rm_pdn_obs"

    # Routing obstructions self-skip when no obstruction config is present.
    librelane_add_routing_obstructions(
        name = name + "_add_route_obs",
        input = input_target,
        src = post_pdn_src,
    )
    pre_gpl_skip_io_src = ":" + name + "_add_route_obs"

    # Global placement (skip IO) - initial placement before IO pins fixed
    librelane_global_placement_skip_io(
        name = name + "_gpl_skip_io",
        input = input_target,
        src = pre_gpl_skip_io_src,
    )

    # IO placement sequence; steps self-skip based on pin-order/template config.
    if fp_def_template and io_pin_order_cfg:
        fail("Cannot specify both fp_def_template and io_pin_order_cfg")

    librelane_io_placement(
        name = name + "_io_place",
        input = input_target,
        src = ":" + name + "_gpl_skip_io",
    )
    librelane_custom_io_placement(
        name = name + "_custom_io",
        input = input_target,
        src = ":" + name + "_io_place",
    )
    librelane_apply_def_template(
        name = name + "_def_template",
        input = input_target,
        src = ":" + name + "_custom_io",
    )
    # Global placement (full) - refine placement with IO pins fixed
    librelane_global_placement(
        name = name + "_gpl",
        input = input_target,
        src = ":" + name + "_def_template",
    )

    # Step 28: Write Verilog header with power ports
    librelane_write_verilog_header(
        name = name + "_vh",
        input = input_target,
        src = ":" + name + "_gpl",
    )

    # Step 29: Check power grid violations
    librelane_power_grid_violations(
        name = name + "_chk_pdn",
        input = input_target,
        src = ":" + name + "_vh",
    )

    # Step 30: STA mid-PnR (after global placement)
    librelane_sta_mid_pnr(
        name = name + "_sta_mid_gpl",
        input = input_target,
        src = ":" + name + "_chk_pdn",
    )

    # Step 31: Repair design after global placement (gated)
    if run_post_gpl_design_repair:
        librelane_repair_design_post_gpl(
            name = name + "_rsz_gpl",
            input = input_target,
            src = ":" + name + "_sta_mid_gpl",
        )
        pre_mgpl_src = ":" + name + "_rsz_gpl"
    else:
        pre_mgpl_src = ":" + name + "_sta_mid_gpl"

    # Step 32: Manual global placement self-skips when no placements are configured.
    librelane_manual_global_placement(
        name = name + "_mgpl",
        input = input_target,
        src = pre_mgpl_src,
    )
    pre_dpl_src = ":" + name + "_mgpl"

    # Step 33: Detailed placement
    librelane_detailed_placement(
        name = name + "_dpl",
        input = input_target,
        src = pre_dpl_src,
    )

    # Steps 34-37: CTS and post-CTS timing optimization (gated)
    if run_cts:
        # Step 34: Clock tree synthesis
        librelane_cts(
            name = name + "_cts",
            input = input_target,
            src = ":" + name + "_dpl",
        )

        # Step 35: STA mid-PnR (after CTS)
        librelane_sta_mid_pnr(
            name = name + "_sta_mid_cts",
            input = input_target,
            src = ":" + name + "_cts",
        )

        # Step 36: Timing optimization after CTS (gated)
        if run_post_cts_resizer_timing:
            librelane_resizer_timing_post_cts(
                name = name + "_rsz_cts",
                input = input_target,
                src = ":" + name + "_sta_mid_cts",
            )

            # Step 37: STA mid-PnR (after resizer timing post-CTS)
            librelane_sta_mid_pnr(
                name = name + "_sta_mid_rsz_cts",
                input = input_target,
                src = ":" + name + "_rsz_cts",
            )
            pre_grt_src = ":" + name + "_sta_mid_rsz_cts"
        else:
            pre_grt_src = ":" + name + "_sta_mid_cts"
    else:
        pre_grt_src = ":" + name + "_dpl"

    # Optional build target for requiring the selected mid-PnR STA point to be
    # clean before global routing.
    zamlet_setup_wns_threshold(
        name = name + "_chk_mid_setup",
        input = input_target,
        src = pre_grt_src,
        threshold = mid_setup_wns_threshold,
    )
    librelane_hold_violations(
        name = name + "_chk_mid_hold",
        input = input_target,
        src = ":" + name + "_chk_mid_setup",
    )
    librelane_max_slew_violations(
        name = name + "_chk_mid_slew",
        input = input_target,
        src = ":" + name + "_chk_mid_hold",
    )
    librelane_max_cap_violations(
        name = name + "_chk_mid_cap",
        input = input_target,
        src = ":" + name + "_chk_mid_slew",
    )

    # Step 38: Global routing
    librelane_global_routing(
        name = name + "_grt",
        input = input_target,
        src = pre_grt_src,
    )

    # Step 39: Check antennas (first occurrence, after GRT)
    librelane_check_antennas(
        name = name + "_chk_ant_grt",
        input = input_target,
        src = ":" + name + "_grt",
    )

    # Step 40: Repair design after global routing (gated, default OFF - experimental)
    if run_post_grt_design_repair:
        librelane_repair_design_post_grt(
            name = name + "_rsz_grt",
            input = input_target,
            src = ":" + name + "_chk_ant_grt",
        )
        pre_diode_src = ":" + name + "_rsz_grt"
    else:
        pre_diode_src = ":" + name + "_chk_ant_grt"

    # Step 41: Diodes on ports (self-skips when DIODE_ON_PORTS == "none")
    librelane_diodes_on_ports(
        name = name + "_dio_ports",
        input = input_target,
        src = pre_diode_src,
    )
    pre_dio_heur_src = ":" + name + "_dio_ports"

    # Step 42: Heuristic diode insertion (only if enabled)
    if run_heuristic_diode_insertion:
        librelane_heuristic_diode_insertion(
            name = name + "_dio_heur",
            input = input_target,
            src = pre_dio_heur_src,
        )
        pre_ant_src = ":" + name + "_dio_heur"
    else:
        pre_ant_src = pre_dio_heur_src

    # Step 43: Antenna repair (gated by run_antenna_repair, default True)
    if run_antenna_repair:
        librelane_repair_antennas(
            name = name + "_ant",
            input = input_target,
            src = pre_ant_src,
        )
        post_ant_src = ":" + name + "_ant"
    else:
        post_ant_src = pre_ant_src

    # Step 44: Final timing optimization after global routing (gated, default OFF)
    if run_post_grt_resizer_timing:
        librelane_resizer_timing_post_grt(
            name = name + "_rsz_grt2",
            input = input_target,
            src = post_ant_src,
        )
        post_rsz_grt_src = ":" + name + "_rsz_grt2"
    else:
        post_rsz_grt_src = post_ant_src

    # Step 45: STA mid-PnR (after resizer timing post-GRT)
    librelane_sta_mid_pnr(
        name = name + "_sta_mid_rsz_grt",
        input = input_target,
        src = post_rsz_grt_src,
    )

    # Step 46: Detailed routing (gated by run_drt, default True)
    if run_drt:
        librelane_detailed_routing(
            name = name + "_drt",
            input = input_target,
            src = ":" + name + "_sta_mid_rsz_grt",
        )
        pre_rm_obs_src = ":" + name + "_drt"
    else:
        pre_rm_obs_src = ":" + name + "_sta_mid_rsz_grt"

    # Step 47: Remove routing obstructions (self-skips when unset)
    librelane_remove_routing_obstructions(
        name = name + "_rm_route_obs",
        input = input_target,
        src = pre_rm_obs_src,
    )
    post_drt_src = ":" + name + "_rm_route_obs"

    # Step 48: Check antennas (second occurrence, after DRT)
    librelane_check_antennas(
        name = name + "_chk_ant_drt",
        input = input_target,
        src = post_drt_src,
    )

    # Step 49: Check routing DRC
    librelane_tr_drc(
        name = name + "_chk_tr_drc",
        input = input_target,
        src = ":" + name + "_chk_ant_drt",
    )

    # Step 50: Report disconnected pins
    librelane_report_disconnected_pins(
        name = name + "_rpt_disc_pins",
        input = input_target,
        src = ":" + name + "_chk_tr_drc",
    )

    # Step 51: Check disconnected pins
    librelane_disconnected_pins(
        name = name + "_chk_disc_pins",
        input = input_target,
        src = ":" + name + "_rpt_disc_pins",
    )

    # Step 52: Report wire length
    librelane_report_wire_length(
        name = name + "_rpt_wire_len",
        input = input_target,
        src = ":" + name + "_chk_disc_pins",
    )

    # Step 53: Check wire length
    librelane_wire_length(
        name = name + "_chk_wire_len",
        input = input_target,
        src = ":" + name + "_rpt_wire_len",
    )

    # Step 54: Fill insertion (gated, default ON)
    if run_fill_insertion:
        librelane_fill(
            name = name + "_fill",
            input = input_target,
            src = ":" + name + "_chk_wire_len",
        )
        post_fill_src = ":" + name + "_fill"
    else:
        post_fill_src = ":" + name + "_chk_wire_len"

    # Step 55: Cell frequency tables
    librelane_cell_frequency_tables(
        name = name + "_cell_freq",
        input = input_target,
        src = post_fill_src,
    )

    # Step 56: Parasitic extraction (gated, default ON)
    if run_spef_extraction:
        librelane_rcx(
            name = name + "_rcx",
            input = input_target,
            src = ":" + name + "_cell_freq",
        )
        pre_sta_post_pnr_src = ":" + name + "_rcx"
    else:
        pre_sta_post_pnr_src = ":" + name + "_cell_freq"

    # Step 57: Final STA (gated, default ON)
    if run_mcsta:
        librelane_sta_post_pnr(
            name = name + "_sta",
            input = input_target,
            src = pre_sta_post_pnr_src,
        )
        pre_ir_drop_src = ":" + name + "_sta"
    else:
        pre_ir_drop_src = pre_sta_post_pnr_src

    # Step 58: IR drop report (gated, default ON)
    if run_irdrop_report:
        librelane_ir_drop_report(
            name = name + "_ir_drop",
            input = input_target,
            src = pre_ir_drop_src,
        )
        pre_gds_src = ":" + name + "_ir_drop"
    else:
        pre_gds_src = pre_ir_drop_src

    # Step 59: GDS stream out (Magic, gated, default ON)
    if run_magic_streamout:
        librelane_gds(
            name = name + "_gds",
            input = input_target,
            src = pre_gds_src,
        )
        pre_klayout_gds_src = ":" + name + "_gds"
    else:
        pre_klayout_gds_src = pre_gds_src

    # Step 60: GDS stream out (KLayout, gated, default ON)
    if run_klayout_streamout:
        librelane_klayout_stream_out(
            name = name + "_klayout_gds",
            input = input_target,
            src = pre_klayout_gds_src,
        )
        pre_lef_src = ":" + name + "_klayout_gds"
    else:
        pre_lef_src = pre_klayout_gds_src

    # Step 61: LEF generation (Magic, gated, default ON)
    if run_magic_write_lef:
        librelane_lef(
            name = name + "_lef",
            input = input_target,
            src = pre_lef_src,
        )
        pre_ant_prop_src = ":" + name + "_lef"
    else:
        pre_ant_prop_src = pre_lef_src

    # Step 62: Check design antenna properties
    librelane_check_design_antenna_properties(
        name = name + "_chk_ant_prop",
        input = input_target,
        src = pre_ant_prop_src,
    )

    # Steps 63-64: KLayout XOR and checker (gated, default ON)
    if run_klayout_xor and run_magic_streamout and run_klayout_streamout:
        librelane_klayout_xor(
            name = name + "_xor",
            input = input_target,
            src = ":" + name + "_chk_ant_prop",
        )
        librelane_xor(
            name = name + "_chk_xor",
            input = input_target,
            src = ":" + name + "_xor",
        )
        pre_magic_drc_src = ":" + name + "_chk_xor"
    else:
        pre_magic_drc_src = ":" + name + "_chk_ant_prop"

    # Step 65: Magic DRC (gated by signoff config, default ON)
    if run_magic_drc:
        librelane_magic_drc(
            name = name + "_magic_drc",
            input = input_target,
            src = pre_magic_drc_src,
        )
        pre_klayout_drc_src = ":" + name + "_magic_drc"
    else:
        pre_klayout_drc_src = pre_magic_drc_src

    # Step 66: KLayout DRC (gated, default ON)
    if run_klayout_drc:
        librelane_klayout_drc(
            name = name + "_klayout_drc",
            input = input_target,
            src = pre_klayout_drc_src,
        )
        pre_magic_drc_check_src = ":" + name + "_klayout_drc"
    else:
        pre_magic_drc_check_src = pre_klayout_drc_src

    # Step 67: Check Magic DRC (same gate as Magic DRC)
    if run_magic_drc:
        librelane_magic_drc_checker(
            name = name + "_chk_magic_drc",
            input = input_target,
            src = pre_magic_drc_check_src,
        )
        pre_klayout_drc_check_src = ":" + name + "_chk_magic_drc"
    else:
        pre_klayout_drc_check_src = pre_magic_drc_check_src

    # Step 68: Check KLayout DRC (same gate as KLayout DRC)
    if run_klayout_drc:
        librelane_klayout_drc_checker(
            name = name + "_chk_klayout_drc",
            input = input_target,
            src = pre_klayout_drc_check_src,
        )
        pre_spice_src = ":" + name + "_chk_klayout_drc"
    else:
        pre_spice_src = pre_klayout_drc_check_src

    # Step 69: SPICE extraction
    librelane_spice_extraction(
        name = name + "_spice",
        input = input_target,
        src = pre_spice_src,
    )

    # Step 70: Check illegal overlaps
    librelane_illegal_overlap(
        name = name + "_chk_overlap",
        input = input_target,
        src = ":" + name + "_spice",
    )

    # Steps 71-72: Netgen LVS and checker (gated, default ON)
    if run_lvs:
        librelane_netgen_lvs(
            name = name + "_lvs",
            input = input_target,
            src = ":" + name + "_chk_overlap",
        )
        librelane_lvs_checker(
            name = name + "_chk_lvs",
            input = input_target,
            src = ":" + name + "_lvs",
        )
        pre_eqy_src = ":" + name + "_chk_lvs"
    else:
        pre_eqy_src = ":" + name + "_chk_overlap"

    # Step 73: Yosys EQY (formal equivalence check, gated by run_eqy)
    if run_eqy:
        librelane_eqy(
            name = name + "_eqy",
            input = input_target,
            src = pre_eqy_src,
        )
        post_eqy_src = ":" + name + "_eqy"
    else:
        post_eqy_src = pre_eqy_src

    # Step 74: Check setup violations
    librelane_setup_violations(
        name = name + "_chk_setup",
        input = input_target,
        src = post_eqy_src,
    )

    # Step 75: Check hold violations
    librelane_hold_violations(
        name = name + "_chk_hold",
        input = input_target,
        src = ":" + name + "_chk_setup",
    )

    # Step 76: Check max slew violations
    librelane_max_slew_violations(
        name = name + "_chk_slew",
        input = input_target,
        src = ":" + name + "_chk_hold",
    )

    # Step 77.5: Check antenna violations (local Zamlet checker, not LibreLane)
    zamlet_antenna_violations(
        name = name + "_zamlet_chk_ant",
        input = input_target,
        src = ":" + name + "_chk_slew",
    )

    # Step 77: Check max cap violations
    librelane_max_cap_violations(
        name = name + "_chk_cap",
        input = input_target,
        src = ":" + name + "_zamlet_chk_ant",
    )

    # Step 78: Report manufacturability
    librelane_report_manufacturability(
        name = name + "_mfg_report",
        input = input_target,
        src = ":" + name + "_chk_cap",
    )
