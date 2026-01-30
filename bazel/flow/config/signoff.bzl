# Signoff configuration attributes and rule
#
# These ~60 attributes control STA, RCX, Magic, KLayout, LVS, and checker behavior.

SignoffConfig = provider(
    doc = "Signoff configuration (DRC, LVS, STA, extraction).",
    fields = {
        # STA
        "sta_macro_prioritize_nl": "Prioritize netlists+SPEF over LIB for macros",
        "sta_max_violator_count": "Max violators in report (0 = unlimited)",
        "sta_threads": "Max parallel STA corners (0 = auto)",
        "vsrc_loc_files": "Map of net names to PSM location files for IR drop",

        # RCX
        "rcx_merge_via_wire_res": "Merge via and wire resistances",
        "rcx_sdc_file": "File - SDC file for RCX-based STA",

        # Magic
        "magic_def_labels": "Read labels with DEF files",
        "magic_gds_polygon_subcells": "Use polygon subcells for speed",
        "magic_def_no_blockages": "Ignore DEF blockages",
        "magic_include_gds_pointers": "Include GDS pointers in mag files",
        "magic_capture_errors": "Capture and quit on Magic errors",
        "magic_ext_use_gds": "Use GDS for SPICE extraction",
        "magic_ext_abstract_cells": "Cells to abstract in extraction",
        "magic_no_ext_unique": "Skip extract unique for label connections",
        "magic_ext_short_resistor": "Add resistors to shorts",
        "magic_ext_abstract": "Extract based on black-boxed cells",
        "magic_feedback_conversion_threshold": "Max feedback items for KLayout conversion",
        "magic_zeroize_origin": "Move layout origin to 0,0",
        "magic_disable_cif_info": "Disable CIF info in GDSII",
        "magic_macro_std_cell_source": "Macro std cell source (PDK/macro)",
        "magic_lef_write_use_gds": "Use GDS for LEF writing",
        "magic_write_full_lef": "Include all shapes in macro LEF",
        "magic_write_lef_pinonly": "Mark only port labels as pins",
        "magic_drc_use_gds": "Run Magic DRC on GDS instead of DEF",
        "run_magic_drc": "Enable Magic DRC step",

        # KLayout
        "klayout_xor_threads": "Number of threads for KLayout XOR",
        "klayout_drc_threads": "Number of threads for KLayout DRC",
        "run_klayout_drc": "Enable KLayout DRC step",

        # LVS
        "run_lvs": "Enable Netgen LVS step",
        "lvs_include_marco_netlists": "Include macro netlists in LVS",
        "lvs_flatten_cells": "Cells to flatten during LVS",

        # Extra files
        "extra_lefs": "Extra LEF files for macros",
        "extra_gds_files": "Extra GDS files for macros",
        "extra_spice_models": "Extra SPICE models for LVS",

        # Checker error flags
        "error_on_linter_timing_constructs": "Quit on timing constructs",
        "error_on_linter_errors": "Quit on linter errors",
        "error_on_linter_warnings": "Quit on linter warnings",
        "error_on_unmapped_cells": "Error on unmapped cells",
        "error_on_synth_checks": "Error on synthesis check failures",
        "error_on_nl_assign_statements": "Error on assign statements in netlist",
        "error_on_pdn_violations": "Error on power grid violations",
        "error_on_tr_drc": "Error on routing DRC violations",
        "error_on_disconnected_pins": "Error on critical disconnected pins",
        "error_on_long_wire": "Error on wires exceeding threshold",
        "error_on_illegal_overlaps": "Error on illegal overlaps",
        "error_on_lvs_error": "Error on LVS errors",
        "error_on_xor_error": "Error on XOR differences",
        "error_on_magic_drc": "Error on Magic DRC violations",
        "error_on_klayout_drc": "Error on KLayout DRC violations",

        # Timing violation corners
        "setup_violation_corners": "Corners for setup violation checking",
        "hold_violation_corners": "Corners for hold violation checking",
        "max_slew_violation_corners": "Corners for max slew checking",
        "max_cap_violation_corners": "Corners for max cap checking",
    },
)

SIGNOFF_ATTRS = {
    # STA
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
    "vsrc_loc_files": attr.label_keyed_string_dict(
        doc = "Map of PSM location files to power/ground net names for IR drop analysis",
        allow_files = True,
    ),

    # RCX
    "rcx_merge_via_wire_res": attr.bool(
        doc = "Merge via and wire resistances in RCX",
        default = True,
    ),
    "rcx_sdc_file": attr.label(
        doc = "SDC file for RCX-based STA (optional, different from implementation SDC)",
        allow_single_file = True,
    ),

    # Magic
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
    "magic_ext_use_gds": attr.bool(
        doc = "Use GDS for SPICE extraction instead of DEF/LEF",
        default = False,
    ),
    "magic_ext_abstract_cells": attr.string_list(
        doc = "Regex patterns for cells to abstract (black-box) during SPICE extraction",
        default = [],
    ),
    "magic_no_ext_unique": attr.bool(
        doc = "Skip 'extract unique' in Magic (enables LVS connections by label)",
        default = False,
    ),
    "magic_ext_short_resistor": attr.bool(
        doc = "Add resistors to shorts in extraction (may fix LVS issues)",
        default = False,
    ),
    "magic_ext_abstract": attr.bool(
        doc = "Extract SPICE based on black-boxed cells rather than transistors",
        default = False,
    ),
    "magic_feedback_conversion_threshold": attr.int(
        doc = "Max feedback items before skipping KLayout database conversion",
        default = 10000,
    ),
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
    "magic_lef_write_use_gds": attr.bool(
        doc = "Use GDS for LEF writing instead of abstract LEF views",
        default = False,
    ),
    "magic_write_full_lef": attr.bool(
        doc = "Include all shapes in macro LEF instead of abstracted view",
        default = False,
    ),
    "magic_write_lef_pinonly": attr.bool(
        doc = "Mark only port labels as pins, rest as obstructions",
        default = False,
    ),
    "magic_drc_use_gds": attr.bool(
        doc = "Run Magic DRC on GDS instead of DEF (more accurate but slower)",
        default = True,
    ),
    "run_magic_drc": attr.bool(
        doc = "Enable Magic DRC step",
        default = True,
    ),

    # KLayout
    "klayout_xor_threads": attr.int(
        doc = "Number of threads for KLayout XOR check (0 = auto)",
        default = 0,
    ),
    "klayout_drc_threads": attr.int(
        doc = "Number of threads for KLayout DRC (0 = auto)",
        default = 0,
    ),
    "run_klayout_drc": attr.bool(
        doc = "Enable KLayout DRC step",
        default = True,
    ),

    # LVS
    "run_lvs": attr.bool(
        doc = "Enable Netgen LVS step",
        default = True,
    ),
    "lvs_include_marco_netlists": attr.bool(
        doc = "Include gate-level netlists of macros in LVS",
        default = False,
    ),
    "lvs_flatten_cells": attr.string_list(
        doc = "Cell names to flatten during LVS",
        default = [],
    ),

    # Extra files
    "extra_lefs": attr.label_list(
        doc = "Extra LEF files for macros (loaded by KLayout, Magic, OpenROAD)",
        allow_files = [".lef"],
        default = [],
    ),
    "extra_gds_files": attr.label_list(
        doc = "Extra GDS files for macros (loaded by KLayout, Magic)",
        allow_files = [".gds"],
        default = [],
    ),
    "extra_spice_models": attr.label_list(
        doc = "Extra SPICE model files for LVS",
        allow_files = True,
        default = [],
    ),

    # Checker error flags
    "error_on_linter_timing_constructs": attr.bool(
        doc = "Quit immediately on timing constructs in RTL",
        default = True,
    ),
    "error_on_linter_errors": attr.bool(
        doc = "Quit immediately on linter errors",
        default = True,
    ),
    "error_on_linter_warnings": attr.bool(
        doc = "Raise an error on linter warnings",
        default = False,
    ),
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
    "error_on_illegal_overlaps": attr.bool(
        doc = "Error on illegal overlaps during Magic extraction (Step 70)",
        default = True,
    ),
    "error_on_lvs_error": attr.bool(
        doc = "Error on LVS errors (Step 72)",
        default = True,
    ),
    "error_on_xor_error": attr.bool(
        doc = "Error on XOR differences between Magic and KLayout GDS",
        default = True,
    ),
    "error_on_magic_drc": attr.bool(
        doc = "Error on Magic DRC violations",
        default = True,
    ),
    "error_on_klayout_drc": attr.bool(
        doc = "Error on KLayout DRC violations",
        default = True,
    ),

    # Timing violation corners
    "setup_violation_corners": attr.string_list(
        doc = "IPVT corners for setup violation checking (empty = use TIMING_VIOLATION_CORNERS)",
        default = [],
    ),
    "hold_violation_corners": attr.string_list(
        doc = "IPVT corners for hold violation checking (empty = use TIMING_VIOLATION_CORNERS)",
        default = [],
    ),
    "max_slew_violation_corners": attr.string_list(
        doc = "IPVT corners for max slew violation checking (default: no corners checked)",
        default = [""],
    ),
    "max_cap_violation_corners": attr.string_list(
        doc = "IPVT corners for max cap violation checking (default: no corners checked)",
        default = [""],
    ),
}

# Default values for signoff config
SIGNOFF_DEFAULTS = {
    "sta_macro_prioritize_nl": True,
    "sta_max_violator_count": 0,
    "sta_threads": 0,
    "vsrc_loc_files": {},
    "rcx_merge_via_wire_res": True,
    "rcx_sdc_file": None,
    "magic_def_labels": True,
    "magic_gds_polygon_subcells": False,
    "magic_def_no_blockages": True,
    "magic_include_gds_pointers": False,
    "magic_capture_errors": True,
    "magic_ext_use_gds": False,
    "magic_ext_abstract_cells": [],
    "magic_no_ext_unique": False,
    "magic_ext_short_resistor": False,
    "magic_ext_abstract": False,
    "magic_feedback_conversion_threshold": 10000,
    "magic_zeroize_origin": False,
    "magic_disable_cif_info": True,
    "magic_macro_std_cell_source": "macro",
    "magic_lef_write_use_gds": False,
    "magic_write_full_lef": False,
    "magic_write_lef_pinonly": False,
    "magic_drc_use_gds": True,
    "run_magic_drc": True,
    "klayout_xor_threads": 0,
    "klayout_drc_threads": 0,
    "run_klayout_drc": True,
    "run_lvs": True,
    "lvs_include_marco_netlists": False,
    "lvs_flatten_cells": [],
    "extra_lefs": [],
    "extra_gds_files": [],
    "extra_spice_models": [],
    "error_on_linter_timing_constructs": True,
    "error_on_linter_errors": True,
    "error_on_linter_warnings": False,
    "error_on_unmapped_cells": True,
    "error_on_synth_checks": True,
    "error_on_nl_assign_statements": True,
    "error_on_pdn_violations": True,
    "error_on_tr_drc": True,
    "error_on_disconnected_pins": True,
    "error_on_long_wire": True,
    "error_on_illegal_overlaps": True,
    "error_on_lvs_error": True,
    "error_on_xor_error": True,
    "error_on_magic_drc": True,
    "error_on_klayout_drc": True,
    "setup_violation_corners": [],
    "hold_violation_corners": [],
    "max_slew_violation_corners": [""],
    "max_cap_violation_corners": [""],
}


def _signoff_config_impl(ctx):
    return [SignoffConfig(
        sta_macro_prioritize_nl = ctx.attr.sta_macro_prioritize_nl,
        sta_max_violator_count = ctx.attr.sta_max_violator_count,
        sta_threads = ctx.attr.sta_threads,
        vsrc_loc_files = {f: v for f, v in ctx.attr.vsrc_loc_files.items()},
        rcx_merge_via_wire_res = ctx.attr.rcx_merge_via_wire_res,
        rcx_sdc_file = ctx.file.rcx_sdc_file,
        magic_def_labels = ctx.attr.magic_def_labels,
        magic_gds_polygon_subcells = ctx.attr.magic_gds_polygon_subcells,
        magic_def_no_blockages = ctx.attr.magic_def_no_blockages,
        magic_include_gds_pointers = ctx.attr.magic_include_gds_pointers,
        magic_capture_errors = ctx.attr.magic_capture_errors,
        magic_ext_use_gds = ctx.attr.magic_ext_use_gds,
        magic_ext_abstract_cells = ctx.attr.magic_ext_abstract_cells,
        magic_no_ext_unique = ctx.attr.magic_no_ext_unique,
        magic_ext_short_resistor = ctx.attr.magic_ext_short_resistor,
        magic_ext_abstract = ctx.attr.magic_ext_abstract,
        magic_feedback_conversion_threshold = ctx.attr.magic_feedback_conversion_threshold,
        magic_zeroize_origin = ctx.attr.magic_zeroize_origin,
        magic_disable_cif_info = ctx.attr.magic_disable_cif_info,
        magic_macro_std_cell_source = ctx.attr.magic_macro_std_cell_source,
        magic_lef_write_use_gds = ctx.attr.magic_lef_write_use_gds,
        magic_write_full_lef = ctx.attr.magic_write_full_lef,
        magic_write_lef_pinonly = ctx.attr.magic_write_lef_pinonly,
        magic_drc_use_gds = ctx.attr.magic_drc_use_gds,
        run_magic_drc = ctx.attr.run_magic_drc,
        klayout_xor_threads = ctx.attr.klayout_xor_threads,
        klayout_drc_threads = ctx.attr.klayout_drc_threads,
        run_klayout_drc = ctx.attr.run_klayout_drc,
        run_lvs = ctx.attr.run_lvs,
        lvs_include_marco_netlists = ctx.attr.lvs_include_marco_netlists,
        lvs_flatten_cells = ctx.attr.lvs_flatten_cells,
        extra_lefs = ctx.files.extra_lefs,
        extra_gds_files = ctx.files.extra_gds_files,
        extra_spice_models = ctx.files.extra_spice_models,
        error_on_linter_timing_constructs = ctx.attr.error_on_linter_timing_constructs,
        error_on_linter_errors = ctx.attr.error_on_linter_errors,
        error_on_linter_warnings = ctx.attr.error_on_linter_warnings,
        error_on_unmapped_cells = ctx.attr.error_on_unmapped_cells,
        error_on_synth_checks = ctx.attr.error_on_synth_checks,
        error_on_nl_assign_statements = ctx.attr.error_on_nl_assign_statements,
        error_on_pdn_violations = ctx.attr.error_on_pdn_violations,
        error_on_tr_drc = ctx.attr.error_on_tr_drc,
        error_on_disconnected_pins = ctx.attr.error_on_disconnected_pins,
        error_on_long_wire = ctx.attr.error_on_long_wire,
        error_on_illegal_overlaps = ctx.attr.error_on_illegal_overlaps,
        error_on_lvs_error = ctx.attr.error_on_lvs_error,
        error_on_xor_error = ctx.attr.error_on_xor_error,
        error_on_magic_drc = ctx.attr.error_on_magic_drc,
        error_on_klayout_drc = ctx.attr.error_on_klayout_drc,
        setup_violation_corners = ctx.attr.setup_violation_corners,
        hold_violation_corners = ctx.attr.hold_violation_corners,
        max_slew_violation_corners = ctx.attr.max_slew_violation_corners,
        max_cap_violation_corners = ctx.attr.max_cap_violation_corners,
    )]


librelane_signoff_config = rule(
    implementation = _signoff_config_impl,
    attrs = SIGNOFF_ATTRS,
    provides = [SignoffConfig],
)
