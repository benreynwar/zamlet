# Validation rules - run librelane Classic flow as a single bundled invocation
#
# This rule takes the same attrs as librelane_classic_flow but with default = None,
# so we can detect which values the user explicitly set. Only non-None values are
# passed to librelane; for everything else, librelane uses its own defaults.
#
# This validates that Bazel flow defaults match librelane's native defaults.
#
# LIMITATION: Librelane's global placement (and possibly other steps) has non-deterministic
# behavior that cannot be controlled with a seed. This means ODB files from different runs
# may differ even with identical inputs. Comparison is only reliable for deterministic
# outputs like synthesis netlists and floorplan DEFs. Binary ODB comparison after global
# placement will likely fail even if the flows are functionally equivalent.

load(":providers.bzl", "PdkInfo")

# Attrs for bundled flow - same as ENTRY_ATTRS but with None defaults
# Required attrs keep their mandatory = True
BUNDLED_ATTRS = {
    # Required attrs
    "verilog_files": attr.label_list(
        doc = "Verilog/SystemVerilog source files",
        allow_files = [".v", ".sv"],
        mandatory = True,
    ),
    "top": attr.string(
        doc = "Top module name",
        mandatory = True,
    ),
    "pdk": attr.label(
        doc = "PDK target providing PdkInfo",
        mandatory = True,
        providers = [PdkInfo],
    ),
    # SDC template for delay constraints
    "_sdc_template": attr.label(
        default = "//bazel/flow/sdc:base.sdc",
        allow_single_file = [".sdc"],
    ),
    # Optional attrs with None default (to detect user overrides)
    "clock_period": attr.string(doc = "Clock period in nanoseconds"),
    "clock_port": attr.string(doc = "Clock port name"),
    "core_utilization": attr.string(doc = "Target core utilization percentage"),
    "die_area": attr.string(doc = "Die area as 'x0 y0 x1 y1'"),
    # IO delay constraints (percentage of clock period)
    "input_delay_constraint": attr.string(doc = "Input delay as percentage of clock period"),
    "output_delay_constraint": attr.string(doc = "Output delay as percentage of clock period"),
    # Synthesis
    "synth_strategy": attr.string(doc = "Synthesis optimization strategy"),
    "synth_autoname": attr.bool(doc = "Auto-generate names for unnamed cells"),
    "use_synlig": attr.bool(doc = "Use Synlig plugin for SystemVerilog"),
    # Linting
    "run_linter": attr.bool(doc = "Run Verilator linter"),
    # Add more as needed...
}

def _add_if_set(config, key, value):
    """Add to config only if value is set (not None and not empty string)."""
    if value != None and value != "":
        config[key] = value

def _bundled_flow_impl(ctx):
    """Run librelane Classic flow as a single bundled invocation."""

    pdk = ctx.attr.pdk[PdkInfo]

    # Build config with only user-specified values
    # Librelane will use its own defaults for anything not specified
    config = {
        # Always required
        "DESIGN_NAME": ctx.attr.top,
        "VERILOG_FILES": [f.path for f in ctx.files.verilog_files],
    }

    # Add optional values only if user specified them
    _add_if_set(config, "CLOCK_PORT", ctx.attr.clock_port)
    _add_if_set(config, "CLOCK_PERIOD", float(ctx.attr.clock_period) if ctx.attr.clock_period else None)
    _add_if_set(config, "FP_CORE_UTIL", ctx.attr.core_utilization)
    _add_if_set(config, "DIE_AREA", ctx.attr.die_area)
    _add_if_set(config, "SYNTH_STRATEGY", ctx.attr.synth_strategy)
    _add_if_set(config, "SYNTH_AUTONAME", ctx.attr.synth_autoname)
    _add_if_set(config, "USE_SYNLIG", ctx.attr.use_synlig)
    _add_if_set(config, "RUN_LINTER", ctx.attr.run_linter)

    # Handle SDC generation for delay constraints
    input_delay = ctx.attr.input_delay_constraint
    output_delay = ctx.attr.output_delay_constraint
    generate_sdc = input_delay or output_delay
    sdc_generation_script = ""
    if generate_sdc:
        effective_input_delay = input_delay if input_delay else "50"
        effective_output_delay = output_delay if output_delay else "50"
        # Generate SDC by reading template and substituting placeholders
        sdc_generation_script = """
# Generate SDC from template
sed -e 's/{{{{INPUT_DELAY_CONSTRAINT}}}}/{input_delay}/' \\
    -e 's/{{{{OUTPUT_DELAY_CONSTRAINT}}}}/{output_delay}/' \\
    "{sdc_template}" > "$DESIGN_DIR/constraints.sdc"
""".format(
            input_delay = effective_input_delay,
            output_delay = effective_output_delay,
            sdc_template = ctx.file._sdc_template.path,
        )
        # Tell librelane to use the generated SDC (dir:: makes path relative to config file)
        config["PNR_SDC_FILE"] = "dir::constraints.sdc"
        config["SIGNOFF_SDC_FILE"] = "dir::constraints.sdc"

    # Declare outputs - just the directory, files inside are implicit
    out_dir = ctx.actions.declare_directory(ctx.label.name)

    # Collect input files
    inputs = list(ctx.files.verilog_files)
    inputs.extend(pdk.cell_lefs)
    inputs.extend(pdk.cell_gds)
    if pdk.synth_excluded_cell_file:
        inputs.append(pdk.synth_excluded_cell_file)
    if pdk.pnr_excluded_cell_file:
        inputs.append(pdk.pnr_excluded_cell_file)
    for files in pdk.lib.values():
        inputs.extend(files)
    for f in pdk.tech_lefs.values():
        inputs.append(f)
    inputs.append(pdk.fp_tracks_info)
    if generate_sdc:
        inputs.append(ctx.file._sdc_template)

    top = ctx.attr.top
    pdk_name = pdk.name
    scl = pdk.scl

    script = """#!/bin/bash
set -e

DESIGN_DIR="{design_dir}"
mkdir -p "$DESIGN_DIR"
{sdc_generation}
# Write config.json
cat > "$DESIGN_DIR/config.json" << 'CONFIGEOF'
{config_json}
CONFIGEOF

# Run librelane Classic flow through global placement (checkpoint 3)
if ! librelane "$DESIGN_DIR/config.json" \\
    --manual-pdk \\
    --pdk-root "$PDK_ROOT" \\
    --pdk {pdk} \\
    --scl {scl} \\
    --run-tag bundled \\
    --to OpenROAD.GlobalPlacement \\
    --overwrite; then
    echo "=== LIBRELANE FAILED ==="
    echo "Flow log:"
    cat "$DESIGN_DIR/runs/bundled/flow.log" 2>/dev/null || echo "No flow.log"
    exit 1
fi

RUNDIR="$DESIGN_DIR/runs/bundled"

# Checkpoint 1: Synthesis netlist
SYNTH_DIR=$(ls -d "$RUNDIR"/*-yosys-synthesis 2>/dev/null | head -1)
if [ -d "$SYNTH_DIR" ]; then
    cp "$SYNTH_DIR"/{top}.nl.v "$DESIGN_DIR/synth.nl.v"
else
    echo "ERROR: Synthesis output not found"
    exit 1
fi
echo "Checkpoint 1 (Yosys.Synthesis) complete"

# Checkpoint 2: Floorplan DEF
FP_DIR=$(ls -d "$RUNDIR"/*-openroad-floorplan 2>/dev/null | head -1)
if [ -d "$FP_DIR" ]; then
    cp "$FP_DIR"/{top}.def "$DESIGN_DIR/floorplan.def"
else
    echo "ERROR: Floorplan output not found"
    exit 1
fi
echo "Checkpoint 2 (OpenROAD.Floorplan) complete"

# Checkpoint 3: Global Placement ODB
GPL_DIR=$(ls -d "$RUNDIR"/*-openroad-globalplacement 2>/dev/null | head -1)
if [ -d "$GPL_DIR" ]; then
    cp "$GPL_DIR"/{top}.odb "$DESIGN_DIR/gpl.odb"
else
    echo "ERROR: Global placement output not found"
    exit 1
fi
echo "Checkpoint 3 (OpenROAD.GlobalPlacement) complete"
""".format(
        design_dir = out_dir.path,
        sdc_generation = sdc_generation_script,
        config_json = json.encode_indent(config, indent = "  "),
        pdk = pdk_name,
        scl = scl,
        top = top,
    )

    ctx.actions.run_shell(
        outputs = [out_dir],
        inputs = inputs,
        command = script,
        use_default_shell_env = True,
        mnemonic = "LibrelaneBundled",
        progress_message = "Running librelane bundled flow (checkpoints 1-3: synthesis, floorplan, gpl)",
    )

    return [
        DefaultInfo(files = depset([out_dir])),
    ]

librelane_classic_bundled_flow = rule(
    implementation = _bundled_flow_impl,
    attrs = BUNDLED_ATTRS,
    doc = "Run librelane Classic flow as a single bundled invocation for validation",
)

# Comparison test - compare bundled flow output with Bazel flow output
def _compare_flows_test_impl(ctx):
    """Compare outputs from bundled flow and Bazel flow."""
    bundled_dir = ctx.file.bundled
    all_inputs = [bundled_dir]

    # Find the .nl.v file from bazel_synth outputs
    bazel_synth = None
    for f in ctx.files.bazel_synth:
        if f.path.endswith(".nl.v"):
            bazel_synth = f
            break
    if not bazel_synth:
        fail("No .nl.v file found in bazel_synth target")
    all_inputs.extend(ctx.files.bazel_synth)

    # Find the .def file from bazel_floorplan outputs (optional)
    bazel_floorplan = None
    if ctx.files.bazel_floorplan:
        for f in ctx.files.bazel_floorplan:
            if f.path.endswith(".def"):
                bazel_floorplan = f
                break
        all_inputs.extend(ctx.files.bazel_floorplan)

    # Find the .odb file from bazel_gpl outputs (optional)
    bazel_gpl = None
    if ctx.files.bazel_gpl:
        for f in ctx.files.bazel_gpl:
            if f.path.endswith(".odb"):
                bazel_gpl = f
                break
        all_inputs.extend(ctx.files.bazel_gpl)

    # Build comparison script
    comparisons = []
    comparisons.append("""
echo "=== Checkpoint 1: Synthesis Netlist ==="
echo "Bundled: {bundled_dir}/synth.nl.v"
echo "Bazel:   {bazel_synth}"
if diff -u "{bundled_dir}/synth.nl.v" "{bazel_synth}"; then
    echo "PASS: Synthesis netlists match"
else
    echo "FAIL: Synthesis netlists differ"
    FAILED=1
fi
""".format(bundled_dir = bundled_dir.short_path, bazel_synth = bazel_synth.short_path))

    if bazel_floorplan:
        comparisons.append("""
echo ""
echo "=== Checkpoint 2: Floorplan DEF ==="
echo "Bundled: {bundled_dir}/floorplan.def"
echo "Bazel:   {bazel_floorplan}"
if diff -u "{bundled_dir}/floorplan.def" "{bazel_floorplan}"; then
    echo "PASS: Floorplan DEFs match"
else
    echo "FAIL: Floorplan DEFs differ"
    FAILED=1
fi
""".format(bundled_dir = bundled_dir.short_path, bazel_floorplan = bazel_floorplan.short_path))

    if bazel_gpl:
        comparisons.append("""
echo ""
echo "=== Checkpoint 3: Global Placement ODB ==="
echo "Bundled: {bundled_dir}/gpl.odb"
echo "Bazel:   {bazel_gpl}"
if diff "{bundled_dir}/gpl.odb" "{bazel_gpl}"; then
    echo "PASS: Global placement ODBs match"
else
    echo "FAIL: Global placement ODBs differ"
    FAILED=1
fi
""".format(bundled_dir = bundled_dir.short_path, bazel_gpl = bazel_gpl.short_path))

    script_content = """#!/bin/bash
FAILED=0
{comparisons}
echo ""
if [ $FAILED -eq 0 ]; then
    echo "All checkpoints PASS"
    exit 0
else
    echo "Some checkpoints FAILED"
    exit 1
fi
""".format(comparisons = "".join(comparisons))

    script = ctx.actions.declare_file(ctx.label.name + ".sh")
    ctx.actions.write(script, script_content, is_executable = True)

    runfiles = ctx.runfiles(files = all_inputs)

    return [DefaultInfo(executable = script, runfiles = runfiles)]

librelane_compare_flows_test = rule(
    implementation = _compare_flows_test_impl,
    test = True,
    attrs = {
        "bundled": attr.label(
            mandatory = True,
            allow_single_file = True,
            doc = "Bundled flow output directory",
        ),
        "bazel_synth": attr.label(
            mandatory = True,
            allow_files = [".v"],
            doc = "Bazel flow synthesis netlist (picks first .nl.v file from target)",
        ),
        "bazel_floorplan": attr.label(
            allow_files = [".def"],
            doc = "Bazel flow floorplan DEF (optional, picks first .def file from target)",
        ),
        "bazel_gpl": attr.label(
            allow_files = [".odb"],
            doc = "Bazel flow global placement ODB (optional, picks first .odb file from target)",
        ),
    },
    doc = "Test that bundled flow output matches Bazel flow output",
)
