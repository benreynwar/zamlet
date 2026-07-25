load("//bazel:hard_macro_flow.bzl", "PnrAnalysisInfo")
load("//bazel/flow:providers.bzl", "LibrelaneInfo")


def flow_name(top, pdk, clock_period, utilization):
    return "{}_{}_{}ns_util{}".format(top, pdk, clock_period, utilization)


def _systolic_results_impl(ctx):
    inputs = []
    area_power_runs = []
    for target, metadata in ctx.attr.area_power_runs.items():
        analysis = target[PnrAnalysisInfo].analysis
        inputs.append(analysis)
        area_power_runs.append({
            "analysis": analysis.path,
            "metadata": metadata,
        })

    sta_runs = []
    for target, metadata in ctx.attr.sta_runs.items():
        state = target[LibrelaneInfo].state_out
        inputs.append(state)
        sta_runs.append({
            "state": state.path,
            "metadata": metadata,
        })

    manifest = ctx.actions.declare_file(ctx.label.name + "_manifest.json")
    ctx.actions.write(
        manifest,
        json.encode({
            "area_power_runs": area_power_runs,
            "sta_runs": sta_runs,
        }),
    )

    args = ctx.actions.args()
    args.add("--manifest", manifest)
    args.add("--output", ctx.outputs.output)
    ctx.actions.run(
        executable = ctx.executable._generator,
        arguments = [args],
        inputs = depset(inputs + [manifest]),
        outputs = [ctx.outputs.output],
        mnemonic = "SystolicResults",
    )
    return [DefaultInfo(files = depset([ctx.outputs.output]))]


systolic_results = rule(
    implementation = _systolic_results_impl,
    attrs = {
        "area_power_runs": attr.label_keyed_string_dict(
            providers = [PnrAnalysisInfo],
        ),
        "sta_runs": attr.label_keyed_string_dict(
            providers = [LibrelaneInfo],
        ),
        "output": attr.output(mandatory = True),
        "_generator": attr.label(
            default = Label("//dse/systolic_array_note:generate_results"),
            executable = True,
            cfg = "exec",
        ),
    },
)
