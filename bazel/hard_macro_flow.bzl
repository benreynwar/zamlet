load("//bazel:cocotb_rules.bzl", "iverilog_post_pnr_cocotb_test")
load("//bazel:defs.bzl", "json_file")
load("//bazel:power_activity.bzl", "PowerReportInfo")
load("//bazel/flow:defs.bzl", "LibrelaneInfo", "librelane_classic_flow", "librelane_power_post_pnr")


def _state_files(state):
    files = []
    for value in [
        state.gds,
        state.lef,
        state.lib,
        state.nl,
        state.pnl,
        state.sdf,
        state.spef,
        state.spice,
    ]:
        if type(value) == "dict":
            files.extend(value.values())
        elif value != None:
            files.append(value)
    return files


def _hard_macro_analysis_impl(ctx):
    macro = ctx.attr.macro[LibrelaneInfo]
    power = ctx.attr.power[PowerReportInfo]
    nominal_corner = "nom_tt_025C_1v80"
    if nominal_corner not in power.reports:
        fail("Power reports do not contain {}".format(nominal_corner))

    analysis = ctx.actions.declare_file(ctx.label.name + "/analysis.json")
    args = ctx.actions.args()
    args.add("--state", macro.state_out)
    args.add("--power-report", power.reports[nominal_corner])
    args.add("--clock-period-ns", ctx.attr.clock_period_ns)
    args.add("--target-utilization", ctx.attr.target_utilization)
    args.add("--output", analysis)
    ctx.actions.run(
        executable = ctx.executable._summarize,
        arguments = [args],
        inputs = [macro.state_out, power.reports[nominal_corner]],
        outputs = [analysis],
        mnemonic = "SummarizeHardMacro",
    )

    files = _state_files(macro) + ctx.attr.power[DefaultInfo].files.to_list() + [analysis]
    return [DefaultInfo(files = depset(files))]


hard_macro_analysis = rule(
    implementation = _hard_macro_analysis_impl,
    attrs = {
        "macro": attr.label(mandatory = True, providers = [LibrelaneInfo]),
        "power": attr.label(mandatory = True, providers = [PowerReportInfo]),
        "clock_period_ns": attr.string(mandatory = True),
        "target_utilization": attr.string(mandatory = True),
        "_summarize": attr.label(
            default = Label("//bazel/flow:summarize_macro"),
            executable = True,
            cfg = "exec",
        ),
    },
)


def hard_macro_flow(
        name,
        wrapper_verilog,
        test_module,
        py_deps,
        test_params,
        clock_period,
        fp_core_util,
        **flow_kwargs):
    librelane_classic_flow(
        name = name,
        clock_period = clock_period,
        fp_core_util = fp_core_util,
        **flow_kwargs
    )

    power_params = dict(test_params)
    power_params["clockPeriodNs"] = clock_period
    json_file(
        name = name + "_power_params",
        data = power_params,
    )
    iverilog_post_pnr_cocotb_test(
        name = name + "_power_sim",
        flow = ":" + name + "_sta",
        flow_input = ":" + name + "_init",
        wrapper_verilog = wrapper_verilog,
        sdf_corner = "nom_tt_025C_1v80",
        test_module = test_module,
        toplevel = flow_kwargs["top"],
        py_deps = py_deps,
        config = ":" + name + "_power_params",
    )
    librelane_power_post_pnr(
        name = name + "_power",
        src = ":" + name + "_sta",
        input = ":" + name + "_init",
        activity = ":" + name + "_power_sim_activity",
        vcd_scope = flow_kwargs["top"] + "IverilogWrapper/dut",
    )
    hard_macro_analysis(
        name = name + "_macro",
        macro = ":" + name + "_mfg_report",
        power = ":" + name + "_power",
        clock_period_ns = clock_period,
        target_utilization = fp_core_util,
    )
