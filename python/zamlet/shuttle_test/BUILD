# Shuttle core cocotb tests

load("@rules_hdl//verilog:defs.bzl", "verilog_library")
load("@rules_hdl//verilator:defs.bzl", "verilator_cc_library")
load("//bazel:defs.bzl", "cocotb_exe", "cocotb_script")

# Generate Shuttle Verilog using the shuttle_tile_generator
genrule(
    name = "shuttle_verilog",
    outs = ["ShuttleTop.sv"],
    cmd = """
        TMPDIR=$$(mktemp -d)
        $(location //src:shuttle_tile_generator) $$TMPDIR minimal
        cat $$TMPDIR/*.sv > $@
        rm -rf $$TMPDIR
    """,
    tools = ["//src:shuttle_tile_generator"],
)

# Create verilog library for verilator
verilog_library(
    name = "shuttle_verilog_lib",
    srcs = [":shuttle_verilog"],
)

# Compile RISC-V test program
genrule(
    name = "test_simple_bin",
    srcs = ["test_simple.S", "link.ld"],
    outs = ["test_simple.bin"],
    cmd = """
        riscv64-unknown-elf-gcc -nostdlib -nostartfiles \
            -T $(location link.ld) \
            -march=rv64imafdc -mabi=lp64d \
            -o test_simple.elf $(location test_simple.S)
        riscv64-unknown-elf-objcopy -O binary test_simple.elf $@
        rm test_simple.elf
    """,
)

# Create cocotb executable
cocotb_exe(
    name = "shuttle_exe",
    verilog_library = ":shuttle_verilog_lib",
    module_top = "ShuttleTop",
)

# Python test library
py_library(
    name = "test_basic_py",
    srcs = ["test_basic.py"],
    imports = ["."],  # Make test_basic directly importable
    data = [":test_simple_bin"],
    deps = [
        "//python/zamlet:zamlet",
        "@zamlet_pip_deps//cocotb",
        "@cocotb_bus//:cocotb_bus",
        "@cocotbext_axi//:cocotbext_axi",
    ],
)

# Cocotb test
cocotb_script(
    name = "test_basic",
    binary = ":shuttle_exe",
    script = ":test_basic_py",
    module = "test_basic",
    toplevel = "ShuttleTop",
    data = [":test_simple_bin"],
)
