# PDK rule for librelane flow

load(":providers.bzl", "PdkInfo")

def _pdk_impl(ctx):
    return [
        PdkInfo(
            name = ctx.attr.pdk_name,
            scl = ctx.attr.scl,
        ),
    ]

librelane_pdk = rule(
    implementation = _pdk_impl,
    attrs = {
        "pdk_name": attr.string(
            doc = "PDK name (e.g., 'sky130A')",
            mandatory = True,
        ),
        "scl": attr.string(
            doc = "Standard cell library name (e.g., 'sky130_fd_sc_hd')",
            mandatory = True,
        ),
    },
    provides = [PdkInfo],
)
