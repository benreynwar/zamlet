# Static Timing Analysis rules

load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo")
load("//bazel:power_activity.bzl", "PowerActivityInfo", "PowerReportInfo")
load(":common.bzl",
    "single_step_impl",
    "FLOW_ATTRS",
    "BASE_CONFIG_KEYS",
    "OPENROAD_STEP_CONFIG_KEYS",
    "create_librelane_config",
    "run_librelane_step",
    "get_input_files",
)

# Config keys for OpenROAD.CheckSDCFiles (Step 10)
# Inherits from Step (no config_vars from parent)
# config_vars: PNR_SDC_FILE, SIGNOFF_SDC_FILE
CHECK_SDC_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "PNR_SDC_FILE",
    "SIGNOFF_SDC_FILE",
]

# Config keys for OpenROAD.CheckMacroInstances (Step 11)
# Inherits from OpenSTAStep -> OpenROADStep
# Uses MACROS in run() - librelane/steps/openroad.py line 511
CHECK_MACRO_INSTANCES_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    "MACROS",
]

# Config keys for MultiCornerSTA-based steps (STAPrePNR)
# From librelane/steps/openroad.py MultiCornerSTA.config_vars (lines 534-556)
MULTI_CORNER_STA_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    "STA_MACRO_PRIORITIZE_NL",
    "STA_MAX_VIOLATOR_COUNT",
    "STA_THREADS",
    # STA_CORNERS and DESIGN_NAME are in BASE_CONFIG_KEYS
]

# Step 57: OpenROAD.STAPostPNR - openroad.py lines 760-859
# Inherits from STAPrePNR -> MultiCornerSTA, adds SIGNOFF_SDC_FILE (line 776-780)
STA_POST_PNR_CONFIG_KEYS = MULTI_CORNER_STA_CONFIG_KEYS + [
    "SIGNOFF_SDC_FILE",
]

# Mid-PnR multi-corner STA uses a local LibreLane plugin that runs OpenROAD's
# database-backed STA script through LibreLane's MultiCornerSTA report handling.
STA_MID_PNR_CONFIG_KEYS = MULTI_CORNER_STA_CONFIG_KEYS

# Step 58: OpenROAD.IRDropReport - openroad.py lines 1799-1878
# Inherits from OpenROADStep, adds VSRC_LOC_FILES (line 1814-1818)
IRDROP_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    "VSRC_LOC_FILES",
]

# Step 56: OpenROAD.RCX - openroad.py lines 1668-1708
RCX_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    "RCX_MERGE_VIA_WIRE_RES",
    "RCX_SDC_FILE",
    "RCX_RULESETS",
    "STA_THREADS",
]

def _check_sdc_files_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.CheckSDCFiles", CHECK_SDC_CONFIG_KEYS, step_outputs = [])

def _check_macro_instances_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.CheckMacroInstances", CHECK_MACRO_INSTANCES_CONFIG_KEYS, step_outputs = [])

def _multi_corner_sta_reports(corners):
    """Build report path list for multi-corner STA steps."""
    reports = ["summary.rpt"]
    corner_reports = [
        "max.rpt",
        "min.rpt",
        "checks.rpt",
        "power.rpt",
        "skew.min.rpt",
        "skew.max.rpt",
        "ws.min.rpt",
        "ws.max.rpt",
        "tns.min.rpt",
        "tns.max.rpt",
        "wns.min.rpt",
        "wns.max.rpt",
        "violator_list.rpt",
        "unpropagated.rpt",
        "clock.rpt",
    ]
    for corner in corners:
        for report in corner_reports:
            reports.append(corner + "/" + report)
    return reports

def _sta_pre_pnr_impl(ctx):
    """Pre-PnR timing analysis with timing reports."""
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]
    top = input_info.top
    nom_corners = [c for c in input_info.pdk_info.sta_corners if c.startswith("nom_")]

    sdf_outputs = {}
    outputs = []
    for corner in nom_corners:
        sdf = ctx.actions.declare_file(ctx.label.name + "/" + corner + "/" + top + "__" + corner + ".sdf")
        sdf_outputs[corner] = sdf
        outputs.append(sdf)

    report_outputs = []
    for path in _multi_corner_sta_reports(nom_corners):
        report_outputs.append(ctx.actions.declare_file(ctx.label.name + "/" + path))

    inputs = get_input_files(input_info, state_info, MULTI_CORNER_STA_CONFIG_KEYS)
    config = create_librelane_config(input_info, state_info, MULTI_CORNER_STA_CONFIG_KEYS)

    state_out = run_librelane_step(
        ctx = ctx,
        step_id = "OpenROAD.STAPrePNR",
        outputs = outputs + report_outputs,
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
    )

    return [
        DefaultInfo(files = depset(outputs + report_outputs + [state_out])),
        LibrelaneInfo(
            state_out = state_out,
            nl = state_info.nl,
            pnl = state_info.pnl,
            odb = state_info.odb,
            sdc = state_info.sdc,
            sdf = sdf_outputs,
            spef = state_info.spef,
            lib = state_info.lib,
            gds = state_info.gds,
            mag_gds = state_info.mag_gds,
            klayout_gds = state_info.klayout_gds,
            lef = state_info.lef,
            mag = state_info.mag,
            spice = state_info.spice,
            json_h = state_info.json_h,
            vh = state_info.vh,
            **{"def": getattr(state_info, "def", None)}
        ),
    ]

def _sta_mid_pnr_impl(ctx):
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]

    report_outputs = []
    for path in _multi_corner_sta_reports(input_info.pdk_info.sta_corners):
        report_outputs.append(ctx.actions.declare_file(ctx.label.name + "/" + path))

    plugin_files = ctx.files._zamlet_librelane_plugin_files
    inputs = get_input_files(input_info, state_info, STA_MID_PNR_CONFIG_KEYS)
    config = create_librelane_config(input_info, state_info, STA_MID_PNR_CONFIG_KEYS)

    state_out = run_librelane_step(
        ctx = ctx,
        step_id = "Zamlet.STAMidPNRMultiCorner",
        outputs = report_outputs,
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
        plugin_files = plugin_files,
    )

    return [
        DefaultInfo(files = depset(report_outputs + [state_out])),
        LibrelaneInfo(
            state_out = state_out,
            nl = state_info.nl,
            pnl = state_info.pnl,
            odb = state_info.odb,
            sdc = state_info.sdc,
            sdf = state_info.sdf,
            spef = state_info.spef,
            lib = state_info.lib,
            gds = state_info.gds,
            mag_gds = state_info.mag_gds,
            klayout_gds = state_info.klayout_gds,
            lef = state_info.lef,
            mag = state_info.mag,
            spice = state_info.spice,
            json_h = state_info.json_h,
            vh = state_info.vh,
            **{"def": getattr(state_info, "def", None)}
        ),
    ]

def _rcx_impl(ctx):
    """Parasitic extraction - produces SPEF for all corners (passes through def/odb)."""
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]
    top = input_info.top

    # RCX produces SPEF for each corner (nom, min, max)
    spef_nom = ctx.actions.declare_file(ctx.label.name + "/nom/" + top + ".nom.spef")
    spef_min = ctx.actions.declare_file(ctx.label.name + "/min/" + top + ".min.spef")
    spef_max = ctx.actions.declare_file(ctx.label.name + "/max/" + top + ".max.spef")

    # Get input files
    inputs = get_input_files(input_info, state_info, RCX_CONFIG_KEYS)

    # Create config
    config = create_librelane_config(input_info, state_info, RCX_CONFIG_KEYS)

    # Run RCX
    state_out = run_librelane_step(
        ctx = ctx,
        step_id = "OpenROAD.RCX",
        outputs = [spef_nom, spef_min, spef_max],
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
    )

    return [
        DefaultInfo(files = depset([spef_nom, spef_min, spef_max])),
        LibrelaneInfo(
            state_out = state_out,
            nl = state_info.nl,
            pnl = state_info.pnl,
            odb = state_info.odb,
            sdc = state_info.sdc,
            sdf = state_info.sdf,
            spef = {"nom_*": spef_nom, "min_*": spef_min, "max_*": spef_max},
            lib = state_info.lib,
            gds = state_info.gds,
            mag_gds = state_info.mag_gds,
            klayout_gds = state_info.klayout_gds,
            lef = state_info.lef,
            mag = state_info.mag,
            spice = state_info.spice,
            json_h = state_info.json_h,
            vh = state_info.vh,
            **{"def": getattr(state_info, "def", None)}
        ),
    ]

def _sta_post_pnr_impl(ctx):
    """Post-PnR timing analysis with timing reports."""
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]
    top = input_info.top

    lib_outputs = {}
    sdf_outputs = {}
    outputs = []
    for corner in input_info.pdk_info.sta_corners:
        lib = ctx.actions.declare_file(ctx.label.name + "/" + corner + "/" + top + "__" + corner + ".lib")
        sdf = ctx.actions.declare_file(ctx.label.name + "/" + corner + "/" + top + "__" + corner + ".sdf")
        lib_outputs[corner] = lib
        sdf_outputs[corner] = sdf
        outputs.extend([lib, sdf])

    report_outputs = []
    for path in _multi_corner_sta_reports(input_info.pdk_info.sta_corners):
        report_outputs.append(ctx.actions.declare_file(ctx.label.name + "/" + path))

    inputs = get_input_files(input_info, state_info, STA_POST_PNR_CONFIG_KEYS)
    config = create_librelane_config(input_info, state_info, STA_POST_PNR_CONFIG_KEYS)

    state_out = run_librelane_step(
        ctx = ctx,
        step_id = "OpenROAD.STAPostPNR",
        outputs = outputs + report_outputs,
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
    )

    return [
        DefaultInfo(files = depset(outputs + report_outputs + [state_out])),
        LibrelaneInfo(
            state_out = state_out,
            nl = state_info.nl,
            pnl = state_info.pnl,
            odb = state_info.odb,
            sdc = state_info.sdc,
            sdf = sdf_outputs,
            spef = state_info.spef,
            lib = lib_outputs,
            gds = state_info.gds,
            mag_gds = state_info.mag_gds,
            klayout_gds = state_info.klayout_gds,
            lef = state_info.lef,
            mag = state_info.mag,
            spice = state_info.spice,
            json_h = state_info.json_h,
            vh = state_info.vh,
            **{"def": getattr(state_info, "def", None)}
        ),
    ]

def _power_post_pnr_impl(ctx):
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]
    activity = ctx.attr.activity[PowerActivityInfo]

    activity_tcl = ctx.actions.declare_file(ctx.label.name + "/read_activity.tcl")
    ctx.actions.write(
        output = activity_tcl,
        content = "read_vcd -scope {{{}}} {{{}}}\n".format(
            ctx.attr.vcd_scope,
            activity.vcd.path,
        ) + """puts "%OL_CREATE_REPORT activity.rpt"
report_activity_annotation -report_annotated
puts "%OL_END_REPORT"
""",
    )

    reports_by_corner = {
        corner: ctx.actions.declare_file(ctx.label.name + "/" + corner + "/power.rpt")
        for corner in input_info.pdk_info.sta_corners
    }
    activity_reports = [
        ctx.actions.declare_file(ctx.label.name + "/" + corner + "/activity.rpt")
        for corner in input_info.pdk_info.sta_corners
    ]
    reports = reports_by_corner.values() + activity_reports
    inputs = get_input_files(input_info, state_info, STA_POST_PNR_CONFIG_KEYS)
    inputs.extend([activity.vcd, activity.window, activity_tcl])
    config = create_librelane_config(input_info, state_info, STA_POST_PNR_CONFIG_KEYS)
    config["STA_EXTRA_CORNER_TCL_FILE"] = activity_tcl.path

    state_out = run_librelane_step(
        ctx = ctx,
        step_id = "OpenROAD.STAPostPNR",
        outputs = reports,
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
    )
    activity_check = ctx.actions.declare_file(ctx.label.name + "/activity_check.txt")
    report_paths = " ".join(["\"{}\"".format(report.path) for report in activity_reports])
    ctx.actions.run_shell(
        inputs = activity_reports,
        outputs = [activity_check],
        command = """set -e
for report in {reports}; do
  annotated=$(sed -n 's/^vcd  *//p' "$report")
  unannotated=$(sed -n 's/^unannotated  *//p' "$report")
  test -n "$annotated"
  test "$annotated" -gt 0
  test "$unannotated" -eq 0
done
echo "All corners have complete VCD activity annotation." > "{output}"
""".format(reports = report_paths, output = activity_check.path),
        mnemonic = "CheckPowerActivityAnnotation",
    )
    return [
        DefaultInfo(files = depset(reports + [state_out, activity_check])),
        PowerReportInfo(reports = reports_by_corner, state_out = state_out),
    ]

def _ir_drop_report_impl(ctx):
    return single_step_impl(ctx, "OpenROAD.IRDropReport", IRDROP_CONFIG_KEYS,
        step_outputs = [], extra_outputs = ["irdrop.rpt"])

librelane_check_sdc_files = rule(
    implementation = _check_sdc_files_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_check_macro_instances = rule(
    implementation = _check_macro_instances_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_sta_pre_pnr = rule(
    implementation = _sta_pre_pnr_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_sta_mid_pnr = rule(
    implementation = _sta_mid_pnr_impl,
    attrs = dict(FLOW_ATTRS, _zamlet_librelane_plugin_files = attr.label_list(
        default = [
            Label("//bazel/flow:librelane_plugin_zamlet/__init__.py"),
            Label("//bazel/flow:librelane_plugin_zamlet/sta_mid_pnr.py"),
        ],
        allow_files = True,
    )),
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_rcx = rule(
    implementation = _rcx_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_sta_post_pnr = rule(
    implementation = _sta_post_pnr_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_power_post_pnr = rule(
    implementation = _power_post_pnr_impl,
    attrs = dict(
        FLOW_ATTRS,
        activity = attr.label(mandatory = True, providers = [PowerActivityInfo]),
        vcd_scope = attr.string(mandatory = True),
    ),
)

librelane_ir_drop_report = rule(
    implementation = _ir_drop_report_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
