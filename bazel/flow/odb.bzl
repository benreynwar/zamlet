# Odb (OpenDB) manipulation rules

load(":common.bzl", "single_step_impl", "FLOW_ATTRS", "BASE_CONFIG_KEYS", "OPENROAD_STEP_CONFIG_KEYS")
load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo")

# OdbpyStep loads LEFs before running its Python command. Include flow-level
# optional LEF sources that affect the OpenDB view.
ODB_CONFIG_KEYS = BASE_CONFIG_KEYS + [
    "MACROS",
    "EXTRA_LEFS",
]

# Step 50: Odb.ReportDisconnectedPins - odb.py lines 497-535
# IGNORE_DISCONNECTED_MODULES is a PDK variable (pdk=True)
REPORT_DISCONNECTED_PINS_CONFIG_KEYS = ODB_CONFIG_KEYS + ["IGNORE_DISCONNECTED_MODULES"]

# Odb.ManualGlobalPlacement inherits OdbpyStep LEF loading and needs MANUAL_GLOBAL_PLACEMENTS.
MANUAL_GLOBAL_PLACEMENT_CONFIG_KEYS = ODB_CONFIG_KEYS + ["MANUAL_GLOBAL_PLACEMENTS"]

# Odb.AddPDNObstructions / Odb.RemovePDNObstructions need PDN_OBSTRUCTIONS.
PDN_OBS_CONFIG_KEYS = ODB_CONFIG_KEYS + ["PDN_OBSTRUCTIONS"]

# Odb.AddRoutingObstructions / Odb.RemoveRoutingObstructions need ROUTING_OBSTRUCTIONS
ROUTING_OBS_CONFIG_KEYS = ODB_CONFIG_KEYS + ["ROUTING_OBSTRUCTIONS"]

# Odb.WriteVerilogHeader inherits OdbpyStep LEF loading and needs VERILOG_POWER_DEFINE.
WRITE_VH_CONFIG_KEYS = ODB_CONFIG_KEYS + ["VERILOG_POWER_DEFINE"]

# Odb.DiodesOnPorts is a CompositeStep containing:
#   PortDiodePlacement (OdbpyStep) + DetailedPlacement + GlobalRouting
# Needs union of all sub-step config_vars (odb.py:788-818)
DIODES_ON_PORTS_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    # PortDiodePlacement config_vars (odb.py:738-752)
    "DIODE_ON_PORTS",
    "GPL_CELL_PADDING",
    # grt_variables (common_variables.py:285-319) - for GlobalRouting
    "RT_CLOCK_MIN_LAYER",
    "RT_CLOCK_MAX_LAYER",
    "GRT_ADJUSTMENT",
    "GRT_MACRO_EXTENSION",
    "GRT_LAYER_ADJUSTMENTS",
    "DIODE_PADDING",
    "GRT_ALLOW_CONGESTION",
    "GRT_ANTENNA_REPAIR_ITERS",
    "GRT_OVERFLOW_ITERS",
    "GRT_ANTENNA_REPAIR_MARGIN",
    "GRT_ANTENNA_REPAIR_JUMPER_ONLY",
    "GRT_ANTENNA_REPAIR_DIODE_ONLY",
    # dpl_variables (common_variables.py:255-283) - for DetailedPlacement, GlobalRouting
    "PL_OPTIMIZE_MIRRORING",
    "PL_MAX_DISPLACEMENT_X",
    "PL_MAX_DISPLACEMENT_Y",
    "DPL_CELL_PADDING",
]

# Odb.HeuristicDiodeInsertion is a CompositeStep containing:
#   FuzzyDiodePlacement (OdbpyStep) + DetailedPlacement + GlobalRouting
# Needs union of all sub-step config_vars (odb.py:891-919)
HEURISTIC_DIODE_CONFIG_KEYS = OPENROAD_STEP_CONFIG_KEYS + [
    # FuzzyDiodePlacement config_vars (odb.py:840-855)
    "HEURISTIC_ANTENNA_THRESHOLD",
    "GPL_CELL_PADDING",
    # grt_variables (common_variables.py:285-319) - for GlobalRouting
    "RT_CLOCK_MIN_LAYER",
    "RT_CLOCK_MAX_LAYER",
    "GRT_ADJUSTMENT",
    "GRT_MACRO_EXTENSION",
    "GRT_LAYER_ADJUSTMENTS",
    "DIODE_PADDING",
    "GRT_ALLOW_CONGESTION",
    "GRT_ANTENNA_REPAIR_ITERS",
    "GRT_OVERFLOW_ITERS",
    "GRT_ANTENNA_REPAIR_MARGIN",
    "GRT_ANTENNA_REPAIR_JUMPER_ONLY",
    "GRT_ANTENNA_REPAIR_DIODE_ONLY",
    # dpl_variables (common_variables.py:255-283) - for DetailedPlacement, GlobalRouting
    "PL_OPTIMIZE_MIRRORING",
    "PL_MAX_DISPLACEMENT_X",
    "PL_MAX_DISPLACEMENT_Y",
    "DPL_CELL_PADDING",
]

def _check_macro_antenna_properties_impl(ctx):
    return single_step_impl(ctx, "Odb.CheckMacroAntennaProperties", ODB_CONFIG_KEYS, step_outputs = [])

def _set_power_connections_impl(ctx):
    return single_step_impl(ctx, "Odb.SetPowerConnections", ODB_CONFIG_KEYS, step_outputs = ["def", "odb"])

def _manual_macro_placement_impl(ctx):
    return single_step_impl(ctx, "Odb.ManualMacroPlacement", ODB_CONFIG_KEYS, step_outputs = ["def", "odb"])

def _add_pdn_obstructions_impl(ctx):
    input_info = ctx.attr.input[LibrelaneInput]
    step_outputs = ["def", "odb"] if input_info.pdn_obstructions else []
    return single_step_impl(ctx, "Odb.AddPDNObstructions", PDN_OBS_CONFIG_KEYS, step_outputs = step_outputs)

def _remove_pdn_obstructions_impl(ctx):
    input_info = ctx.attr.input[LibrelaneInput]
    step_outputs = ["def", "odb"] if input_info.pdn_obstructions else []
    return single_step_impl(ctx, "Odb.RemovePDNObstructions", PDN_OBS_CONFIG_KEYS, step_outputs = step_outputs)

def _add_routing_obstructions_impl(ctx):
    input_info = ctx.attr.input[LibrelaneInput]
    step_outputs = ["def", "odb"] if input_info.routing_obstructions else []
    return single_step_impl(ctx, "Odb.AddRoutingObstructions", ROUTING_OBS_CONFIG_KEYS,
        step_outputs = step_outputs)

def _custom_io_placement_impl(ctx):
    return single_step_impl(ctx, "Odb.CustomIOPlacement", ODB_CONFIG_KEYS, step_outputs = ["def", "odb"])

def _apply_def_template_impl(ctx):
    return single_step_impl(ctx, "Odb.ApplyDEFTemplate", ODB_CONFIG_KEYS, step_outputs = ["def", "odb"])

def _write_verilog_header_impl(ctx):
    return single_step_impl(ctx, "Odb.WriteVerilogHeader", WRITE_VH_CONFIG_KEYS, step_outputs = ["vh"])

def _manual_global_placement_impl(ctx):
    input_info = ctx.attr.input[LibrelaneInput]
    step_outputs = ["def", "odb"] if input_info.manual_global_placements else []
    return single_step_impl(ctx, "Odb.ManualGlobalPlacement", MANUAL_GLOBAL_PLACEMENT_CONFIG_KEYS,
        step_outputs = step_outputs)

def _diodes_on_ports_impl(ctx):
    input_info = ctx.attr.input[LibrelaneInput]
    step_outputs = ["def", "odb"] if input_info.diode_on_ports != "none" else []
    return single_step_impl(ctx, "Odb.DiodesOnPorts", DIODES_ON_PORTS_CONFIG_KEYS,
        step_outputs = step_outputs)

def _heuristic_diode_insertion_impl(ctx):
    return single_step_impl(ctx, "Odb.HeuristicDiodeInsertion", HEURISTIC_DIODE_CONFIG_KEYS, step_outputs = ["def", "odb"])

def _remove_routing_obstructions_impl(ctx):
    input_info = ctx.attr.input[LibrelaneInput]
    step_outputs = ["def", "odb"] if input_info.routing_obstructions else []
    return single_step_impl(ctx, "Odb.RemoveRoutingObstructions", ROUTING_OBS_CONFIG_KEYS,
        step_outputs = step_outputs)

def _report_disconnected_pins_impl(ctx):
    return single_step_impl(ctx, "Odb.ReportDisconnectedPins", REPORT_DISCONNECTED_PINS_CONFIG_KEYS,
        step_outputs = [], optional_extra_outputs = ["full_disconnected_pins_table.txt"])

def _report_wire_length_impl(ctx):
    return single_step_impl(ctx, "Odb.ReportWireLength", ODB_CONFIG_KEYS,
        step_outputs = [], extra_outputs = ["wire_lengths.csv"])

def _cell_frequency_tables_impl(ctx):
    return single_step_impl(ctx, "Odb.CellFrequencyTables", ODB_CONFIG_KEYS,
        step_outputs = [],
        extra_outputs = ["cell.rpt", "cell_function.rpt", "by_scl.rpt", "buffers.rpt"])

def _check_design_antenna_properties_impl(ctx):
    return single_step_impl(ctx, "Odb.CheckDesignAntennaProperties", ODB_CONFIG_KEYS,
        step_outputs = [], extra_outputs = ["report.yaml"])

# Rule declarations
librelane_check_macro_antenna_properties = rule(
    implementation = _check_macro_antenna_properties_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_set_power_connections = rule(
    implementation = _set_power_connections_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_manual_macro_placement = rule(
    implementation = _manual_macro_placement_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_add_pdn_obstructions = rule(
    implementation = _add_pdn_obstructions_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_remove_pdn_obstructions = rule(
    implementation = _remove_pdn_obstructions_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_add_routing_obstructions = rule(
    implementation = _add_routing_obstructions_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_custom_io_placement = rule(
    implementation = _custom_io_placement_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_apply_def_template = rule(
    implementation = _apply_def_template_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_write_verilog_header = rule(
    implementation = _write_verilog_header_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_manual_global_placement = rule(
    implementation = _manual_global_placement_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

# DIODE_ON_PORTS now comes from input via 5-location pattern, not rule attr
librelane_diodes_on_ports = rule(
    implementation = _diodes_on_ports_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_heuristic_diode_insertion = rule(
    implementation = _heuristic_diode_insertion_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_remove_routing_obstructions = rule(
    implementation = _remove_routing_obstructions_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_report_disconnected_pins = rule(
    implementation = _report_disconnected_pins_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_report_wire_length = rule(
    implementation = _report_wire_length_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_cell_frequency_tables = rule(
    implementation = _cell_frequency_tables_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_check_design_antenna_properties = rule(
    implementation = _check_design_antenna_properties_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)
