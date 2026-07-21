# Cocotb build rules using Nix toolchains
# Based on rules_cocotb_verilator patterns, adapted for Nix toolchains

load("@bazel_tools//tools/cpp:toolchain_utils.bzl", "find_cpp_toolchain")
load("@rules_cc//cc:defs.bzl", "cc_binary", "CcInfo")
load("//bazel:verilog.bzl", "chisel_verilog", "chisel_verilog_no_config")

# -----------------------------------------------------------------------------
# verilate rule - compiles Verilog to C++ library using verilator toolchain
# -----------------------------------------------------------------------------

def _verilate_impl(ctx):
    verilator_tc = ctx.toolchains["//bazel/toolchains:verilator_toolchain_type"].verilator

    # Collect input verilog files
    input_files = []
    for src in ctx.attr.srcs:
        input_files.extend(src.files.to_list())

    input_paths = " ".join([f.path for f in input_files])

    # Declare output directories
    verilator_output = ctx.actions.declare_directory(ctx.attr.name + "_verilated")
    cpp_output = ctx.actions.declare_directory(ctx.attr.name + "_cpp")
    hpp_output = ctx.actions.declare_directory(ctx.attr.name + "_hpp")

    output_split_args = ""
    if ctx.attr.output_split > 0:
        output_split_args += " --output-split %d" % ctx.attr.output_split
    if ctx.attr.output_split_cfuncs > 0:
        output_split_args += " --output-split-cfuncs %d" % ctx.attr.output_split_cfuncs
    if ctx.attr.output_split_ctrace > 0:
        output_split_args += " --output-split-ctrace %d" % ctx.attr.output_split_ctrace

    # Run verilator
    ctx.actions.run_shell(
        outputs = [verilator_output],
        inputs = input_files,
        command = """{verilator} --cc --vpi --public-flat-rw \
            --timescale 1ns/1ps --trace \
            {output_split_args} \
            --prefix Vtop \
            --Mdir {out_dir} \
            --top-module {module_top} \
            {inputs}
        """.format(
            verilator = verilator_tc.verilator_bin,
            output_split_args = output_split_args,
            out_dir = verilator_output.path,
            module_top = ctx.attr.module_top,
            inputs = input_paths,
        ),
        mnemonic = "Verilate",
        progress_message = "Verilating %s" % ctx.attr.module_top,
    )

    # Separate cpp and hpp files
    ctx.actions.run_shell(
        outputs = [cpp_output, hpp_output],
        inputs = [verilator_output],
        command = """
            mkdir -p {cpp_dir} {hpp_dir}
            for f in {verilator_dir}/*.cpp {verilator_dir}/*.cc; do
                [ -f "$f" ] && cp "$f" {cpp_dir}/ || true
            done
            for f in {verilator_dir}/*.h {verilator_dir}/*.hpp; do
                [ -f "$f" ] && cp "$f" {hpp_dir}/ || true
            done
        """.format(
            verilator_dir = verilator_output.path,
            cpp_dir = cpp_output.path,
            hpp_dir = hpp_output.path,
        ),
        mnemonic = "VerilatorSeparate",
    )

    # Compile with cc_common
    cc_toolchain = find_cpp_toolchain(ctx)
    feature_configuration = cc_common.configure_features(
        ctx = ctx,
        cc_toolchain = cc_toolchain,
        requested_features = ctx.features,
        unsupported_features = ctx.disabled_features,
    )

    compilation_contexts = [dep[CcInfo].compilation_context for dep in ctx.attr.deps]

    compilation_context, compilation_outputs = cc_common.compile(
        name = ctx.attr.name,
        actions = ctx.actions,
        feature_configuration = feature_configuration,
        cc_toolchain = cc_toolchain,
        user_compile_flags = ["-std=c++17", "-faligned-new"],
        srcs = [cpp_output],
        includes = [hpp_output.path],
        defines = ["VM_TRACE"],
        public_hdrs = [hpp_output],
        compilation_contexts = compilation_contexts,
    )

    linking_contexts = [dep[CcInfo].linking_context for dep in ctx.attr.deps]
    linking_context, linking_output = cc_common.create_linking_context_from_compilation_outputs(
        actions = ctx.actions,
        feature_configuration = feature_configuration,
        cc_toolchain = cc_toolchain,
        compilation_outputs = compilation_outputs,
        linking_contexts = linking_contexts,
        name = ctx.attr.name,
        disallow_dynamic_library = True,
    )

    output_files = []
    if linking_output.library_to_link and linking_output.library_to_link.static_library:
        output_files.append(linking_output.library_to_link.static_library)

    return [
        DefaultInfo(files = depset(output_files)),
        CcInfo(
            compilation_context = compilation_context,
            linking_context = linking_context,
        ),
    ]

verilate = rule(
    implementation = _verilate_impl,
    attrs = {
        "srcs": attr.label_list(allow_files = [".v", ".sv"]),
        "module_top": attr.string(mandatory = True),
        "deps": attr.label_list(providers = [CcInfo]),
        "output_split": attr.int(default = 20000),
        "output_split_cfuncs": attr.int(default = 20000),
        "output_split_ctrace": attr.int(default = 20000),
        "_cc_toolchain": attr.label(
            default = Label("@bazel_tools//tools/cpp:current_cc_toolchain"),
        ),
    },
    toolchains = [
        "//bazel/toolchains:verilator_toolchain_type",
        "@bazel_tools//tools/cpp:toolchain_type",
    ],
    fragments = ["cpp"],
    provides = [CcInfo, DefaultInfo],
)

# -----------------------------------------------------------------------------
# python_runner rule - sets up Python environment for cocotb
# Based on rules_cocotb_verilator's python_runner, with toolchain for Nix paths
# -----------------------------------------------------------------------------

def _python_runner_impl(ctx):
    cocotb_tc = ctx.toolchains["//bazel/toolchains:cocotb_toolchain_type"].cocotb

    # Collect import paths from PyInfo (following rules_cocotb_verilator pattern)
    import_paths = []
    all_runfiles = ctx.runfiles()

    for py_dep in ctx.attr.py_deps:
        if PyInfo in py_dep:
            py_info = py_dep[PyInfo]
            import_paths.extend(py_info.imports.to_list())

        if DefaultInfo in py_dep:
            all_runfiles = all_runfiles.merge(py_dep[DefaultInfo].default_runfiles)

    # Get the binary
    binary = ctx.attr.binary[DefaultInfo].files_to_run.executable

    config_file = None
    if ctx.attr.config:
        config_files = ctx.attr.config[DefaultInfo].files.to_list()
        if len(config_files) != 1:
            fail("config must produce exactly one file")
        config_file = config_files[0]

    # Build PYTHONPATH entries (relative to runfiles)
    python_paths = ["."]
    for path in import_paths:
        if path and path != ".":
            python_paths.append(path)
    python_paths.append(ctx.workspace_name)

    # Generate runner script
    wrapper_script = ctx.actions.declare_file(ctx.label.name + "_runner.sh")

    script_content = """#!/bin/bash
# Auto-generated cocotb runner with Nix toolchain paths

RUNFILES_DIR="."

# Set up PYTHONPATH with runfiles-relative paths
PYTHONPATH_PARTS=()
PYTHONPATH_PARTS+=("$RUNFILES_DIR")
{pythonpath_exports}

# Make paths absolute
ABSOLUTE_PARTS=()
for part in "${{PYTHONPATH_PARTS[@]}}"; do
    if [[ "$part" == "." ]]; then
        ABSOLUTE_PARTS+=("$(pwd)")
    else
        ABSOLUTE_PARTS+=("$(pwd)/$part")
    fi
done

IFS=':'; export PYTHONPATH="${{ABSOLUTE_PARTS[*]}}:$PYTHONPATH"

# LD_LIBRARY_PATH for cocotb to dlopen libpython (Nix libs have wrong rpaths)
export LD_LIBRARY_PATH="{python_libdir}:$LD_LIBRARY_PATH"

# Python interpreter for cocotb
export PYGPI_PYTHON_BIN="{python_bin}"

# Cocotb environment
export COCOTB_RESOLVE_X=VALUE_ERROR
export ZAMLET_TEST_SEED="${{ZAMLET_TEST_SEED:-0}}"
{config_export}

# Run simulation
if [ "$VERILATOR_TRACE" = "1" ]; then
    "$RUNFILES_DIR/{binary_path}" --trace "$@"
else
    "$RUNFILES_DIR/{binary_path}" "$@"
fi

# Copy VCD to test outputs
if [ -n "$TEST_UNDECLARED_OUTPUTS_DIR" ] && [ -f "dump.vcd" ]; then
    cp "dump.vcd" "$TEST_UNDECLARED_OUTPUTS_DIR/"
fi

# Check for results.xml
if [ ! -f results.xml ]; then
    echo "ERROR: results.xml not found - cocotb test did not complete"
    exit 1
fi

# Parse results
python3 -c "
import sys
import xml.etree.ElementTree as ET
try:
    tree = ET.parse('results.xml')
    root = tree.getroot()
    total = 0
    failed = 0
    for tc in root.findall('.//testcase'):
        total += 1
        if tc.find('failure') is not None or tc.find('error') is not None:
            failed += 1
    if failed > 0:
        print(f'FAILED: {{failed}}/{{total}} tests failed', file=sys.stderr)
        sys.exit(1)
    else:
        print(f'PASSED: {{total}} tests')
except Exception as e:
    print(f'Failed to parse results.xml: {{e}}', file=sys.stderr)
    sys.exit(1)
"
""".format(
        pythonpath_exports = "\n".join([
            'PYTHONPATH_PARTS+=("../{}")'.format(path)
            for path in python_paths if path != "."
        ]),
        python_libdir = cocotb_tc.python_libdir,
        python_bin = cocotb_tc.python_bin,
        binary_path = binary.short_path,
        config_export = (
            'export ZAMLET_TEST_CONFIG_FILENAME="{config_path}"'.format(
                config_path = config_file.short_path,
            ) if config_file else ""
        ),
    )

    ctx.actions.write(
        output = wrapper_script,
        content = script_content,
        is_executable = True,
    )

    # Merge runfiles
    binary_runfiles = ctx.attr.binary[DefaultInfo].default_runfiles
    runfiles = binary_runfiles.merge(all_runfiles)
    runfiles = runfiles.merge(ctx.runfiles(files = [binary]))
    if config_file:
        runfiles = runfiles.merge(ctx.runfiles(files = [config_file]))

    return [
        DefaultInfo(
            executable = wrapper_script,
            runfiles = runfiles,
        ),
    ]

python_runner = rule(
    implementation = _python_runner_impl,
    attrs = {
        "binary": attr.label(
            mandatory = True,
            executable = True,
            cfg = "target",
        ),
        "config": attr.label(allow_files = [".json"]),
        "py_deps": attr.label_list(),
    },
    executable = True,
    toolchains = ["//bazel/toolchains:cocotb_toolchain_type"],
)

def _cvc_runner_impl(ctx):
    cocotb_tc = ctx.toolchains["//bazel/toolchains:cocotb_toolchain_type"].cocotb

    import_paths = []
    runfiles = ctx.runfiles(
        files = ctx.files.srcs + [ctx.file._cvc, ctx.file._vpi] + ctx.files._cvc_runtime,
    )
    for py_dep in ctx.attr.py_deps:
        if PyInfo in py_dep:
            import_paths.extend(py_dep[PyInfo].imports.to_list())
        if DefaultInfo in py_dep:
            runfiles = runfiles.merge(py_dep[DefaultInfo].default_runfiles)

    config_file = None
    if ctx.attr.config:
        config_files = ctx.attr.config[DefaultInfo].files.to_list()
        if len(config_files) != 1:
            fail("config must produce exactly one file")
        config_file = config_files[0]
        runfiles = runfiles.merge(ctx.runfiles(files = [config_file]))

    python_paths = [ctx.workspace_name]
    python_paths.extend([path for path in import_paths if path and path != "."])
    wrapper = ctx.actions.declare_file(ctx.label.name + ".sh")
    ctx.actions.write(
        output = wrapper,
        is_executable = True,
        content = """#!/bin/bash
set -euo pipefail

PYTHONPATH_PARTS=("$(pwd)")
{pythonpath_entries}
IFS=':'; export PYTHONPATH="${{PYTHONPATH_PARTS[*]}}:${{PYTHONPATH:-}}"
export LD_LIBRARY_PATH="$(dirname "{vpi}"):{python_libdir}:${{LD_LIBRARY_PATH:-}}"
export PYGPI_PYTHON_BIN="{python_bin}"
export COCOTB_RESOLVE_X=VALUE_ERROR
export ZAMLET_TEST_SEED="${{ZAMLET_TEST_SEED:-0}}"
{config_export}

"{cvc}" +interp +acc+2 ${{CVC_ARGS:-}} -o cvc_sim \
  "+loadvpi={vpi}:vlog_startup_routines_bootstrap" \
  {sources}

if [ -f verilog.dump ]; then
  cp verilog.dump "$TEST_UNDECLARED_OUTPUTS_DIR/dump.vcd"
fi

test -f results.xml || {{
  echo "ERROR: results.xml not found - cocotb test did not complete" >&2
  exit 1
}}
"{python_bin}" -m cocotb_tools.check_results results.xml
""".format(
            cvc = ctx.file._cvc.short_path,
            vpi = ctx.file._vpi.short_path,
            sources = " ".join([src.short_path for src in ctx.files.srcs]),
            python_libdir = cocotb_tc.python_libdir,
            python_bin = cocotb_tc.python_bin,
            pythonpath_entries = "\n".join([
                'PYTHONPATH_PARTS+=("$(pwd)/../{}")'.format(path)
                for path in python_paths
            ]),
            config_export = (
                'export ZAMLET_TEST_CONFIG_FILENAME="{}"'.format(config_file.short_path)
                if config_file else ""
            ),
        ),
    )

    return [DefaultInfo(executable = wrapper, runfiles = runfiles)]

cvc_runner = rule(
    implementation = _cvc_runner_impl,
    attrs = {
        "srcs": attr.label_list(allow_files = [".v", ".sv"]),
        "config": attr.label(allow_files = [".json"]),
        "py_deps": attr.label_list(),
        "_cvc": attr.label(
            default = Label("@nix_cvc//:cvc_bin"),
            allow_single_file = True,
        ),
        "_vpi": attr.label(
            default = Label("@nix_cocotb//:cvc_vpi"),
            allow_single_file = True,
        ),
        "_cvc_runtime": attr.label(
            default = Label("@nix_cocotb//:cvc_runtime"),
        ),
    },
    executable = True,
    toolchains = ["//bazel/toolchains:cocotb_toolchain_type"],
)

# -----------------------------------------------------------------------------
# Convenience macros
# -----------------------------------------------------------------------------

def cocotb_binary(name, verilog_files, module_top):
    """Create a cocotb simulation binary.

    Args:
        name: Name for the binary target
        verilog_files: List of Verilog source files
        module_top: Top-level module name
    """
    verilate(
        name = name + "_verilated",
        srcs = verilog_files,
        module_top = module_top,
        deps = ["@nix_verilator//:verilator_includes"],
    )

    cc_binary(
        name = name,
        srcs = [
            "@nix_verilator//:verilator_sources",
            "@nix_cocotb//:verilator_cpp",
        ],
        copts = ["-std=c++17"],
        linkopts = ["-Wl,--allow-shlib-undefined"],
        deps = [
            ":" + name + "_verilated",
            "@nix_cocotb//:cocotb_headers",
            "@nix_cocotb//:cocotb_libs",
            "@nix_cocotb//:python_libs",
        ],
        visibility = ["//visibility:public"],
    )


def cocotb_test(name, binary, test_module, toplevel, py_deps = [], env = {}, data = [], config = None):
    """Create a cocotb test.

    Args:
        name: Test name
        binary: The cocotb_binary target
        test_module: Python module name (e.g. "zamlet.maths_test.test_wallace")
        toplevel: Top-level Verilog module name
        py_deps: Python library dependencies
        env: Additional environment variables
        data: Additional data files
        config: Optional JSON config label exposed as ZAMLET_TEST_CONFIG_FILENAME
    """
    python_runner(
        name = name + "_runner",
        binary = binary,
        config = config,
        py_deps = py_deps,
    )

    default_env = {
        "COCOTB_TEST_MODULES": test_module,
        "TOPLEVEL": toplevel,
        "TOPLEVEL_LANG": "verilog",
        "VERILATOR_TRACE": "1",
    }
    merged_env = dict(default_env)
    merged_env.update(env)

    native.sh_test(
        name = name,
        srcs = [name + "_runner"],
        env = merged_env,
        data = data + ([config] if config else []),
    )

def cvc_cocotb_test(name, verilog_files, test_module, toplevel, py_deps = [], env = {}, data = [], config = None):
    """Create a cocotb test that runs Verilog directly with CVC."""
    cvc_runner(
        name = name + "_runner",
        srcs = verilog_files,
        config = config,
        py_deps = py_deps,
    )

    default_env = {
        "COCOTB_TEST_MODULES": test_module,
        "COCOTB_TOPLEVEL": toplevel,
        "TOPLEVEL": toplevel,
        "TOPLEVEL_LANG": "verilog",
    }
    merged_env = dict(default_env)
    merged_env.update(env)

    native.sh_test(
        name = name,
        srcs = [name + "_runner"],
        env = merged_env,
        data = data + ([config] if config else []),
    )


_DEFAULT_CONFIG = "//configs:zamlet_default.json"

_TAG_ALLOWED = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"

def _sanitize_tag(s):
    out = ""
    for i in range(len(s)):
        c = s[i]
        out += c if c in _TAG_ALLOWED else "_"
    return out

def _normalize_entry(entry):
    """Return (module, filter, suffix) for a test_modules list entry.

    Accepts either a Python module string or a (module, filter) 2-tuple.
    """
    if type(entry) == "string":
        suffix = entry.split(".")[-1]
        if suffix.startswith("test_"):
            suffix = suffix[5:]
        return entry, None, suffix
    if type(entry) == "tuple" and len(entry) == 2:
        mod, filt = entry
        return mod, filt, _sanitize_tag(filt)
    fail("test_modules entry must be a string or a (module, filter) tuple")

def chisel_module_tests(
        generator,
        toplevel,
        srcs,
        test_modules,
        configs = None,
        py_deps = None):
    """Emit Verilog generation + cocotb tests for one Chisel module.

    For each (tag, label) in `configs`, emits a chisel_verilog genrule and a
    cocotb_binary. For each (config, test_module) pair, emits a cocotb_test.
    A shared py_library holds `srcs`. A test_suite `:{toplevel}_tests`
    aggregates every generated cocotb_test. All target names are prefixed by
    the lowercased toplevel.

    Args:
        generator: Chisel generator binary label.
        toplevel: top-module name (used by Verilator and as DUT name).
        srcs: shared Python sources for the test py_library.
        test_modules: list of entries; each entry is either a Python module
            string (e.g. "zamlet.foo_test.test_foo") or a
            (module, filter) 2-tuple, where `filter` is set as
            COCOTB_TEST_FILTER to select specific @cocotb.test functions.
        configs: list of (tag, label) pairs; defaults to one entry tagged
            "default" with //configs:zamlet_default.json.
        py_deps: extra py_library deps beyond //python/zamlet:zamlet.
    """
    configs = configs or [("default", _DEFAULT_CONFIG)]
    base = toplevel.lower()

    native.py_library(
        name = base + "_py",
        srcs = srcs,
        deps = ["//python/zamlet:zamlet"] + (py_deps or []),
    )

    entries = [_normalize_entry(e) for e in test_modules]
    include_suffix = len(entries) > 1

    test_targets = []

    for cfg_tag, cfg_label in configs:
        cfg_base = "{}_{}".format(base, cfg_tag)
        chisel_verilog(
            name = cfg_base,
            generator = generator,
            config = cfg_label,
        )
        cocotb_binary(
            name = cfg_base + "_exe",
            verilog_files = [":" + cfg_base + "_verilog"],
            module_top = toplevel,
        )

        for mod, filt, sfx in entries:
            if include_suffix:
                test_name = "test_{}_{}".format(cfg_base, sfx)
            else:
                test_name = "test_" + cfg_base

            env = {}
            if filt:
                env["COCOTB_TEST_FILTER"] = filt

            cocotb_test(
                name = test_name,
                binary = ":" + cfg_base + "_exe",
                test_module = mod,
                toplevel = toplevel,
                py_deps = [":" + base + "_py"],
                env = env,
                config = cfg_label,
            )
            test_targets.append(":" + test_name)

    native.test_suite(name = base + "_tests", tests = test_targets)

def chisel_module_tests_no_config(
        generator,
        toplevel,
        srcs,
        test_modules,
        generator_args = None,
        py_deps = None,
        config = None):
    """Emit Verilog generation + cocotb tests for a configless Chisel module."""
    base = toplevel.lower()
    generator_args = generator_args or []

    native.py_library(
        name = base + "_py",
        srcs = srcs,
        deps = ["//python/zamlet:zamlet"] + (py_deps or []),
    )

    chisel_verilog_no_config(
        name = base,
        generator = generator,
        extra_args = generator_args,
    )
    cocotb_binary(
        name = base + "_exe",
        verilog_files = [":" + base + "_verilog"],
        module_top = toplevel,
    )

    entries = [_normalize_entry(e) for e in test_modules]
    include_suffix = len(entries) > 1
    test_targets = []

    for mod, filt, sfx in entries:
        if include_suffix:
            test_name = "test_{}_{}".format(base, sfx)
        else:
            test_name = "test_" + base

        env = {}
        if filt:
            env["COCOTB_TEST_FILTER"] = filt

        cocotb_test(
            name = test_name,
            binary = ":" + base + "_exe",
            test_module = mod,
            toplevel = toplevel,
            py_deps = [":" + base + "_py"],
            env = env,
            config = config,
        )
        test_targets.append(":" + test_name)

    native.test_suite(name = base + "_tests", tests = test_targets)
