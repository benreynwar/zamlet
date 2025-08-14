"""Cocotb test rule for running cocotb tests.

Based on bazel_rules_hdl/cocotb/cocotb.bzl
Copyright 2023 Antmicro, Licensed under Apache License 2.0
"""

load("@rules_python//python:defs.bzl", "PyInfo")
load("//bazel/cocotb:cocotb_common.bzl", "get_pythonpath_to_set")

def _cocotb_test_impl(ctx):
    """Implementation of cocotb_test rule."""
    # Get the binary target
    binary_executable = ctx.attr.binary[DefaultInfo].files_to_run.executable
    binary_runfiles = ctx.attr.binary[DefaultInfo].default_runfiles

    # Create a test wrapper script that sets up cocotb environment
    test_script = ctx.actions.declare_file(ctx.label.name + "_test.sh")
    
    # Get test module names from the test_module attribute
    test_modules = [f.basename.removesuffix(".py") for f in ctx.files.test_module]
    
    script_content = '''#!/bin/bash
# Generated cocotb test script

# Set up test environment
export TEST_TMPDIR="${{TEST_TMPDIR:-$(mktemp -d)}}"
export TEST_WORKSPACE="${{TEST_WORKSPACE:-$PWD}}"

# Set up cocotb environment variables (what cocotb makefile sets)
export MODULE="{modules}"
export COCOTB_TEST_MODULES="{modules}"
export COCOTB_TOPLEVEL="{toplevel}"
export TOPLEVEL_LANG="verilog"

# Set up custom environment variables
{env_vars}

# Set up Python path for cocotb to find test modules
export PYTHONPATH="{pythonpath}:${{PYTHONPATH:-}}"

# Set cocotb results file location
export COCOTB_RESULTS_FILE="${{TEST_TMPDIR}}/results.xml"

# Run the cocotb executable
"{binary}" "$@"
exit_code=$?

# Check cocotb results - if no results file, the test failed to run properly
if [ ! -f "$COCOTB_RESULTS_FILE" ]; then
    echo "Test failed: No results.xml generated - cocotb test did not run properly" >&2
    exit 1
fi

# Parse results.xml to check for test failures
python3 -c "
import sys
import xml.etree.ElementTree as ET
try:
    tree = ET.parse('$COCOTB_RESULTS_FILE')
    root = tree.getroot()
    
    total_tests = 0
    failed_tests = 0
    
    for testcase in root.findall('.//testcase'):
        total_tests += 1
        if testcase.find('failure') is not None or testcase.find('error') is not None:
            failed_tests += 1
    
    if failed_tests > 0:
        print(f'Test failed: {{failed_tests}} out of {{total_tests}} tests failed', file=sys.stderr)
        sys.exit(1)
    else:
        print(f'All tests passed: {{total_tests}} tests completed successfully')
        
except Exception as e:
    print(f'Failed to parse results.xml: {{e}}', file=sys.stderr)
    sys.exit(1)
"
'''.format(
        binary = binary_executable.short_path,
        modules = ",".join(test_modules) if test_modules else "test",
        toplevel = ctx.attr.hdl_toplevel,
        pythonpath = get_pythonpath_to_set(ctx),
        env_vars = "\n".join(["export {}=\"{}\"".format(k, v) for k, v in ctx.attr.env.items()])
    )

    ctx.actions.write(
        output = test_script,
        content = script_content,
        is_executable = True,
    )

    # Set up runfiles
    runfiles = ctx.runfiles(files = [binary_executable] + ctx.files.data).merge(binary_runfiles)

    # Set up test environment with cocotb variables
    env = {
        "PYTHONPATH": get_pythonpath_to_set(ctx),
        "TOPLEVEL_LANG": "verilog",
    }

    return [
        DefaultInfo(executable = test_script, runfiles = runfiles),
        testing.TestEnvironment(env),
    ]

# Simple test rule that just wraps a cocotb_binary
cocotb_test = rule(
    implementation = _cocotb_test_impl,
    attrs = {
        "binary": attr.label(
            doc = "The cocotb_binary target to run as a test",
            mandatory = True,
            executable = True,
            cfg = "target",
        ),
        "deps": attr.label_list(
            doc = "Python dependencies for PYTHONPATH setup",
            providers = [PyInfo],
            default = [],
        ),
        "hdl_toplevel": attr.string(
            doc = "The name of the HDL toplevel module",
            mandatory = True,
        ),
        "test_module": attr.label_list(
            doc = "Test modules for PYTHONPATH setup",
            allow_files = [".py"],
            default = [],
        ),
        "env": attr.string_dict(
            doc = "Environment variables to set for the test",
            default = {},
        ),
        "data": attr.label_list(
            doc = "Data files needed by the test",
            allow_files = True,
            default = [],
        ),
    },
    toolchains = ["@rules_python//python:toolchain_type"],
    test = True,
)