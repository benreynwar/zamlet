# Systolic array physical design experiments

package(default_visibility = ["//visibility:public"])

load("//bazel:verilog.bzl", "chisel_verilog_no_config")
load("//bazel:design/systolic/defs.bzl", "sum_stationary_top", "weight_stationary_top")
load("//bazel:hard_macro_flow.bzl", "hard_macro_flow")
load("//bazel/flow:defs.bzl", "librelane_synth_config")
load("//bazel/flow/sdc:sdc_template.bzl", "sdc_template")
load("@sky130_fd_sc_hd_config//:defs.bzl", "pdk")

pdk(name = "sky130hd")

SYSTOLIC_PKG = "//src/main/scala/zamlet/systolic"

librelane_synth_config(
    name = "synth_weight_stationary_preserve_cell",
    synth_autoname = True,
    synth_keep_hierarchy_modules = [
        "RegisterWithPipelinedReset",
        "WeightStationaryCell",
        "WeightStationaryResetGroup",
    ],
)

librelane_synth_config(
    name = "synth_sum_stationary_preserve_cell",
    synth_autoname = True,
    synth_keep_hierarchy_modules = [
        "RegisterWithPipelinedReset",
        "SumStationaryCell",
        "SumStationaryResetGroup",
    ],
)

WEIGHT_STATIONARY_CONFIGS = [
    (8, 4),
    (4, 0),
    (2, 0),
]
WEIGHT_STATIONARY_CLOCK_PERIODS = [20, 16, 12, 11, 10, 9]
WEIGHT_STATIONARY_UTILIZATIONS = [40, 50, 60, 65, 70]

[
    chisel_verilog_no_config(
        name = weight_stationary_top(n, reset_group),
        generator = SYSTOLIC_PKG + ":weightstationary",
        extra_args = [str(n), str(reset_group)],
    )
    for n, reset_group in WEIGHT_STATIONARY_CONFIGS
]

[
    chisel_verilog_no_config(
        name = weight_stationary_top(n, reset_group) + "_iverilog_wrapper",
        generator = SYSTOLIC_PKG + ":weightstationary_iverilog_wrapper",
        extra_args = [str(n), str(reset_group)],
    )
    for n, reset_group in WEIGHT_STATIONARY_CONFIGS
]

[
    hard_macro_flow(
        name = weight_stationary_top(n, reset_group) +
               "_sky130hd_{}ns_util{}".format(clock_period, utilization),
        wrapper_verilog = ":" + weight_stationary_top(n, reset_group) +
                          "_iverilog_wrapper_verilog",
        test_module = "zamlet.systolic_test.test_weight_stationary",
        py_deps = ["//python/zamlet/systolic_test:weight_stationary_test"],
        test_params = {
            "n": n,
            "resetGroupSize": reset_group,
        },
        verilog_files = [":" + weight_stationary_top(n, reset_group) + ".sv"],
        top = weight_stationary_top(n, reset_group),
        pdk = ":sky130hd",
        clock_period = "{}.0".format(clock_period),
        fp_core_util = str(utilization),
        io_pin_order_cfg = ":weight_stationary{}x{}_pin_order.cfg".format(n, n),
        pnr_sdc_file = ":weight_stationary_pnr_sdc",
        signoff_sdc_file = ":weight_stationary_signoff_sdc",
        synth_config = ":synth_weight_stationary_preserve_cell",
        design_repair_max_wire_length = "150",
        run_post_grt_resizer_timing = True,
        mid_setup_wns_threshold = "-0.2",
    )
    for n, reset_group in WEIGHT_STATIONARY_CONFIGS
    for clock_period in WEIGHT_STATIONARY_CLOCK_PERIODS
    for utilization in WEIGHT_STATIONARY_UTILIZATIONS
]

sdc_template(
    name = "weight_stationary_pnr_sdc",
    template = "//bazel/flow/sdc:base.sdc",
    clock_period_scale = "0.9",
    input_delay_constraint = "75",
    output_delay_constraint = "55",
)

sdc_template(
    name = "weight_stationary_signoff_sdc",
    template = "//bazel/flow/sdc:base.sdc",
    input_delay_constraint = "75",
    output_delay_constraint = "45",
)

SUM_STATIONARY_CONFIGS = [
    (8, False, True, 4),
    (4, False, False, 0),
    (2, False, False, 0),
    (8, True, False, 0),
    (4, True, False, 0),
    (2, True, False, 0),
]

SUM_STATIONARY_CLOCK_PERIODS = [20, 16, 12, 11, 10, 9]
SUM_STATIONARY_UTILIZATIONS = [40, 50, 60, 65, 70]

[
    chisel_verilog_no_config(
        name = sum_stationary_top(n, csa, True, False, split_drain, reset_group),
        generator = SYSTOLIC_PKG + ":sumstationary",
        extra_args = [
            str(n),
            str(csa).lower(),
            "true",
            "false",
            str(split_drain).lower(),
            str(reset_group),
        ],
    )
    for n, csa, split_drain, reset_group in SUM_STATIONARY_CONFIGS
]

[
    chisel_verilog_no_config(
        name = sum_stationary_top(n, csa, True, False, split_drain, reset_group) +
               "_iverilog_wrapper",
        generator = SYSTOLIC_PKG + ":sumstationary_iverilog_wrapper",
        extra_args = [
            str(n),
            str(csa).lower(),
            "true",
            "false",
            str(split_drain).lower(),
            str(reset_group),
        ],
    )
    for n, csa, split_drain, reset_group in SUM_STATIONARY_CONFIGS
]

[
    hard_macro_flow(
        name = sum_stationary_top(n, csa, True, False, split_drain, reset_group) +
               "_sky130hd_{}ns_util{}".format(clock_period, utilization),
        wrapper_verilog = ":" +
                          sum_stationary_top(n, csa, True, False, split_drain, reset_group) +
                          "_iverilog_wrapper_verilog",
        test_module = "zamlet.systolic_test.test_sum_stationary",
        py_deps = ["//python/zamlet/systolic_test:sum_stationary_test"],
        test_params = {
            "n": n,
            "useCarrySaveAccumulator": csa,
            "registerBC": True,
            "registerDE": False,
            "splitCDrain": split_drain,
            "resetGroupSize": reset_group,
        },
        verilog_files = [
            ":" + sum_stationary_top(n, csa, True, False, split_drain, reset_group) + ".sv",
        ],
        top = sum_stationary_top(n, csa, True, False, split_drain, reset_group),
        pdk = ":sky130hd",
        clock_period = "{}.0".format(clock_period),
        fp_core_util = str(utilization),
        io_pin_order_cfg = ":sum_stationary{}x{}_pin_order.cfg".format(n, n),
        pnr_sdc_file = ":sum_stationary_pnr_sdc",
        signoff_sdc_file = ":sum_stationary_signoff_sdc",
        synth_config = ":synth_sum_stationary_preserve_cell",
        design_repair_max_wire_length = "150",
        run_post_grt_resizer_timing = True,
        mid_setup_wns_threshold = "-0.2",
    )
    for n, csa, split_drain, reset_group in SUM_STATIONARY_CONFIGS
    for clock_period in SUM_STATIONARY_CLOCK_PERIODS
    for utilization in SUM_STATIONARY_UTILIZATIONS
]

sdc_template(
    name = "sum_stationary_pnr_sdc",
    template = "//bazel/flow/sdc:base.sdc",
    clock_period_scale = "0.9",
    input_delay_constraint = "75",
    output_delay_constraint = "55",
)

sdc_template(
    name = "sum_stationary_signoff_sdc",
    template = "//bazel/flow/sdc:base.sdc",
    input_delay_constraint = "75",
    output_delay_constraint = "45",
)
