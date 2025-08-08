"""Public API for Bazel utilities and rules.

This module exports the main rules and utilities:
- cocotb_test: For running cocotb tests
- cocotb_binary: For creating cocotb simulation binaries
- chisel_binary, chisel_library: For Chisel compilation
- generate_verilog_rule: For generating Verilog from configs
- create_module_tests: For creating test suites
"""

load("//bazel/cocotb:cocotb_test.bzl", _cocotb_test = "cocotb_test")
load("//bazel/cocotb:cocotb_binary.bzl", _cocotb_binary = "cocotb_binary")
load("//bazel:chisel.bzl", _chisel_binary = "chisel_binary", _chisel_library = "chisel_library")
load("//bazel:verilog.bzl", _generate_verilog_rule = "generate_verilog_rule", _generate_verilog_filegroup = "generate_verilog_filegroup", _generate_verilog_library = "generate_verilog_library")

# Export cocotb rules
cocotb_test = _cocotb_test
cocotb_binary = _cocotb_binary

# Export Chisel rules
chisel_binary = _chisel_binary
chisel_library = _chisel_library

# Export Verilog utilities
generate_verilog_rule = _generate_verilog_rule
generate_verilog_filegroup = _generate_verilog_filegroup
generate_verilog_library = _generate_verilog_library

