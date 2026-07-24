# Repository rule to extract PDK configuration at fetch time

# LibreLane PDK config keys and their Bazel value types. PdkInfo field names are
# always the lowercase form of these keys.
# Types: "file", "file_list", "file_dict", "file_list_dict", "string",
# "string_list", "number", "int", "dict"
PDK_FIELD_TYPES = {
    # Core identity (handled separately)
    "STD_CELL_LIBRARY": "string",

    # Power/ground
    "VDD_PIN": "string",
    "GND_PIN": "string",
    "VDD_PIN_VOLTAGE": "number",
    "SCL_POWER_PINS": "string_list",
    "SCL_GROUND_PINS": "string_list",

    # Cell libraries - files
    "CELL_LEFS": "file_list",
    "CELL_GDS": "file_list",
    "CELL_VERILOG_MODELS": "file_list",
    "CELL_BB_VERILOG_MODELS": "file_list",
    "CELL_SPICE_MODELS": "file_list",
    "PAD_VERILOG_MODELS": "file_list",

    # Technology LEFs
    "TECH_LEFS": "file_dict",

    # Timing libraries
    "LIB": "file_list_dict",

    # GPIO pads
    "GPIO_PADS_LEF": "file_list",
    "GPIO_PADS_LEF_CORE_SIDE": "file_list",
    "GPIO_PADS_VERILOG": "file_list",
    "GPIO_PAD_CELLS": "string_list",

    # Floorplanning
    "FP_FLIP_SITES": "string_list",
    "FP_TRACKS_INFO": "file",
    "FP_TAPCELL_DIST": "number",
    "FP_PRUNE_THRESHOLD": "number",
    "PDN_CFG": "file",
    "IO_PIN_H_LAYER": "string",
    "IO_PIN_V_LAYER": "string",

    # Routing
    "RT_MIN_LAYER": "string",
    "RT_MAX_LAYER": "string",
    "GRT_LAYER_ADJUSTMENTS": "number_list",

    # Placement
    "GPL_CELL_PADDING": "int",
    "DPL_CELL_PADDING": "int",
    "EXTRA_SITES": "string_list",

    # CTS
    "CTS_ROOT_BUFFER": "string",
    "CTS_CLK_BUFFERS": "string_list",

    # Timing corners
    "DEFAULT_CORNER": "string",
    "STA_CORNERS": "string_list",
    "PNR_CORNERS": "string_list",

    # Wire RC
    "SET_RC_TCL": "file",
    "LAYERS_RC": "dict",
    "VIAS_R": "dict",
    "SIGNAL_WIRE_RC_LAYERS": "string_list",
    "CLOCK_WIRE_RC_LAYERS": "string_list",

    # Constraints
    "DEFAULT_MAX_TRAN": "number",
    "OUTPUT_CAP_LOAD": "number",
    "MAX_FANOUT_CONSTRAINT": "int",
    "MAX_TRANSITION_CONSTRAINT": "number",
    "MAX_CAPACITANCE_CONSTRAINT": "number",
    "CLOCK_UNCERTAINTY_CONSTRAINT": "number",
    "CLOCK_TRANSITION_CONSTRAINT": "number",
    "TIME_DERATING_CONSTRAINT": "number",
    "IO_DELAY_CONSTRAINT": "number",
    "WIRE_LENGTH_THRESHOLD": "number",

    # Synthesis cells
    "SYNTH_DRIVING_CELL": "string",
    "SYNTH_CLK_DRIVING_CELL": "string",
    "SYNTH_TIEHI_CELL": "string",
    "SYNTH_TIELO_CELL": "string",
    "SYNTH_BUFFER_CELL": "string",
    "SYNTH_EXCLUDED_CELL_FILE": "file",
    "PNR_EXCLUDED_CELL_FILE": "file",

    # Placement cells
    "WELLTAP_CELL": "string",
    "ENDCAP_CELL": "string",
    "PLACE_SITE": "string",
    "FILL_CELLS": "string_list",
    "DECAP_CELLS": "string_list",
    "CELL_PAD_EXCLUDE": "string_list",
    "DIODE_CELL": "string",
    "TRISTATE_CELLS": "string_list",

    # Signoff
    "PRIMARY_GDSII_STREAMOUT_TOOL": "string",

    # Step-specific PDK variables - IO
    "IO_PIN_H_LENGTH": "number",
    "IO_PIN_V_LENGTH": "number",
    "IO_PIN_MIN_DISTANCE": "number",

    # Step-specific PDK variables - PDN (Power Distribution Network)
    "PDN_RAIL_LAYER": "string",
    "PDN_RAIL_WIDTH": "number",
    "PDN_RAIL_OFFSET": "number",
    "PDN_HORIZONTAL_LAYER": "string",
    "PDN_VERTICAL_LAYER": "string",
    "PDN_CORE_HORIZONTAL_LAYER": "string",
    "PDN_CORE_VERTICAL_LAYER": "string",
    "PDN_HOFFSET": "number",
    "PDN_VOFFSET": "number",
    "PDN_HPITCH": "number",
    "PDN_VPITCH": "number",
    "PDN_HSPACING": "number",
    "PDN_VSPACING": "number",
    "PDN_HWIDTH": "number",
    "PDN_VWIDTH": "number",
    "PDN_CORE_RING_HOFFSET": "number",
    "PDN_CORE_RING_VOFFSET": "number",
    "PDN_CORE_RING_HSPACING": "number",
    "PDN_CORE_RING_VSPACING": "number",
    "PDN_CORE_RING_HWIDTH": "number",
    "PDN_CORE_RING_VWIDTH": "number",
    "PDN_CORE_RING_CONNECT_TO_PADS": "bool",
    "PDN_CORE_RING_ALLOW_OUT_OF_DIE": "bool",
    "PDN_EXTEND_TO": "string",
    "PDN_ENABLE_PINS": "bool",

    # Step-specific PDK variables - Antenna
    "HEURISTIC_ANTENNA_THRESHOLD": "number",

    # Step-specific PDK variables - Magic
    "MAGICRC": "file",
    "MAGIC_TECH": "file",
    "MAGIC_PDK_SETUP": "file",
    "CELL_MAGS": "file_list",
    "CELL_MAGLEFS": "file_list",

    # Step-specific PDK variables - KLayout
    "KLAYOUT_TECH": "file",
    "KLAYOUT_PROPERTIES": "file",
    "KLAYOUT_DEF_LAYER_MAP": "file",
    "KLAYOUT_DRC_RUNSET": "file",
    "KLAYOUT_DRC_OPTIONS": "bool_int_dict",
    "KLAYOUT_XOR_IGNORE_LAYERS": "string_list",
    "KLAYOUT_XOR_TILE_SIZE": "int",

    # Step-specific PDK variables - Netgen
    "NETGEN_SETUP": "file",

    # Step-specific PDK variables - RCX
    "RCX_RULESETS": "file_dict",

    # Step-specific PDK variables - Synthesis maps
    "SYNTH_LATCH_MAP": "file",
    "SYNTH_TRISTATE_MAP": "file",
    "SYNTH_CSA_MAP": "file",
    "SYNTH_RCA_MAP": "file",
    "SYNTH_FA_MAP": "file",
    "SYNTH_MUX_MAP": "file",
    "SYNTH_MUX4_MAP": "file",
    "SYNTH_CLOCKGATE_POSEDGE_ICG": "string",
    "SYNTH_CLOCKGATE_NEGEDGE_ICG": "string",

    # Step-specific PDK variables - Misc
    "IGNORE_DISCONNECTED_MODULES": "string_list",
    "TIMING_VIOLATION_CORNERS": "string_list",
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
    repository_ctx.watch(script_path)

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

        if librelane_key not in PDK_FIELD_TYPES:
            # Unknown field - skip
            continue

        field_name = librelane_key.lower()
        field_type = PDK_FIELD_TYPES[librelane_key]

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

        elif field_type == "bool":
            if type(value) == "bool":
                field_values[field_name] = ("bool", value)
            else:
                value_str = str(value).lower()
                if value_str == "true":
                    field_values[field_name] = ("bool", True)
                elif value_str == "false":
                    field_values[field_name] = ("bool", False)
                else:
                    fail("Expected bool for field '{}', got {}".format(field_name, value))

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

        elif field_type == "dict":
            if type(value) == "dict":
                field_values[field_name] = ("dict", value)
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

    # Generate each field listed in the PDK schema.
    for librelane_key, field_type in sorted(PDK_FIELD_TYPES.items()):
        field_name = librelane_key.lower()
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
