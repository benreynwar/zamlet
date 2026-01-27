# Odb (OpenDB) manipulation rules

load(":common.bzl", "single_step_impl", "FLOW_ATTRS")
load(":providers.bzl", "LibrelaneInfo")

def _check_macro_antenna_properties_impl(ctx):
    return single_step_impl(ctx, "Odb.CheckMacroAntennaProperties", step_outputs = [])

def _set_power_connections_impl(ctx):
    return single_step_impl(ctx, "Odb.SetPowerConnections", step_outputs = ["def", "odb"])

def _manual_macro_placement_impl(ctx):
    return single_step_impl(ctx, "Odb.ManualMacroPlacement", step_outputs = ["def", "odb"])

def _add_pdn_obstructions_impl(ctx):
    extra_config = {"PDN_OBSTRUCTIONS": ctx.attr.pdn_obstructions}
    return single_step_impl(ctx, "Odb.AddPDNObstructions",
        step_outputs = ["def", "odb"], extra_config = extra_config)

def _remove_pdn_obstructions_impl(ctx):
    extra_config = {"PDN_OBSTRUCTIONS": ctx.attr.pdn_obstructions}
    return single_step_impl(ctx, "Odb.RemovePDNObstructions",
        step_outputs = ["def", "odb"], extra_config = extra_config)

def _add_routing_obstructions_impl(ctx):
    extra_config = {"ROUTING_OBSTRUCTIONS": ctx.attr.routing_obstructions}
    return single_step_impl(ctx, "Odb.AddRoutingObstructions",
        step_outputs = ["def", "odb"], extra_config = extra_config)

def _custom_io_placement_impl(ctx):
    return single_step_impl(ctx, "Odb.CustomIOPlacement", step_outputs = ["def", "odb"])

def _apply_def_template_impl(ctx):
    return single_step_impl(ctx, "Odb.ApplyDEFTemplate", step_outputs = ["def", "odb"])

def _write_verilog_header_impl(ctx):
    return single_step_impl(ctx, "Odb.WriteVerilogHeader", step_outputs = ["vh"])

def _manual_global_placement_impl(ctx):
    extra_config = {"MANUAL_GLOBAL_PLACEMENTS": ctx.attr.manual_global_placements}
    return single_step_impl(ctx, "Odb.ManualGlobalPlacement",
        step_outputs = ["def", "odb"], extra_config = extra_config)

def _diodes_on_ports_impl(ctx):
    extra_config = {"DIODE_ON_PORTS": ctx.attr.diode_on_ports}
    return single_step_impl(ctx, "Odb.DiodesOnPorts",
        step_outputs = ["def", "odb"], extra_config = extra_config)

def _heuristic_diode_insertion_impl(ctx):
    return single_step_impl(ctx, "Odb.HeuristicDiodeInsertion", step_outputs = ["def", "odb"])

def _remove_routing_obstructions_impl(ctx):
    extra_config = {"ROUTING_OBSTRUCTIONS": ctx.attr.routing_obstructions}
    return single_step_impl(ctx, "Odb.RemoveRoutingObstructions",
        step_outputs = ["def", "odb"], extra_config = extra_config)

def _report_disconnected_pins_impl(ctx):
    return single_step_impl(ctx, "Odb.ReportDisconnectedPins", step_outputs = [])

def _report_wire_length_impl(ctx):
    return single_step_impl(ctx, "Odb.ReportWireLength", step_outputs = [])

def _cell_frequency_tables_impl(ctx):
    return single_step_impl(ctx, "Odb.CellFrequencyTables", step_outputs = [])

def _check_design_antenna_properties_impl(ctx):
    return single_step_impl(ctx, "Odb.CheckDesignAntennaProperties", step_outputs = [])

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

_PDN_OBSTRUCTIONS_ATTRS = dict(FLOW_ATTRS)
_PDN_OBSTRUCTIONS_ATTRS["pdn_obstructions"] = attr.string_list(
    doc = "PDN obstructions: list of 'layer llx lly urx ury' strings",
    mandatory = True,
)

_ROUTING_OBSTRUCTIONS_ATTRS = dict(FLOW_ATTRS)
_ROUTING_OBSTRUCTIONS_ATTRS["routing_obstructions"] = attr.string_list(
    doc = "Routing obstructions: list of 'layer llx lly urx ury' strings",
    mandatory = True,
)

librelane_add_pdn_obstructions = rule(
    implementation = _add_pdn_obstructions_impl,
    attrs = _PDN_OBSTRUCTIONS_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_remove_pdn_obstructions = rule(
    implementation = _remove_pdn_obstructions_impl,
    attrs = _PDN_OBSTRUCTIONS_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_add_routing_obstructions = rule(
    implementation = _add_routing_obstructions_impl,
    attrs = _ROUTING_OBSTRUCTIONS_ATTRS,
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

_MANUAL_GLOBAL_PLACEMENT_ATTRS = dict(FLOW_ATTRS)
_MANUAL_GLOBAL_PLACEMENT_ATTRS["manual_global_placements"] = attr.string(
    doc = "JSON dict of instance name to placement {x, y, orientation}",
    mandatory = True,
)

_DIODES_ON_PORTS_ATTRS = dict(FLOW_ATTRS)
_DIODES_ON_PORTS_ATTRS["diode_on_ports"] = attr.string(
    doc = "Port polarity for diode insertion: 'none', 'in', 'out', or 'both'",
    mandatory = True,
)

librelane_manual_global_placement = rule(
    implementation = _manual_global_placement_impl,
    attrs = _MANUAL_GLOBAL_PLACEMENT_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_diodes_on_ports = rule(
    implementation = _diodes_on_ports_impl,
    attrs = _DIODES_ON_PORTS_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_heuristic_diode_insertion = rule(
    implementation = _heuristic_diode_insertion_impl,
    attrs = FLOW_ATTRS,
    provides = [DefaultInfo, LibrelaneInfo],
)

librelane_remove_routing_obstructions = rule(
    implementation = _remove_routing_obstructions_impl,
    attrs = _ROUTING_OBSTRUCTIONS_ATTRS,
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
