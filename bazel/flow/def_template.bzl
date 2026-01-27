# Rule to generate DEF template for CombinedNetworkNode

load(":providers.bzl", "PdkInfo")

def _combined_network_node_def_impl(ctx):
    pdk = ctx.attr.pdk[PdkInfo]

    # Get nominal tech LEF (keys are patterns like "nom_*", not exact corner names)
    tech_lef = pdk.tech_lefs["nom_*"]

    output = ctx.actions.declare_file(ctx.attr.name + ".def")

    args = [
        "-exit",
        "-no_splash",
        "-python",
        ctx.file._script.path,
        "--tech-lef", tech_lef.path,
        "--config", ctx.file.config.path,
        "--output", output.path,
        "--v-layer", pdk.fp_io_vlayer,
        "--h-layer", pdk.fp_io_hlayer,
    ]
    if ctx.attr.die_area:
        args.extend(["--die-area", ctx.attr.die_area])

    ctx.actions.run(
        inputs = [tech_lef, ctx.file.config, ctx.file._script],
        outputs = [output],
        executable = "openroad",
        arguments = args,
        use_default_shell_env = True,
    )

    return [DefaultInfo(files = depset([output]))]

combined_network_node_def = rule(
    implementation = _combined_network_node_def_impl,
    attrs = {
        "pdk": attr.label(
            mandatory = True,
            providers = [PdkInfo],
            doc = "PDK target",
        ),
        "config": attr.label(
            mandatory = True,
            allow_single_file = [".json"],
            doc = "Lamlet config JSON file",
        ),
        "die_area": attr.string(
            doc = "Die area as 'x0 y0 x1 y1' in microns (overrides auto-calc)",
        ),
        "_script": attr.label(
            default = "//dse/jamlet:gen_combined_network_node_def.py",
            allow_single_file = True,
        ),
    },
)
