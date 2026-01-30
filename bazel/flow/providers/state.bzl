# LibrelaneInfo provider - design state that changes between steps
#
# Field names match librelane's DesignFormat IDs where possible.
# See librelane/state/design_format.py for the full list.

LibrelaneInfo = provider(
    doc = "Design state passed between librelane flow stages.",
    fields = {
        # State from previous step (for metrics flow)
        "state_out": "File - state_out.json from this step (carries metrics)",

        # Design views - field names match librelane DesignFormat IDs
        # Each is a File, dict of Files (for multi-corner), or None
        "nl": "File - Verilog netlist",
        "pnl": "File - Powered Verilog netlist",
        "def": "File - Design Exchange Format",
        "odb": "File - OpenDB database",
        "sdc": "File - Timing constraints (output from synthesis/PnR)",
        "sdf": "Dict[str, File] - Standard Delay Format (per corner)",
        "spef": "Dict[str, File] - Parasitics (per corner)",
        "lib": "Dict[str, File] - Timing libraries (per corner)",
        "gds": "File - GDSII stream",
        "mag_gds": "File - GDSII stream from Magic",
        "klayout_gds": "File - GDSII stream from KLayout",
        "lef": "File - Library Exchange Format",
        "mag": "File - Magic view",
        "spice": "File - SPICE netlist",
        "json_h": "File - JSON header",
        "vh": "File - Verilog header",
    },
)
