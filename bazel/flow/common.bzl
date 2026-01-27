# Common utilities for librelane flow rules

load(":providers.bzl", "LibrelaneInput", "LibrelaneInfo", "PdkInfo", "MacroInfo")

def _add_optional(config, key, value):
    """Add a value to config if it's not None."""
    if value != None:
        config[key] = value

def _add_optional_file(config, key, f):
    """Add a file path to config if the file is not None."""
    if f != None:
        config[key] = f.path

def _add_optional_file_list(config, key, files):
    """Add a list of file paths to config if the list is not None/empty."""
    if files:
        config[key] = [f.path for f in files]

def _add_optional_file_dict(config, key, file_dict):
    """Add a dict of file paths to config if the dict is not None/empty."""
    if file_dict:
        config[key] = {k: f.path for k, f in file_dict.items()}

def create_librelane_config(input_info, state_info):
    """Create a config dict for librelane.

    Args:
        input_info: LibrelaneInput with flow configuration
        state_info: LibrelaneInfo with current design state (can be None for init)
    """
    pdk = input_info.pdk_info

    config = {
        # Design-level config
        "DESIGN_NAME": input_info.top,
        "CLOCK_PORT": input_info.clock_port,
        "CLOCK_PERIOD": float(input_info.clock_period),
        "VERILOG_FILES": get_verilog_paths(input_info, state_info),

        # PDK identity
        "PDK": pdk.name,
        "STD_CELL_LIBRARY": pdk.scl,

        # PDK config - power/ground
        "VDD_PIN": pdk.vdd_pin,
        "GND_PIN": pdk.gnd_pin,
        "SCL_POWER_PINS": pdk.scl_power_pins,
        "SCL_GROUND_PINS": pdk.scl_ground_pins,

        # PDK config - cells (as paths for librelane)
        "CELL_LEFS": [f.path for f in pdk.cell_lefs],
        "CELL_GDS": [f.path for f in pdk.cell_gds],

        # PDK config - tech LEFs (corner -> path)
        "TECH_LEFS": {corner: f.path for corner, f in pdk.tech_lefs.items()},

        # PDK config - timing
        "DEFAULT_CORNER": pdk.default_corner,
        "STA_CORNERS": pdk.sta_corners,

        # PDK config - floorplanning
        "FP_TRACKS_INFO": pdk.fp_tracks_info.path,
        "FP_TAPCELL_DIST": pdk.fp_tapcell_dist,
        "FP_IO_HLAYER": pdk.fp_io_hlayer,
        "FP_IO_VLAYER": pdk.fp_io_vlayer,
        "PLACE_SITE": pdk.place_site,

        # PDK config - routing
        "RT_MIN_LAYER": pdk.rt_min_layer,
        "RT_MAX_LAYER": pdk.rt_max_layer,
        "GRT_LAYER_ADJUSTMENTS": pdk.grt_layer_adjustments,

        # PDK config - placement
        "GPL_CELL_PADDING": pdk.gpl_cell_padding,
        "DPL_CELL_PADDING": pdk.dpl_cell_padding,

        # PDK config - CTS
        "CTS_ROOT_BUFFER": pdk.cts_root_buffer,
        "CTS_CLK_BUFFERS": pdk.cts_clk_buffers,

        # PDK config - synthesis cells
        "SYNTH_DRIVING_CELL": pdk.synth_driving_cell,
        "SYNTH_TIEHI_CELL": pdk.synth_tiehi_cell,
        "SYNTH_TIELO_CELL": pdk.synth_tielo_cell,
        "SYNTH_BUFFER_CELL": pdk.synth_buffer_cell,
        "SYNTH_EXCLUDED_CELL_FILE": pdk.synth_excluded_cell_file.path,
        "PNR_EXCLUDED_CELL_FILE": pdk.pnr_excluded_cell_file.path,

        # PDK config - placement cells
        "WELLTAP_CELL": pdk.welltap_cell,
        "ENDCAP_CELL": pdk.endcap_cell,
        "FILL_CELL": pdk.fill_cell,
        "DECAP_CELL": pdk.decap_cell,
        "DIODE_CELL": pdk.diode_cell,
        "CELL_PAD_EXCLUDE": pdk.cell_pad_exclude,

        # PDK config - constraints
        "OUTPUT_CAP_LOAD": pdk.output_cap_load,
        "MAX_FANOUT_CONSTRAINT": pdk.max_fanout_constraint,
        "CLOCK_UNCERTAINTY_CONSTRAINT": pdk.clock_uncertainty_constraint,
        "CLOCK_TRANSITION_CONSTRAINT": pdk.clock_transition_constraint,
        "TIME_DERATING_CONSTRAINT": pdk.time_derating_constraint,
        "IO_DELAY_CONSTRAINT": pdk.io_delay_constraint,

        # PDK config - signoff
        "PRIMARY_GDSII_STREAMOUT_TOOL": pdk.primary_gdsii_streamout_tool,
    }

    # Add optional fields if present
    if pdk.max_transition_constraint:
        config["MAX_TRANSITION_CONSTRAINT"] = pdk.max_transition_constraint
    if pdk.max_capacitance_constraint:
        config["MAX_CAPACITANCE_CONSTRAINT"] = pdk.max_capacitance_constraint
    if pdk.vdd_pin_voltage:
        config["VDD_PIN_VOLTAGE"] = pdk.vdd_pin_voltage

    # Step-specific optional fields
    _add_optional(config, "EXTRA_SITES", pdk.extra_sites)
    _add_optional(config, "FP_IO_HLENGTH", pdk.fp_io_hlength)
    _add_optional(config, "FP_IO_VLENGTH", pdk.fp_io_vlength)
    _add_optional(config, "FP_IO_MIN_DISTANCE", pdk.fp_io_min_distance)
    _add_optional(config, "FP_PDN_RAIL_LAYER", pdk.fp_pdn_rail_layer)
    _add_optional(config, "FP_PDN_RAIL_WIDTH", pdk.fp_pdn_rail_width)
    _add_optional(config, "FP_PDN_RAIL_OFFSET", pdk.fp_pdn_rail_offset)
    _add_optional(config, "FP_PDN_HORIZONTAL_LAYER", pdk.fp_pdn_horizontal_layer)
    _add_optional(config, "FP_PDN_VERTICAL_LAYER", pdk.fp_pdn_vertical_layer)
    _add_optional(config, "FP_PDN_HOFFSET", pdk.fp_pdn_hoffset)
    _add_optional(config, "FP_PDN_VOFFSET", pdk.fp_pdn_voffset)
    _add_optional(config, "FP_PDN_HPITCH", pdk.fp_pdn_hpitch)
    _add_optional(config, "FP_PDN_VPITCH", pdk.fp_pdn_vpitch)
    _add_optional(config, "FP_PDN_HSPACING", pdk.fp_pdn_hspacing)
    _add_optional(config, "FP_PDN_VSPACING", pdk.fp_pdn_vspacing)
    _add_optional(config, "FP_PDN_HWIDTH", pdk.fp_pdn_hwidth)
    _add_optional(config, "FP_PDN_VWIDTH", pdk.fp_pdn_vwidth)
    _add_optional(config, "FP_PDN_CORE_RING_HOFFSET", pdk.fp_pdn_core_ring_hoffset)
    _add_optional(config, "FP_PDN_CORE_RING_VOFFSET", pdk.fp_pdn_core_ring_voffset)
    _add_optional(config, "FP_PDN_CORE_RING_HSPACING", pdk.fp_pdn_core_ring_hspacing)
    _add_optional(config, "FP_PDN_CORE_RING_VSPACING", pdk.fp_pdn_core_ring_vspacing)
    _add_optional(config, "FP_PDN_CORE_RING_HWIDTH", pdk.fp_pdn_core_ring_hwidth)
    _add_optional(config, "FP_PDN_CORE_RING_VWIDTH", pdk.fp_pdn_core_ring_vwidth)
    _add_optional(config, "HEURISTIC_ANTENNA_THRESHOLD", pdk.heuristic_antenna_threshold)
    _add_optional_file(config, "MAGICRC", pdk.magicrc)
    _add_optional_file(config, "MAGIC_TECH", pdk.magic_tech)
    _add_optional_file(config, "MAGIC_PDK_SETUP", pdk.magic_pdk_setup)
    _add_optional_file_list(config, "CELL_MAGS", pdk.cell_mags)
    _add_optional_file_list(config, "CELL_MAGLEFS", pdk.cell_maglefs)
    _add_optional_file(config, "KLAYOUT_TECH", pdk.klayout_tech)
    _add_optional_file(config, "KLAYOUT_PROPERTIES", pdk.klayout_properties)
    _add_optional_file(config, "KLAYOUT_DEF_LAYER_MAP", pdk.klayout_def_layer_map)
    _add_optional_file(config, "KLAYOUT_DRC_RUNSET", pdk.klayout_drc_runset)
    _add_optional(config, "KLAYOUT_XOR_IGNORE_LAYERS", pdk.klayout_xor_ignore_layers)
    _add_optional(config, "KLAYOUT_XOR_TILE_SIZE", pdk.klayout_xor_tile_size)
    _add_optional_file(config, "NETGEN_SETUP", pdk.netgen_setup)
    _add_optional_file_dict(config, "RCX_RULESETS", pdk.rcx_rulesets)
    _add_optional_file(config, "SYNTH_LATCH_MAP", pdk.synth_latch_map)
    _add_optional_file(config, "SYNTH_TRISTATE_MAP", pdk.synth_tristate_map)
    _add_optional_file(config, "SYNTH_CSA_MAP", pdk.synth_csa_map)
    _add_optional_file(config, "SYNTH_RCA_MAP", pdk.synth_rca_map)
    _add_optional_file(config, "SYNTH_FA_MAP", pdk.synth_fa_map)
    _add_optional_file(config, "SYNTH_MUX_MAP", pdk.synth_mux_map)
    _add_optional_file(config, "SYNTH_MUX4_MAP", pdk.synth_mux4_map)
    _add_optional(config, "IGNORE_DISCONNECTED_MODULES", pdk.ignore_disconnected_modules)
    _add_optional(config, "TIMING_VIOLATION_CORNERS", pdk.timing_violation_corners)

    # Add LIB dict (corner -> list of file paths)
    config["LIB"] = {corner: [f.path for f in files] for corner, files in pdk.lib.items()}

    # Add macros config
    macros = get_macros_config(input_info)
    if macros:
        config["MACROS"] = macros

    # Add custom SDC files if provided
    if input_info.pnr_sdc_file:
        config["PNR_SDC_FILE"] = input_info.pnr_sdc_file.path
    if input_info.signoff_sdc_file:
        config["SIGNOFF_SDC_FILE"] = input_info.signoff_sdc_file.path

    return config

# Mapping of LibrelaneInfo field names to librelane state keys
# Most are identical, but this allows for any future differences
STATE_FIELD_MAPPING = {
    "nl": "nl",
    "pnl": "pnl",
    "def": "def",
    "odb": "odb",
    "sdc": "sdc",
    "sdf": "sdf",
    "spef": "spef",
    "lib": "lib",
    "gds": "gds",
    "mag_gds": "mag_gds",
    "klayout_gds": "klayout_gds",
    "lef": "lef",
    "mag": "mag",
    "spice": "spice",
    "json_h": "json_h",
    "vh": "vh",
}

# Reverse mapping for deserialize
STATE_KEY_TO_FIELD = {v: k for k, v in STATE_FIELD_MAPPING.items()}

# Fields that can have multiple files (dict keyed by corner name)
MULTI_FILE_FIELDS = ["sdf", "spef", "lib"]

def serialize_state(src_info):
    """Serialize LibrelaneInfo to a state dict for librelane.

    Converts File objects to their paths. Does NOT include metrics -
    those are merged from state_out.json at execution time.

    Args:
        src_info: LibrelaneInfo provider

    Returns:
        Dict suitable for JSON encoding as state_in.json (without metrics)
    """
    state = {}

    # Serialize each view field
    for field, state_key in STATE_FIELD_MAPPING.items():
        value = getattr(src_info, field, None)
        if value == None:
            state[state_key] = None
        elif field in MULTI_FILE_FIELDS:
            # Multi-file fields are dicts
            if type(value) == "dict":
                state[state_key] = {k: v.path for k, v in value.items()}
            else:
                state[state_key] = None
        else:
            # Single file
            state[state_key] = value.path

    # Metrics will be merged from previous state_out.json at execution time
    state["metrics"] = {}

    return state

def deserialize_state(state_out_content, declared_outputs, prev_info):
    """Deserialize librelane state_out.json to LibrelaneInfo fields.

    Validates that all paths in state_out match either:
    - A declared Bazel output file
    - An unchanged path from the input state

    Args:
        state_out_content: JSON string of state_out.json
        declared_outputs: Dict mapping basename to declared File object
        prev_info: Previous LibrelaneInfo (for unchanged values)

    Returns:
        Dict of field values for new LibrelaneInfo

    Fails if state_out contains unknown keys or paths that can't be mapped.
    """
    state = json.decode(state_out_content)

    # Extract and remove metrics
    metrics = state.pop("metrics", {})
    result = {
        "metrics": json.encode(metrics) if metrics else None,
    }

    # Process each state key
    for state_key, value in state.items():
        if state_key not in STATE_KEY_TO_FIELD:
            fail("Unknown state key from librelane: '{}'. Add it to STATE_FIELD_MAPPING.".format(state_key))

        field = STATE_KEY_TO_FIELD[state_key]

        if value == None:
            result[field] = None
            continue

        if field in MULTI_FILE_FIELDS:
            # Multi-file: value is a dict
            if type(value) == "dict":
                file_dict = {}
                for corner, path in value.items():
                    file_dict[corner] = _resolve_path(path, declared_outputs, prev_info, field)
                result[field] = file_dict
            else:
                result[field] = None
        else:
            # Single file
            result[field] = _resolve_path(value, declared_outputs, prev_info, field)

    return result

def _resolve_path(path, declared_outputs, prev_info, field):
    """Resolve a path from state_out to a Bazel File.

    First checks if it matches a declared output (by basename).
    Then checks if it matches the previous value (unchanged).
    Fails if neither matches.
    """
    basename = path.rsplit("/", 1)[-1] if "/" in path else path

    # Check declared outputs first
    if basename in declared_outputs:
        return declared_outputs[basename]

    # Check if unchanged from previous state
    prev_value = getattr(prev_info, field, None) if prev_info else None
    if prev_value != None and prev_value.path == path:
        return prev_value

    # Also check if prev_value has same basename (path may differ between steps)
    if prev_value != None and prev_value.basename == basename:
        return prev_value

    fail("Cannot resolve path '{}' for field '{}'. Not in declared outputs or previous state.".format(path, field))

def get_pdk_files(pdk_info):
    """Get all files from a PdkInfo provider.

    Returns a list of File objects that should be inputs to the action.
    """
    files = []

    # Single files - core
    if pdk_info.fp_tracks_info:
        files.append(pdk_info.fp_tracks_info)
    if pdk_info.synth_excluded_cell_file:
        files.append(pdk_info.synth_excluded_cell_file)
    if pdk_info.pnr_excluded_cell_file:
        files.append(pdk_info.pnr_excluded_cell_file)

    # Single files - Magic
    if pdk_info.magicrc:
        files.append(pdk_info.magicrc)
    if pdk_info.magic_tech:
        files.append(pdk_info.magic_tech)
    if pdk_info.magic_pdk_setup:
        files.append(pdk_info.magic_pdk_setup)

    # Single files - KLayout
    if pdk_info.klayout_tech:
        files.append(pdk_info.klayout_tech)
    if pdk_info.klayout_properties:
        files.append(pdk_info.klayout_properties)
    if pdk_info.klayout_def_layer_map:
        files.append(pdk_info.klayout_def_layer_map)
    if pdk_info.klayout_drc_runset:
        files.append(pdk_info.klayout_drc_runset)

    # Single files - Netgen
    if pdk_info.netgen_setup:
        files.append(pdk_info.netgen_setup)

    # Single files - Synthesis maps
    if pdk_info.synth_latch_map:
        files.append(pdk_info.synth_latch_map)
    if pdk_info.synth_tristate_map:
        files.append(pdk_info.synth_tristate_map)
    if pdk_info.synth_csa_map:
        files.append(pdk_info.synth_csa_map)
    if pdk_info.synth_rca_map:
        files.append(pdk_info.synth_rca_map)
    if pdk_info.synth_fa_map:
        files.append(pdk_info.synth_fa_map)
    if pdk_info.synth_mux_map:
        files.append(pdk_info.synth_mux_map)
    if pdk_info.synth_mux4_map:
        files.append(pdk_info.synth_mux4_map)

    # List of files - core
    if pdk_info.cell_lefs:
        files.extend(pdk_info.cell_lefs)
    if pdk_info.cell_gds:
        files.extend(pdk_info.cell_gds)
    if pdk_info.cell_verilog_models:
        files.extend(pdk_info.cell_verilog_models)
    if pdk_info.cell_bb_verilog_models:
        files.extend(pdk_info.cell_bb_verilog_models)
    if pdk_info.cell_spice_models:
        files.extend(pdk_info.cell_spice_models)
    if pdk_info.gpio_pads_lef:
        files.extend(pdk_info.gpio_pads_lef)
    if pdk_info.gpio_pads_lef_core_side:
        files.extend(pdk_info.gpio_pads_lef_core_side)
    if pdk_info.gpio_pads_verilog:
        files.extend(pdk_info.gpio_pads_verilog)

    # List of files - Magic
    if pdk_info.cell_mags:
        files.extend(pdk_info.cell_mags)
    if pdk_info.cell_maglefs:
        files.extend(pdk_info.cell_maglefs)

    # Dict of corner -> File (tech_lefs)
    if pdk_info.tech_lefs:
        files.extend(pdk_info.tech_lefs.values())

    # Dict of corner -> File (rcx_rulesets)
    if pdk_info.rcx_rulesets:
        files.extend(pdk_info.rcx_rulesets.values())

    # Dict of corner -> list of Files (lib)
    if pdk_info.lib:
        for lib_files in pdk_info.lib.values():
            files.extend(lib_files)

    return files

def get_input_files(input_info, state_info):
    """Get all input files for a librelane step.

    Args:
        input_info: LibrelaneInput with flow configuration
        state_info: LibrelaneInfo with current design state (can be None for init)

    Returns a list of File objects that should be inputs to the action.
    """
    inputs = []

    # Add PDK files
    inputs.extend(get_pdk_files(input_info.pdk_info))

    # Add verilog files if present
    if input_info.verilog_files:
        inputs.extend(input_info.verilog_files.to_list())

    # Add custom SDC files if provided
    if input_info.pnr_sdc_file:
        inputs.append(input_info.pnr_sdc_file)
    if input_info.signoff_sdc_file:
        inputs.append(input_info.signoff_sdc_file)

    # Add macro files
    if input_info.macros:
        for macro in input_info.macros:
            if macro.lef:
                inputs.append(macro.lef)
            if macro.gds:
                inputs.append(macro.gds)
            if macro.netlist:
                inputs.append(macro.netlist)

    # Add state files if we have state from a previous step
    if state_info:
        # Add state_out from previous step (for metrics)
        if state_info.state_out:
            inputs.append(state_info.state_out)

        # Add single-file design views
        for field in STATE_FIELD_MAPPING.keys():
            if field in MULTI_FILE_FIELDS:
                continue
            value = getattr(state_info, field, None)
            if value != None:
                inputs.append(value)

        # Add multi-file design views (dicts)
        for field in MULTI_FILE_FIELDS:
            value = getattr(state_info, field, None)
            if value != None and type(value) == "dict":
                inputs.extend(value.values())

    return inputs


def get_verilog_paths(input_info, state_info):
    """Get verilog file paths - either synthesized netlist or input RTL."""
    if state_info and state_info.nl:
        return [state_info.nl.path]
    elif input_info.verilog_files:
        return [f.path for f in input_info.verilog_files.to_list()]
    else:
        return []

def get_macros_config(input_info):
    """Build MACROS config dict from MacroInfo list."""
    if not input_info.macros:
        return None

    macros_config = {}
    for macro in input_info.macros:
        macros_config[macro.name] = {
            "lef": [macro.lef.path] if macro.lef else [],
            "gds": [macro.gds.path] if macro.gds else [],
            "nl": [macro.netlist.path] if macro.netlist else [],
        }
    return macros_config

def librelane_output_path(filename, subdir = ""):
    """Get the path where librelane.steps writes a file (relative to design_dir).

    Args:
        filename: The filename to locate
        subdir: Subdirectory within runs/bazel/ where the file is written.
            Empty for most steps. CompositeSteps write to subdirectories
            (e.g., "1-diodeinsertion" for RepairAntennas).
    """
    if subdir:
        return "runs/bazel/" + subdir + "/" + filename
    return "runs/bazel/" + filename

def relative_path(file_path, base_dir):
    """Get the relative path of a file from a base directory."""
    if not file_path.startswith(base_dir + "/"):
        fail("File '{}' is not under base directory '{}'".format(file_path, base_dir))
    return file_path[len(base_dir) + 1:]

def run_librelane_step(
        ctx,
        step_id,
        outputs,
        config_content,
        inputs,
        input_info,
        state_info,
        output_subdir = ""):
    """Run a librelane step.

    Args:
        ctx: Rule context
        step_id: Librelane step ID (e.g., "Yosys.Synthesis")
        outputs: List of declared output Files (in target directory)
        config_content: JSON string for config
        inputs: List of input Files
        input_info: LibrelaneInput with flow configuration
        state_info: LibrelaneInfo from previous step (can be None for init)
        output_subdir: Subdirectory within runs/bazel/ where outputs are written.
            Empty for most steps, but CompositeSteps write to subdirectories
            (e.g., "1-diodeinsertion" for RepairAntennas).

    Returns:
        File - the state_out.json from this step
    """
    # Write config file in target-specific directory
    config_file = ctx.actions.declare_file(ctx.label.name + "/config.json")
    ctx.actions.write(output = config_file, content = config_content)

    # Design directory is the target-specific output directory
    design_dir = config_file.dirname

    # Generate state_in from state_info (has correct Bazel paths, no metrics yet)
    state_content = json.encode(serialize_state(state_info))
    state_in_base = ctx.actions.declare_file(ctx.label.name + "/state_in_base.json")
    ctx.actions.write(output = state_in_base, content = state_content)

    # Declare state_out as an output (we'll copy it from librelane)
    state_out = ctx.actions.declare_file(ctx.label.name + "/state_out.json")

    # Build copy commands to move files from librelane output to declared outputs
    copy_commands = []

    # Copy state_out.json (always at runs/bazel/state_out.json)
    copy_commands.append('cp "{design_dir}/{src}" "{dst}"'.format(
        design_dir = design_dir,
        src = librelane_output_path("state_out.json"),
        dst = state_out.path,
    ))

    # Copy each declared output from librelane's output location
    for output in outputs:
        rel_path = relative_path(output.path, design_dir)
        librelane_path = librelane_output_path(rel_path, output_subdir)
        copy_commands.append('mkdir -p "$(dirname "{dst}")" && cp "{design_dir}/{src}" "{dst}"'.format(
            design_dir = design_dir,
            src = librelane_path,
            dst = output.path,
        ))

    # Merge metrics from previous state_out into state_in at execution time
    if state_info and state_info.state_out:
        prev_state_out = state_info.state_out.path
        merge_metrics_cmd = 'jq -s \'.[0] * {{"metrics": .[1].metrics}}\' "{state_in_base}" "{prev_state_out}" > "{design_dir}/state_in.json"'.format(
            state_in_base = state_in_base.path,
            prev_state_out = prev_state_out,
            design_dir = design_dir,
        )
        state_in_path = design_dir + "/state_in.json"
    else:
        merge_metrics_cmd = ""
        state_in_path = state_in_base.path

    ctx.actions.run_shell(
        outputs = outputs + [state_out],
        inputs = inputs + [config_file, state_in_base],
        command = """
            set -e
            {merge_metrics_cmd}
            HOME="$(pwd)/{design_dir}" librelane.steps run \\
                --manual-pdk \\
                --pdk-root "$PDK_ROOT" \\
                --pdk {pdk} \\
                --scl {scl} \\
                --id {step_id} \\
                -c {config_file} \\
                -i "{state_in}" \\
                -o "$(pwd)/{design_dir}/runs/bazel"
            {copy_commands}
        """.format(
            merge_metrics_cmd = merge_metrics_cmd,
            pdk = input_info.pdk_info.name,
            scl = input_info.pdk_info.scl,
            config_file = config_file.path,
            state_in = state_in_path,
            step_id = step_id,
            design_dir = design_dir,
            copy_commands = "\n            ".join(copy_commands),
        ),
        use_default_shell_env = True,
    )

    return state_out

def single_step_impl(ctx, step_id, step_outputs, extra_config = {}, extra_inputs = [],
                     output_subdir = ""):
    """Run a librelane step with configurable outputs.

    Args:
        ctx: Rule context (must have 'src' and 'input' attributes)
        step_id: Librelane step ID
        extra_config: Additional config entries to merge
        extra_inputs: Additional input files (e.g., config files)
        step_outputs: List of outputs this step produces. Valid values:
            "def", "odb", "nl", "pnl", "sdc", "vh", "spef", "gds", "lef", etc.
            Use [] for checkers/reporters that don't produce outputs.
        output_subdir: Subdirectory within runs/bazel/ where outputs are written.
            Empty for most steps. CompositeSteps write to subdirectories
            (e.g., "1-diodeinsertion" for RepairAntennas).

    Returns:
        List of providers [DefaultInfo, LibrelaneInfo]
    """
    input_info = ctx.attr.input[LibrelaneInput]
    state_info = ctx.attr.src[LibrelaneInfo]
    top = input_info.top

    outputs = []

    # Declare outputs based on step_outputs list
    if "def" in step_outputs:
        def_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".def")
        outputs.append(def_out)
    else:
        def_out = getattr(state_info, "def", None)

    if "odb" in step_outputs:
        odb_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".odb")
        outputs.append(odb_out)
    else:
        odb_out = state_info.odb

    if "nl" in step_outputs:
        nl_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".nl.v")
        outputs.append(nl_out)
    else:
        nl_out = state_info.nl

    if "pnl" in step_outputs:
        pnl_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".pnl.v")
        outputs.append(pnl_out)
    else:
        pnl_out = state_info.pnl

    if "sdc" in step_outputs:
        sdc_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".sdc")
        outputs.append(sdc_out)
    else:
        sdc_out = state_info.sdc

    if "vh" in step_outputs:
        vh_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".vh")
        outputs.append(vh_out)
    else:
        vh_out = state_info.vh

    if "spef" in step_outputs:
        spef_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".spef")
        outputs.append(spef_out)
    else:
        spef_out = state_info.spef

    if "gds" in step_outputs:
        gds_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".gds")
        outputs.append(gds_out)
    else:
        gds_out = state_info.gds

    if "klayout_gds" in step_outputs:
        klayout_gds_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".klayout.gds")
        outputs.append(klayout_gds_out)
    else:
        klayout_gds_out = state_info.klayout_gds

    if "lef" in step_outputs:
        lef_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".lef")
        outputs.append(lef_out)
    else:
        lef_out = state_info.lef

    if "spice" in step_outputs:
        spice_out = ctx.actions.declare_file(ctx.label.name + "/" + top + ".spice")
        outputs.append(spice_out)
    else:
        spice_out = state_info.spice

    # Get input files
    inputs = get_input_files(input_info, state_info) + extra_inputs

    # Create config
    config = create_librelane_config(input_info, state_info)
    config.update(extra_config)

    # Run step
    state_out = run_librelane_step(
        ctx = ctx,
        step_id = step_id,
        outputs = outputs,
        config_content = json.encode(config),
        inputs = inputs,
        input_info = input_info,
        state_info = state_info,
        output_subdir = output_subdir,
    )

    # Build new LibrelaneInfo (state only - config stays in LibrelaneInput)
    default_files = outputs if outputs else [state_out]
    return [
        DefaultInfo(files = depset(default_files)),
        LibrelaneInfo(
            state_out = state_out,
            nl = nl_out,
            pnl = pnl_out,
            odb = odb_out,
            sdc = sdc_out,
            sdf = state_info.sdf,
            spef = spef_out,
            lib = state_info.lib,
            gds = gds_out,
            mag_gds = state_info.mag_gds,
            klayout_gds = klayout_gds_out,
            lef = lef_out,
            mag = state_info.mag,
            spice = spice_out,
            json_h = state_info.json_h,
            vh = vh_out,
            **{"def": def_out}
        ),
    ]

# Common attributes for rules that take a previous step as input
FLOW_ATTRS = {
    "src": attr.label(
        doc = "Previous flow step providing LibrelaneInfo (state)",
        mandatory = True,
        providers = [LibrelaneInfo],
    ),
    "input": attr.label(
        doc = "Init step providing LibrelaneInput (config)",
        mandatory = True,
        providers = [LibrelaneInput],
    ),
}

# Attributes for entry-point rules (init)
ENTRY_ATTRS = {
    "verilog_files": attr.label_list(
        doc = "Verilog/SystemVerilog source files",
        allow_files = [".v", ".sv"],
        mandatory = True,
    ),
    "top": attr.string(
        doc = "Top module name",
        mandatory = True,
    ),
    "clock_period": attr.string(
        doc = "Clock period in nanoseconds",
        default = "10.0",
    ),
    "clock_port": attr.string(
        doc = "Clock port name",
        default = "clock",
    ),
    "pdk": attr.label(
        doc = "PDK target providing PdkInfo",
        mandatory = True,
        providers = [PdkInfo],
    ),
    "macros": attr.label_list(
        doc = "Hard macro targets providing MacroInfo",
        default = [],
        providers = [MacroInfo],
    ),
    "pnr_sdc_file": attr.label(
        doc = "Custom SDC file for PnR timing constraints (optional)",
        allow_single_file = [".sdc"],
    ),
    "signoff_sdc_file": attr.label(
        doc = "Custom SDC file for signoff STA (optional)",
        allow_single_file = [".sdc"],
    ),
}

