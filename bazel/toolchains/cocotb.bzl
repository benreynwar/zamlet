# Cocotb toolchain provider and rule

CocotbInfo = provider(
    doc = "Information about a cocotb installation",
    fields = {
        "libs_dir": "Path to cocotb shared libraries",
        "include_dir": "Path to cocotb headers",
        "verilator_cpp": "Path to cocotb's verilator.cpp entry point",
        "python_libdir": "Path to Python library directory (for LD_LIBRARY_PATH)",
        "python_bin": "Path to Python interpreter",
    },
)

def _cocotb_toolchain_impl(ctx):
    return [platform_common.ToolchainInfo(
        cocotb = CocotbInfo(
            libs_dir = ctx.attr.libs_dir,
            include_dir = ctx.attr.include_dir,
            verilator_cpp = ctx.attr.verilator_cpp,
            python_libdir = ctx.attr.python_libdir,
            python_bin = ctx.attr.python_bin,
        ),
    )]

cocotb_toolchain = rule(
    implementation = _cocotb_toolchain_impl,
    attrs = {
        "libs_dir": attr.string(mandatory = True),
        "include_dir": attr.string(mandatory = True),
        "verilator_cpp": attr.string(mandatory = True),
        "python_libdir": attr.string(mandatory = True),
        "python_bin": attr.string(mandatory = True),
    },
)
