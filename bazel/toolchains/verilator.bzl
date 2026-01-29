# Verilator toolchain provider and rule

VerilatorInfo = provider(
    doc = "Information about a Verilator installation",
    fields = {
        "verilator_bin": "Path to verilator binary",
        "include_dir": "Path to verilator include directory",
    },
)

def _verilator_toolchain_impl(ctx):
    return [platform_common.ToolchainInfo(
        verilator = VerilatorInfo(
            verilator_bin = ctx.attr.verilator_bin,
            include_dir = ctx.attr.include_dir,
        ),
    )]

verilator_toolchain = rule(
    implementation = _verilator_toolchain_impl,
    attrs = {
        "verilator_bin": attr.string(mandatory = True),
        "include_dir": attr.string(mandatory = True),
    },
)
