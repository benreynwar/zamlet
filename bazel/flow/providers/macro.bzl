# MacroInfo provider - information about hard macros for hierarchical designs

MacroInfo = provider(
    doc = "Information about a hard macro for hierarchical designs.",
    fields = {
        "name": "Macro module name",
        "lef": "File - LEF abstract",
        "gds": "File - GDSII layout",
        "netlist": "File - gate-level netlist (.nl.v)",
    },
)
