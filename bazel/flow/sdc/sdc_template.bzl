# SDC templating rule

def _sdc_template_impl(ctx):
    """Generate an SDC file with delay constraints substituted."""
    out = ctx.actions.declare_file(ctx.label.name + ".sdc")
    fragments = ctx.files.fragments

    template_out = out
    if fragments:
        template_out = ctx.actions.declare_file(ctx.label.name + "_base.sdc")

    ctx.actions.expand_template(
        template = ctx.file.template,
        output = template_out,
        substitutions = {
            "{{INPUT_DELAY_CONSTRAINT}}": ctx.attr.input_delay_constraint,
            "{{OUTPUT_DELAY_CONSTRAINT}}": ctx.attr.output_delay_constraint,
        },
    )

    if fragments:
        ctx.actions.run_shell(
            inputs = [template_out] + fragments,
            outputs = [out],
            arguments = [out.path, template_out.path] + [f.path for f in fragments],
            command = """
out="$1"
shift
cat "$@" > "$out"
""",
        )

    return [DefaultInfo(files = depset([out]))]

sdc_template = rule(
    implementation = _sdc_template_impl,
    attrs = {
        "template": attr.label(
            mandatory = True,
            allow_single_file = [".sdc"],
            doc = "SDC template file",
        ),
        "input_delay_constraint": attr.string(
            mandatory = True,
            doc = "Input delay constraint as percentage of clock period",
        ),
        "output_delay_constraint": attr.string(
            mandatory = True,
            doc = "Output delay constraint as percentage of clock period",
        ),
        "fragments": attr.label_list(
            allow_files = [".sdc"],
            doc = "Additional SDC fragments appended after the generated base SDC",
        ),
    },
)
