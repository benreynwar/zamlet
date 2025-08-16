"""Public API for Bazel utilities and rules.

This module exports the main rules and utilities:
- cocotb_exe: For creating cocotb simulation executables
- cocotb_script: For running cocotb tests
- chisel_binary, chisel_library: For Chisel compilation
- generate_verilog_rule: For generating Verilog from configs
- create_module_tests: For creating test suites
"""

load("@rules_cocotb_verilator//:cocotb_rules.bzl", _cocotb_exe = "cocotb_exe", _cocotb_script = "cocotb_script")
load("//bazel:chisel.bzl", _chisel_binary = "chisel_binary", _chisel_library = "chisel_library")
load("//bazel:verilog.bzl", _generate_verilog_rule = "generate_verilog_rule", _generate_verilog_filegroup = "generate_verilog_filegroup", _generate_verilog_library = "generate_verilog_library")

# Export cocotb rules
cocotb_exe = _cocotb_exe
cocotb_script = _cocotb_script

# Export Chisel rules
chisel_binary = _chisel_binary
chisel_library = _chisel_library

# Export Verilog utilities
generate_verilog_rule = _generate_verilog_rule
generate_verilog_filegroup = _generate_verilog_filegroup
generate_verilog_library = _generate_verilog_library

