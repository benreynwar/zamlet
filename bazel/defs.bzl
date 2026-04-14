"""Public API for Bazel utilities and rules."""

load("//bazel:chisel.bzl", _chisel_binary = "chisel_binary", _chisel_library = "chisel_library")
load("//bazel:verilog.bzl",
    _chisel_verilog = "chisel_verilog",
    _chisel_dse_module = "chisel_dse_module",
)
load("//bazel/flow:defs.bzl",
    _librelane_classic_flow = "librelane_classic_flow",
    _librelane_init = "librelane_init",
    _librelane_synthesis = "librelane_synthesis",
    _librelane_floorplan = "librelane_floorplan",
    _LibrelaneInfo = "LibrelaneInfo",
    _PdkInfo = "PdkInfo",
    _MacroInfo = "MacroInfo",
)

chisel_binary = _chisel_binary
chisel_library = _chisel_library
chisel_verilog = _chisel_verilog
chisel_dse_module = _chisel_dse_module
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
            clang --target=riscv64-unknown-elf -fuse-ld=lld -mno-relax \
                -nostdlib -nostartfiles \
                -T $(location {ld}) \
                -march={march} -mabi={mabi} \
                -o {name}.elf $(location {src})
            llvm-objcopy -O binary {name}.elf $@
            rm {name}.elf
        """.format(
            name = name,
            src = src,
            ld = linker_script,
            march = march,
            mabi = mabi,
        ),
    )

# Default geometry names matching zamlet.geometries.SMALL_GEOMETRIES
SMALL_GEOMETRY_NAMES = [
    "k2x1_j1x1",
    "k2x1_j1x2",
    "k2x1_j2x1",
    "k2x2_j1x2",
    "k2x2_j2x1",
    "k2x2_j2x2",
]

def riscv_kernel(
        name,
        srcs,
        linker_script,
        common_srcs = [],
        hdrs = [],
        copts = [],
        march = "rv64gcv",
        mabi = "lp64d",
        visibility = None):
    """Compile C and assembly sources into a RISC-V ELF for kernel tests.

    Args:
        name: Name for the output (will produce {name}.riscv)
        srcs: Kernel-specific source files (.c, .S)
        linker_script: Linker script label
        common_srcs: Shared source files (e.g. standard_runtime filegroup)
        hdrs: Header files needed for include paths
        copts: Extra compiler flags (e.g. ["-ffast-math", "-DPREALLOCATE=1"])
        march: RISC-V architecture string
        mabi: RISC-V ABI string
        visibility: Bazel visibility
    """
    all_srcs = srcs + common_srcs + hdrs
    src_locations = " ".join(["$(locations {})".format(s) for s in srcs + common_srcs])
    copts_str = " ".join(copts)

    # Build -I flags from header locations. We use the directory of the linker script
    # as the common include path, and the package directory for local headers.
    native.genrule(
        name = name,
        srcs = all_srcs + [linker_script],
        outs = [name + ".riscv"],
        cmd = """
            COMMON_DIR=$$(dirname $(location {linker_script}))
            clang --target=riscv64-unknown-elf -fuse-ld=lld -mno-relax \
                -mcmodel=medany -static -ffreestanding -O2 -g \
                -fno-common -fno-builtin-printf \
                -march={march} -mabi={mabi} -std=gnu99 \
                -mllvm -riscv-vpu-stack \
                {copts} \
                -I$$COMMON_DIR -I$$COMMON_DIR/ara \
                -I$$(dirname $(location {local_anchor})) \
                -static -nostdlib -nostartfiles \
                -T$(location {linker_script}) \
                {src_locations} \
                -o $@
        """.format(
            linker_script = linker_script,
            local_anchor = srcs[0],
            march = march,
            mabi = mabi,
            copts = copts_str,
            src_locations = src_locations,
        ),
        visibility = visibility,
    )

def kernel_test(
        name,
        kernel,
        geometries = None,
        expected_failure = False,
        max_cycles = 100000,
        symbol_values = None,
        timeout = "moderate",
        tags = [],
        deps = []):
    """Generate py_test targets for a kernel binary across geometries.

    Creates one py_test per geometry and a test_suite grouping them all.

    Args:
        name: Base test name (e.g. "test_vecadd")
        kernel: Label of the riscv_kernel target
        geometries: List of geometry name strings; defaults to SMALL_GEOMETRY_NAMES
        expected_failure: If True, assert non-zero exit code
        max_cycles: Maximum simulation cycles
        symbol_values: Dict of symbol name -> int value to inject before running
        tags: Extra Bazel tags
        deps: Extra Python deps
    """
    if geometries == None:
        geometries = SMALL_GEOMETRY_NAMES

    test_names = []
    for geom in geometries:
        test_name = "{}_{}".format(name, geom)
        test_names.append(test_name)
        env = {
            "KERNEL_BINARY": "$(rootpath {})".format(kernel),
            "GEOMETRY": geom,
            "MAX_CYCLES": str(max_cycles),
            "EXPECTED_FAILURE": "1" if expected_failure else "0",
        }
        if symbol_values:
            env["SYMBOL_VALUES"] = json.encode(symbol_values)
        native.py_test(
            name = test_name,
            srcs = ["//python/zamlet/kernel_tests:run_kernel_test.py"],
            main = "//python/zamlet/kernel_tests:run_kernel_test.py",
            data = [kernel],
            deps = ["//python/zamlet:zamlet"] + deps,
            env = env,
            timeout = timeout,
            tags = tags,
        )

    native.test_suite(
        name = name,
        tests = test_names,
    )
