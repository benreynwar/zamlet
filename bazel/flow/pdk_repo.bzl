# Repository rule to extract PDK configuration at fetch time

# Mapping from librelane config keys to PdkInfo field names
# Format: "LIBRELANE_KEY": ("field_name", "type")
# Types: "file", "file_list", "file_dict", "file_list_dict", "string", "string_list", "number", "int"
PDK_FIELD_MAP = {
    # Core identity (handled separately)
    "STD_CELL_LIBRARY": ("scl", "string"),

    # Power/ground
    "VDD_PIN": ("vdd_pin", "string"),
    "GND_PIN": ("gnd_pin", "string"),
    "VDD_PIN_VOLTAGE": ("vdd_pin_voltage", "number"),
    "SCL_POWER_PINS": ("scl_power_pins", "string_list"),
    "SCL_GROUND_PINS": ("scl_ground_pins", "string_list"),

    # Cell libraries - files
    "CELL_LEFS": ("cell_lefs", "file_list"),
    "CELL_GDS": ("cell_gds", "file_list"),
    "CELL_VERILOG_MODELS": ("cell_verilog_models", "file_list"),
    "CELL_BB_VERILOG_MODELS": ("cell_bb_verilog_models", "file_list"),
    "CELL_SPICE_MODELS": ("cell_spice_models", "file_list"),

    # Technology LEFs
    "TECH_LEFS": ("tech_lefs", "file_dict"),

    # Timing libraries
    "LIB": ("lib", "file_list_dict"),

    # GPIO pads
    "GPIO_PADS_LEF": ("gpio_pads_lef", "file_list"),
    "GPIO_PADS_LEF_CORE_SIDE": ("gpio_pads_lef_core_side", "file_list"),
    "GPIO_PADS_VERILOG": ("gpio_pads_verilog", "file_list"),
    "GPIO_PAD_CELLS": ("gpio_pad_cells", "string_list"),

    # Floorplanning
    "FP_TRACKS_INFO": ("fp_tracks_info", "file"),
    "FP_TAPCELL_DIST": ("fp_tapcell_dist", "number"),
    "FP_IO_HLAYER": ("fp_io_hlayer", "string"),
    "FP_IO_VLAYER": ("fp_io_vlayer", "string"),

    # Routing
    "RT_MIN_LAYER": ("rt_min_layer", "string"),
    "RT_MAX_LAYER": ("rt_max_layer", "string"),
    "GRT_LAYER_ADJUSTMENTS": ("grt_layer_adjustments", "number_list"),

    # Placement
    "GPL_CELL_PADDING": ("gpl_cell_padding", "int"),
    "DPL_CELL_PADDING": ("dpl_cell_padding", "int"),
    "EXTRA_SITES": ("extra_sites", "string_list"),

    # CTS
    "CTS_ROOT_BUFFER": ("cts_root_buffer", "string"),
    "CTS_CLK_BUFFERS": ("cts_clk_buffers", "string_list"),

    # Timing corners
    "DEFAULT_CORNER": ("default_corner", "string"),
    "STA_CORNERS": ("sta_corners", "string_list"),

    # Wire RC
    "SIGNAL_WIRE_RC_LAYERS": ("signal_wire_rc_layers", "string_list"),
    "CLOCK_WIRE_RC_LAYERS": ("clock_wire_rc_layers", "string_list"),

    # Constraints
    "DEFAULT_MAX_TRAN": ("default_max_tran", "number"),
    "OUTPUT_CAP_LOAD": ("output_cap_load", "number"),
    "MAX_FANOUT_CONSTRAINT": ("max_fanout_constraint", "int"),
    "MAX_TRANSITION_CONSTRAINT": ("max_transition_constraint", "number"),
    "MAX_CAPACITANCE_CONSTRAINT": ("max_capacitance_constraint", "number"),
    "CLOCK_UNCERTAINTY_CONSTRAINT": ("clock_uncertainty_constraint", "number"),
    "CLOCK_TRANSITION_CONSTRAINT": ("clock_transition_constraint", "number"),
    "TIME_DERATING_CONSTRAINT": ("time_derating_constraint", "number"),
    "IO_DELAY_CONSTRAINT": ("io_delay_constraint", "number"),
    "WIRE_LENGTH_THRESHOLD": ("wire_length_threshold", "number"),

    # Synthesis cells
    "SYNTH_DRIVING_CELL": ("synth_driving_cell", "string"),
    "SYNTH_CLK_DRIVING_CELL": ("synth_clk_driving_cell", "string"),
    "SYNTH_TIEHI_CELL": ("synth_tiehi_cell", "string"),
    "SYNTH_TIELO_CELL": ("synth_tielo_cell", "string"),
    "SYNTH_BUFFER_CELL": ("synth_buffer_cell", "string"),
    "SYNTH_EXCLUDED_CELL_FILE": ("synth_excluded_cell_file", "file"),
    "PNR_EXCLUDED_CELL_FILE": ("pnr_excluded_cell_file", "file"),

    # Placement cells
    "WELLTAP_CELL": ("welltap_cell", "string"),
    "ENDCAP_CELL": ("endcap_cell", "string"),
    "PLACE_SITE": ("place_site", "string"),
    "FILL_CELL": ("fill_cell", "string_list"),
    "DECAP_CELL": ("decap_cell", "string_list"),
    "CELL_PAD_EXCLUDE": ("cell_pad_exclude", "string_list"),
    "DIODE_CELL": ("diode_cell", "string"),
    "TRISTATE_CELLS": ("tristate_cells", "string_list"),

    # Signoff
    "PRIMARY_GDSII_STREAMOUT_TOOL": ("primary_gdsii_streamout_tool", "string"),

    # Step-specific PDK variables - IO
    "FP_IO_HLENGTH": ("fp_io_hlength", "number"),
    "FP_IO_VLENGTH": ("fp_io_vlength", "number"),
    "FP_IO_MIN_DISTANCE": ("fp_io_min_distance", "number"),

    # Step-specific PDK variables - PDN (Power Distribution Network)
    "FP_PDN_RAIL_LAYER": ("fp_pdn_rail_layer", "string"),
    "FP_PDN_RAIL_WIDTH": ("fp_pdn_rail_width", "number"),
    "FP_PDN_RAIL_OFFSET": ("fp_pdn_rail_offset", "number"),
    "FP_PDN_HORIZONTAL_LAYER": ("fp_pdn_horizontal_layer", "string"),
    "FP_PDN_VERTICAL_LAYER": ("fp_pdn_vertical_layer", "string"),
    "FP_PDN_HOFFSET": ("fp_pdn_hoffset", "number"),
    "FP_PDN_VOFFSET": ("fp_pdn_voffset", "number"),
    "FP_PDN_HPITCH": ("fp_pdn_hpitch", "number"),
    "FP_PDN_VPITCH": ("fp_pdn_vpitch", "number"),
    "FP_PDN_HSPACING": ("fp_pdn_hspacing", "number"),
    "FP_PDN_VSPACING": ("fp_pdn_vspacing", "number"),
    "FP_PDN_HWIDTH": ("fp_pdn_hwidth", "number"),
    "FP_PDN_VWIDTH": ("fp_pdn_vwidth", "number"),
    "FP_PDN_CORE_RING_HOFFSET": ("fp_pdn_core_ring_hoffset", "number"),
    "FP_PDN_CORE_RING_VOFFSET": ("fp_pdn_core_ring_voffset", "number"),
    "FP_PDN_CORE_RING_HSPACING": ("fp_pdn_core_ring_hspacing", "number"),
    "FP_PDN_CORE_RING_VSPACING": ("fp_pdn_core_ring_vspacing", "number"),
    "FP_PDN_CORE_RING_HWIDTH": ("fp_pdn_core_ring_hwidth", "number"),
    "FP_PDN_CORE_RING_VWIDTH": ("fp_pdn_core_ring_vwidth", "number"),

    # Step-specific PDK variables - Antenna
    "HEURISTIC_ANTENNA_THRESHOLD": ("heuristic_antenna_threshold", "number"),

    # Step-specific PDK variables - Magic
    "MAGICRC": ("magicrc", "file"),
    "MAGIC_TECH": ("magic_tech", "file"),
    "MAGIC_PDK_SETUP": ("magic_pdk_setup", "file"),
    "CELL_MAGS": ("cell_mags", "file_list"),
    "CELL_MAGLEFS": ("cell_maglefs", "file_list"),

    # Step-specific PDK variables - KLayout
    "KLAYOUT_TECH": ("klayout_tech", "file"),
    "KLAYOUT_PROPERTIES": ("klayout_properties", "file"),
    "KLAYOUT_DEF_LAYER_MAP": ("klayout_def_layer_map", "file"),
    "KLAYOUT_DRC_RUNSET": ("klayout_drc_runset", "file"),
    "KLAYOUT_DRC_OPTIONS": ("klayout_drc_options", "bool_int_dict"),
    "KLAYOUT_XOR_IGNORE_LAYERS": ("klayout_xor_ignore_layers", "string_list"),
    "KLAYOUT_XOR_TILE_SIZE": ("klayout_xor_tile_size", "int"),

    # Step-specific PDK variables - Netgen
    "NETGEN_SETUP": ("netgen_setup", "file"),

    # Step-specific PDK variables - RCX
    "RCX_RULESETS": ("rcx_rulesets", "file_dict"),

    # Step-specific PDK variables - Synthesis maps
    "SYNTH_LATCH_MAP": ("synth_latch_map", "file"),
    "SYNTH_TRISTATE_MAP": ("synth_tristate_map", "file"),
    "SYNTH_CSA_MAP": ("synth_csa_map", "file"),
    "SYNTH_RCA_MAP": ("synth_rca_map", "file"),
    "SYNTH_FA_MAP": ("synth_fa_map", "file"),
    "SYNTH_MUX_MAP": ("synth_mux_map", "file"),
    "SYNTH_MUX4_MAP": ("synth_mux4_map", "file"),

    # Step-specific PDK variables - Misc
    "IGNORE_DISCONNECTED_MODULES": ("ignore_disconnected_modules", "string_list"),
    "TIMING_VIOLATION_CORNERS": ("timing_violation_corners", "string_list"),
}

def _pdk_config_repo_impl(repository_ctx):
    """Extract PDK configuration and generate files for Bazel."""

    pdk_root = repository_ctx.os.environ.get("PDK_ROOT")
    pdk = repository_ctx.attr.pdk
    scl = repository_ctx.attr.scl

    if not pdk_root:
        fail("PDK_ROOT environment variable must be set (run inside nix-shell)")

    # Path to the dump script (relative to workspace root)
    script_path = repository_ctx.path(repository_ctx.attr._dump_script)

    # Run the dump script
    # PATH must be passed through so we find nix-shell's python3 with librelane
    path = repository_ctx.os.environ.get("PATH", "")
    result = repository_ctx.execute(
        [
            "python3",
            str(script_path),
            "--pdk-root", pdk_root,
            "--pdk", pdk,
            "--scl", scl,
        ],
        environment = {
            "PDK_ROOT": pdk_root,
            "PDK": pdk,
            "PATH": path,
        },
        working_directory = str(repository_ctx.path(repository_ctx.attr._dump_script).dirname.dirname.dirname),
        quiet = False,
    )

    if result.return_code != 0:
        fail("Failed to extract PDK config:\n" + result.stderr)

    # Parse JSON output (skip nix-shell banner lines)
    lines = result.stdout.split("\n")
    json_start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("{"):
            json_start = i
            break
    json_str = "\n".join(lines[json_start:])

    raw_config = json.decode(json_str)

    # Process config using the field map
    field_values = {}  # field_name -> processed value
    file_counter = [0]  # mutable counter for unique file names

    for librelane_key, value in raw_config.items():
        if value == None or value == "":
            continue

        if librelane_key not in PDK_FIELD_MAP:
            # Unknown field - skip
            continue

        field_name, field_type = PDK_FIELD_MAP[librelane_key]

        # Skip if we already have a value for this field (handles deprecated names)
        if field_name in field_values:
            continue

        if field_type == "file":
            path = _as_string(value).strip()
            if path:
                label = _symlink_file(repository_ctx, field_name, path, file_counter)
                field_values[field_name] = ("file", label)

        elif field_type == "file_list":
            paths = _split_paths(value)
            labels = []
            for path in paths:
                label = _symlink_file(repository_ctx, field_name, path, file_counter)
                if label:
                    labels.append(label)
            if labels:
                field_values[field_name] = ("file_list", labels)

        elif field_type == "file_dict":
            if type(value) == "dict":
                corner_labels = {}
                for corner, path in value.items():
                    label = _symlink_file(repository_ctx, field_name, _as_string(path), file_counter)
                    if label:
                        corner_labels[corner] = label
                if corner_labels:
                    field_values[field_name] = ("file_dict", corner_labels)

        elif field_type == "file_list_dict":
            if type(value) == "dict":
                corner_labels = {}
                for corner, paths in value.items():
                    path_list = paths if type(paths) == "list" else [paths]
                    labels = []
                    for path in path_list:
                        label = _symlink_file(repository_ctx, field_name, _as_string(path), file_counter)
                        if label:
                            labels.append(label)
                    if labels:
                        corner_labels[corner] = labels
                if corner_labels:
                    field_values[field_name] = ("file_list_dict", corner_labels)

        elif field_type == "string":
            field_values[field_name] = ("string", _as_string(value))

        elif field_type == "string_list":
            items = _split_strings(value)
            if items:
                field_values[field_name] = ("string_list", items)

        elif field_type == "number":
            field_values[field_name] = ("number", _as_number(value))

        elif field_type == "int":
            field_values[field_name] = ("int", int(value))

        elif field_type == "number_list":
            if type(value) == "list":
                field_values[field_name] = ("number_list", [_as_number(v) for v in value])
            else:
                fail("Expected list for field '{}', got {}".format(field_name, type(value)))

        elif field_type == "number_dict":
            if type(value) == "dict":
                number_dict = {}
                for k, v in value.items():
                    number_dict[k] = _as_number(v)
                if number_dict:
                    field_values[field_name] = ("number_dict", number_dict)
            else:
                fail("Expected dict for field '{}', got {}".format(field_name, type(value)))

        elif field_type == "bool_int_dict":
            # Dict with bool or int values (e.g., KLAYOUT_DRC_OPTIONS)
            if type(value) == "dict":
                bool_int_dict = {}
                for k, v in value.items():
                    if type(v) == "bool":
                        bool_int_dict[k] = v
                    elif type(v) == "int":
                        bool_int_dict[k] = v
                    else:
                        # Try to parse as bool or int
                        v_str = str(v).lower()
                        if v_str == "true":
                            bool_int_dict[k] = True
                        elif v_str == "false":
                            bool_int_dict[k] = False
                        else:
                            bool_int_dict[k] = int(v)
                if bool_int_dict:
                    field_values[field_name] = ("bool_int_dict", bool_int_dict)
            else:
                fail("Expected dict for field '{}', got {}".format(field_name, type(value)))

        else:
            fail("Unknown field type '{}' for field '{}'".format(field_type, field_name))

    # Generate BUILD.bazel with exports_files
    _generate_build_file(repository_ctx)

    # Generate defs.bzl with PdkInfo rule
    _generate_defs_bzl(repository_ctx, pdk, scl, field_values)

def _as_string(value):
    """Convert value to string."""
    if type(value) == "string":
        return value
    return str(value)

def _as_number(value):
    """Convert value to number (float)."""
    if type(value) == "int":
        return float(value)
    if type(value) == "float":
        return value
    return float(str(value))

def _split_paths(value):
    """Split space-separated paths, handling potential newlines."""
    if type(value) == "list":
        return [_as_string(v).strip() for v in value if v]
    if type(value) != "string":
        return [_as_string(value)] if value else []
    paths = []
    for part in value.replace("\n", " ").split(" "):
        part = part.strip()
        if part:
            paths.append(part)
    return paths

def _split_strings(value):
    """Split space-separated strings into a list."""
    if type(value) == "list":
        return [_as_string(v).strip() for v in value if v]
    if type(value) != "string":
        return [_as_string(value)] if value else []
    items = []
    for part in value.replace("\n", " ").split(" "):
        part = part.strip()
        if part:
            items.append(part)
    return items

def _symlink_file(repository_ctx, field_name, path, counter):
    """Create a symlink to an external file and return its label."""
    path = path.strip()
    if not path:
        return None

    # Use counter for uniqueness
    basename = path.split("/")[-1]
    symlink_path = "files/{}_{}".format(counter[0], basename)
    counter[0] += 1

    repository_ctx.symlink(path, symlink_path)
    return symlink_path

def _generate_build_file(repository_ctx):
    """Generate BUILD.bazel that exports all symlinked files."""
    content = '''# Auto-generated PDK config repository
# Do not edit - regenerate by running: bazel sync --configure

exports_files(glob(["files/*"]))
'''
    repository_ctx.file("BUILD.bazel", content)

def _generate_defs_bzl(repository_ctx, pdk, scl, field_values):
    """Generate defs.bzl with PdkInfo provider."""
    content = '''"""PDK configuration for {} / {}."""

# Auto-generated by pdk_config_repo rule. Do not edit.

load("@zamlet//bazel/flow:providers.bzl", "PdkInfo")

def _pdk_impl(ctx):
    return [
        PdkInfo(
            name = "{}",
'''.format(pdk, scl, pdk)

    # Generate each field - include all fields from PDK_FIELD_MAP
    for librelane_key, (field_name, field_type) in sorted(PDK_FIELD_MAP.items()):
        if field_name in field_values:
            _, value = field_values[field_name]
            if field_type == "file":
                content += '            {} = ctx.file._{},\n'.format(field_name, field_name)
            elif field_type == "file_list":
                content += '            {} = ctx.files._{},\n'.format(field_name, field_name)
            elif field_type == "file_dict":
                content += '            {} = {{\n'.format(field_name)
                for corner, label in sorted(value.items()):
                    content += '                "{}": ctx.file._{}_{},\n'.format(corner, field_name, _safe_name(corner))
                content += '            },\n'
            elif field_type == "file_list_dict":
                content += '            {} = {{\n'.format(field_name)
                for corner, labels in sorted(value.items()):
                    content += '                "{}": ctx.files._{}_{},\n'.format(corner, field_name, _safe_name(corner))
                content += '            },\n'
            else:
                # Scalar value
                content += '            {} = {},\n'.format(field_name, repr(value))
        else:
            # Field not in PDK config - set to None
            content += '            {} = None,\n'.format(field_name)

    content += '''        ),
    ]

pdk = rule(
    implementation = _pdk_impl,
    attrs = {
'''

    # Generate attrs for file fields
    for field_name, (field_type, value) in sorted(field_values.items()):
        if field_type == "file":
            content += '        "_%s": attr.label(allow_single_file = True, default = ":%s"),\n' % (field_name, value)
        elif field_type == "file_list":
            content += '        "_%s": attr.label_list(allow_files = True, default = [%s]),\n' % (
                field_name,
                ", ".join(['":' + l + '"' for l in value]),
            )
        elif field_type == "file_dict":
            for corner, label in sorted(value.items()):
                content += '        "_{}_{}"'.format(field_name, _safe_name(corner))
                content += ': attr.label(allow_single_file = True, default = ":%s"),\n' % label
        elif field_type == "file_list_dict":
            for corner, labels in sorted(value.items()):
                content += '        "_{}_{}"'.format(field_name, _safe_name(corner))
                content += ': attr.label_list(allow_files = True, default = [%s]),\n' % (
                    ", ".join(['":' + l + '"' for l in labels]),
                )

    content += '''    },
    provides = [PdkInfo],
)
'''

    repository_ctx.file("defs.bzl", content)

def _safe_name(s):
    """Convert a string to a safe Starlark identifier."""
    return s.replace("-", "_").replace(".", "_").replace("*", "star")

pdk_config_repo = repository_rule(
    implementation = _pdk_config_repo_impl,
    attrs = {
        "pdk": attr.string(mandatory = True, doc = "PDK name (e.g., 'sky130A')"),
        "scl": attr.string(mandatory = True, doc = "Standard cell library name"),
        "_dump_script": attr.label(
            default = "//bazel/flow:dump_pdk_config.py",
            allow_single_file = True,
        ),
    },
    environ = ["PDK_ROOT", "PATH"],
    local = True,  # Re-fetch when local files change
    doc = "Extracts PDK configuration and generates a .bzl file",
)
