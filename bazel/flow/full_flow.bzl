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
)
load(":synthesis.bzl", "librelane_synthesis", "librelane_json_header", "librelane_eqy")
load(":floorplan.bzl", "librelane_floorplan")
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
    core_utilization = "50",
    pl_target_density_pct = "",
    die_area = None,
    macros = [],
    pin_order_cfg = None,
    def_template = None,
    macro_placement_cfg = None,
    cts_clk_max_wire_length = None,
    run_cts = True,
    run_post_cts_resizer_timing = True,
    run_linter = True,
    run_tap_endcap_insertion = True,
    run_post_gpl_design_repair = True,
    run_post_grt_design_repair = False,
    pdn_obstructions = None,
    routing_obstructions = None,
    diode_on_ports = "none",
    run_heuristic_diode_insertion = False,
    run_antenna_repair = True,
    run_post_grt_resizer_timing = False,
    run_drt = True,
    manual_global_placements = None,
    pnr_sdc_file = None,
    signoff_sdc_file = None,
    input_delay_constraint = None,
    output_delay_constraint = None):
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
        core_utilization: Target core utilization (0-100), ignored if die_area specified
        pl_target_density_pct: Target placement density percentage (0-100), empty for dynamic
        die_area: Explicit die area as "x0 y0 x1 y1" in microns
        macros: List of hard macro targets (for hierarchical designs)
        pin_order_cfg: Pin order configuration file for custom IO placement
        def_template: DEF template file with die area and pin placements (alternative to pin_order_cfg)
        macro_placement_cfg: Macro placement configuration file (instance X Y orientation)
        cts_clk_max_wire_length: Max clock wire length in µm before buffer insertion (0=disabled)
        run_cts: Enable clock tree synthesis (default True)
        run_post_cts_resizer_timing: Enable timing optimization after CTS (default True, ignored if run_cts=False)
        run_linter: Enable Verilator linting (default True)
        run_tap_endcap_insertion: Enable tap/endcap insertion (default True)
        run_post_gpl_design_repair: Enable design repair after global placement (default True)
        run_post_grt_design_repair: Enable design repair after global routing (default False, experimental)
    """

    # Generate templated SDC if delay constraints provided
    effective_pnr_sdc = pnr_sdc_file
    effective_signoff_sdc = signoff_sdc_file
    if input_delay_constraint or output_delay_constraint:
        sdc_template(
            name = name + "_sdc",
            template = "//bazel/flow/sdc:base.sdc",
            input_delay_constraint = input_delay_constraint if input_delay_constraint else "50",
            output_delay_constraint = output_delay_constraint if output_delay_constraint else "50",
        )
        if not pnr_sdc_file:
            effective_pnr_sdc = ":" + name + "_sdc"
        if not signoff_sdc_file:
            effective_signoff_sdc = ":" + name + "_sdc"

    # PnR config - create if any PnR params are non-default
    pnr_config_kwargs = {}
    if pl_target_density_pct:
        pnr_config_kwargs["pl_target_density_pct"] = pl_target_density_pct
    if pin_order_cfg:
        pnr_config_kwargs["fp_pin_order_cfg"] = pin_order_cfg
    if def_template:
        pnr_config_kwargs["fp_def_template"] = def_template
    if cts_clk_max_wire_length:
        pnr_config_kwargs["cts_clk_max_wire_length"] = cts_clk_max_wire_length
    if core_utilization != "50":
        pnr_config_kwargs["fp_core_util"] = core_utilization
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
            core_utilization = core_utilization,
        )

    # Post-floorplan checks and setup
    librelane_check_macro_antenna_properties(
        name = name + "_chk_macro_ant",
        input = input_target,
        src = ":" + name + "_floorplan",
    )
    librelane_set_power_connections(
        name = name + "_power_conn",
        input = input_target,
        src = ":" + name + "_chk_macro_ant",
    )

    # Manual macro placement (if configured)
    if macro_placement_cfg:
        librelane_manual_macro_placement(
            name = name + "_mpl",
            input = input_target,
            src = ":" + name + "_power_conn",
            macro_placement_cfg = macro_placement_cfg,
        )
        pre_cutrows_src = ":" + name + "_mpl"
    else:
        pre_cutrows_src = ":" + name + "_power_conn"

    # Cut rows (for macro placement clearance)
    librelane_cut_rows(
        name = name + "_cutrows",
        input = input_target,
        src = pre_cutrows_src,
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

    # PDN obstructions (added before PDN, removed after) - only if configured
    if pdn_obstructions:
        librelane_add_pdn_obstructions(
            name = name + "_add_pdn_obs",
            input = input_target,
            src = pre_pdn_src,
        )
        pre_pdn_gen_src = ":" + name + "_add_pdn_obs"
    else:
        pre_pdn_gen_src = pre_pdn_src

    # Power delivery network
    librelane_generate_pdn(
        name = name + "_pdn",
        input = input_target,
        src = pre_pdn_gen_src,
    )

    # Remove PDN obstructions - only if we added them
    if pdn_obstructions:
        librelane_remove_pdn_obstructions(
            name = name + "_rm_pdn_obs",
            input = input_target,
            src = ":" + name + "_pdn",
        )
        post_pdn_src = ":" + name + "_rm_pdn_obs"
    else:
        post_pdn_src = ":" + name + "_pdn"

    # Add routing obstructions (removed after detailed routing) - only if configured
    if routing_obstructions:
        librelane_add_routing_obstructions(
            name = name + "_add_route_obs",
            input = input_target,
            src = post_pdn_src,
        )
        pre_gpl_skip_io_src = ":" + name + "_add_route_obs"
    else:
        pre_gpl_skip_io_src = post_pdn_src

    # Global placement (skip IO) - initial placement before IO pins fixed
    librelane_global_placement_skip_io(
        name = name + "_gpl_skip_io",
        input = input_target,
        src = pre_gpl_skip_io_src,
    )

    # IO placement
    if def_template and pin_order_cfg:
        fail("Cannot specify both def_template and pin_order_cfg")

    if def_template:
        librelane_apply_def_template(
            name = name + "_io",
            input = input_target,
            src = ":" + name + "_gpl_skip_io",
        )
    elif pin_order_cfg:
        librelane_custom_io_placement(
            name = name + "_io",
            input = input_target,
            src = ":" + name + "_gpl_skip_io",
        )
    else:
        librelane_io_placement(
            name = name + "_io",
            input = input_target,
            src = ":" + name + "_gpl_skip_io",
        )

    # Global placement (full) - refine placement with IO pins fixed
    librelane_global_placement(
        name = name + "_gpl",
        input = input_target,
        src = ":" + name + "_io",
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

    # Step 32: Manual global placement (only if configured)
    # Config flows through LibrelaneInput (manual_global_placements attr)
    if manual_global_placements:
        librelane_manual_global_placement(
            name = name + "_mgpl",
            input = input_target,
            src = pre_mgpl_src,
        )
        pre_dpl_src = ":" + name + "_mgpl"
    else:
        pre_dpl_src = pre_mgpl_src

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

    # Step 41: Diodes on ports (only if configured, default "none" skips)
    # DIODE_ON_PORTS comes from input via 5-location pattern
    if diode_on_ports != "none":
        librelane_diodes_on_ports(
            name = name + "_dio_ports",
            input = input_target,
            src = pre_diode_src,
        )
        pre_dio_heur_src = ":" + name + "_dio_ports"
    else:
        pre_dio_heur_src = pre_diode_src

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

    # Step 47: Remove routing obstructions (only if we added them)
    if routing_obstructions:
        librelane_remove_routing_obstructions(
            name = name + "_rm_route_obs",
            input = input_target,
            src = pre_rm_obs_src,
        )
        post_drt_src = ":" + name + "_rm_route_obs"
    else:
        post_drt_src = pre_rm_obs_src

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

    # Step 54: Fill insertion
    librelane_fill(
        name = name + "_fill",
        input = input_target,
        src = ":" + name + "_chk_wire_len",
    )

    # Step 55: Cell frequency tables
    librelane_cell_frequency_tables(
        name = name + "_cell_freq",
        input = input_target,
        src = ":" + name + "_fill",
    )

    # Step 56: Parasitic extraction
    librelane_rcx(
        name = name + "_rcx",
        input = input_target,
        src = ":" + name + "_cell_freq",
    )

    # Step 57: Final STA
    librelane_sta_post_pnr(
        name = name + "_sta",
        input = input_target,
        src = ":" + name + "_rcx",
    )

    # Step 58: IR drop report
    librelane_ir_drop_report(
        name = name + "_ir_drop",
        input = input_target,
        src = ":" + name + "_sta",
    )

    # Step 59: GDS stream out (Magic)
    librelane_gds(
        name = name + "_gds",
        input = input_target,
        src = ":" + name + "_ir_drop",
    )

    # Step 60: GDS stream out (KLayout)
    librelane_klayout_stream_out(
        name = name + "_klayout_gds",
        input = input_target,
        src = ":" + name + "_gds",
    )

    # Step 61: LEF generation (Magic)
    librelane_lef(
        name = name + "_lef",
        input = input_target,
        src = ":" + name + "_klayout_gds",
    )

    # Step 62: Check design antenna properties
    librelane_check_design_antenna_properties(
        name = name + "_chk_ant_prop",
        input = input_target,
        src = ":" + name + "_lef",
    )

    # Step 63: KLayout XOR (Magic vs KLayout)
    librelane_klayout_xor(
        name = name + "_xor",
        input = input_target,
        src = ":" + name + "_chk_ant_prop",
    )

    # Step 64: Check XOR differences
    librelane_xor(
        name = name + "_chk_xor",
        input = input_target,
        src = ":" + name + "_xor",
    )

    # Step 65: Magic DRC
    librelane_magic_drc(
        name = name + "_magic_drc",
        input = input_target,
        src = ":" + name + "_chk_xor",
    )

    # Step 66: KLayout DRC
    librelane_klayout_drc(
        name = name + "_klayout_drc",
        input = input_target,
        src = ":" + name + "_magic_drc",
    )

    # Step 67: Check Magic DRC
    librelane_magic_drc_checker(
        name = name + "_chk_magic_drc",
        input = input_target,
        src = ":" + name + "_klayout_drc",
    )

    # Step 68: Check KLayout DRC
    librelane_klayout_drc_checker(
        name = name + "_chk_klayout_drc",
        input = input_target,
        src = ":" + name + "_chk_magic_drc",
    )

    # Step 69: SPICE extraction
    librelane_spice_extraction(
        name = name + "_spice",
        input = input_target,
        src = ":" + name + "_chk_klayout_drc",
    )

    # Step 70: Check illegal overlaps
    librelane_illegal_overlap(
        name = name + "_chk_overlap",
        input = input_target,
        src = ":" + name + "_spice",
    )

    # Step 71: Netgen LVS
    librelane_netgen_lvs(
        name = name + "_lvs",
        input = input_target,
        src = ":" + name + "_chk_overlap",
    )

    # Step 72: Check LVS
    librelane_lvs_checker(
        name = name + "_chk_lvs",
        input = input_target,
        src = ":" + name + "_lvs",
    )

    # Step 73: Yosys EQY (formal equivalence check)
    librelane_eqy(
        name = name + "_eqy",
        input = input_target,
        src = ":" + name + "_chk_lvs",
    )

    # Step 74: Check setup violations
    librelane_setup_violations(
        name = name + "_chk_setup",
        input = input_target,
        src = ":" + name + "_eqy",
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

    # Step 77: Check max cap violations
    librelane_max_cap_violations(
        name = name + "_chk_cap",
        input = input_target,
        src = ":" + name + "_chk_slew",
    )

    # Step 78: Report manufacturability
    librelane_report_manufacturability(
        name = name + "_mfg_report",
        input = input_target,
        src = ":" + name + "_chk_cap",
    )


