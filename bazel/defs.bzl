"""Public API for Bazel utilities and rules.

This module exports the main rules and utilities:
- chisel_binary, chisel_library: For Chisel compilation
- generate_verilog_rule: For generating Verilog from configs
- riscv_asm_binary: For compiling RISC-V assembly to binary
- librelane_*: Physical design flow rules
"""

load("//bazel:chisel.bzl", _chisel_binary = "chisel_binary", _chisel_library = "chisel_library")
load("//bazel:verilog.bzl", _generate_verilog_rule = "generate_verilog_rule", _generate_verilog_filegroup = "generate_verilog_filegroup")
load("//bazel/flow:defs.bzl",
    _librelane_classic_flow = "librelane_classic_flow",
    _librelane_init = "librelane_init",
    _librelane_synthesis = "librelane_synthesis",
    _librelane_floorplan = "librelane_floorplan",
    _LibrelaneInfo = "LibrelaneInfo",
    _PdkInfo = "PdkInfo",
    _MacroInfo = "MacroInfo",
)

# Export Chisel rules
chisel_binary = _chisel_binary
chisel_library = _chisel_library

# Export Verilog utilities
generate_verilog_rule = _generate_verilog_rule
generate_verilog_filegroup = _generate_verilog_filegroup

# Export librelane flow rules
librelane_classic_flow = _librelane_classic_flow
librelane_init = _librelane_init
librelane_synthesis = _librelane_synthesis
librelane_floorplan = _librelane_floorplan
LibrelaneInfo = _LibrelaneInfo
PdkInfo = _PdkInfo
MacroInfo = _MacroInfo

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
