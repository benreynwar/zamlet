"""Public API for Bazel utilities and rules.

This module exports the main rules and utilities:
- cocotb_exe: For creating cocotb simulation executables
- cocotb_script: For running cocotb tests
- chisel_binary, chisel_library: For Chisel compilation
- generate_verilog_rule: For generating Verilog from configs
- create_module_tests: For creating test suites
- riscv_asm_binary: For compiling RISC-V assembly to binary
- shuttle_cocotb_test: For creating Shuttle cocotb tests
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

def riscv_asm_binary(name, src, linker_script, march = "rv64imafdc", mabi = "lp64d"):
    """Compile RISC-V assembly to a binary file.

    Args:
        name: Name for the output (will produce {name}.bin)
        src: Assembly source file (.S)
        linker_script: Linker script (.ld)
        march: RISC-V architecture string
        mabi: RISC-V ABI string
    """
    native.genrule(
        name = name,
        srcs = [src, linker_script],
        outs = [name + ".bin"],
        cmd = """
            riscv64-unknown-elf-gcc -nostdlib -nostartfiles \
                -T $(location {ld}) \
                -march={march} -mabi={mabi} \
                -o {name}.elf $(location {src})
            riscv64-unknown-elf-objcopy -O binary {name}.elf $@
            rm {name}.elf
        """.format(
            name = name,
            src = src,
            ld = linker_script,
            march = march,
            mabi = mabi,
        ),
    )

def shuttle_cocotb_test(name, asm_src, linker_script, cocotb_module, shuttle_exe, deps = []):
    """Create a Shuttle cocotb test from assembly source.

    Args:
        name: Test name
        asm_src: Assembly source file (.S)
        linker_script: Linker script (.ld)
        cocotb_module: Python module containing the cocotb test
        shuttle_exe: Shuttle cocotb executable target
        deps: Additional Python dependencies
    """
    bin_name = name + "_bin"
    bin_file = bin_name + ".bin"

    riscv_asm_binary(
        name = bin_name,
        src = asm_src,
        linker_script = linker_script,
    )

    _cocotb_script(
        name = name,
        binary = shuttle_exe,
        script = cocotb_module,
        module = cocotb_module.replace(".py", "").split(":")[-1],
        toplevel = "ShuttleTop",
        data = [":" + bin_name],
        env = {"ZAMLET_TEST_BINARY": "$(location :" + bin_name + ")"},
    )

