# Systolic array physical design experiments

load("//bazel:verilog.bzl", "chisel_verilog_no_config")
load("//bazel:design/systolic/defs.bzl", "sum_stationary_top")
load("//bazel/flow:defs.bzl", "librelane_classic_flow", "librelane_synth_config")
load("//bazel/flow/sdc:sdc_template.bzl", "sdc_template")
load("@sky130_fd_sc_hd_config//:defs.bzl", "pdk")

pdk(name = "sky130hd")

SYSTOLIC_PKG = "//src/main/scala/zamlet/systolic"

librelane_synth_config(
    name = "synth_autoname",
    synth_autoname = True,
)

librelane_synth_config(
    name = "synth_sum_stationary_preserve_cell",
    synth_autoname = True,
    synth_keep_hierarchy_modules = [
        "SumStationaryCDrainRegister",
        "SumStationaryCell",
        "SumStationaryResetGroup",
    ],
)

SUM_STATIONARY_CONFIGS = [
    (8, False, True, 4),
    (4, False, False, 0),
    (2, False, False, 0),
    (8, True, False, 0),
    (4, True, False, 0),
    (2, True, False, 0),
]

SUM_STATIONARY_CLOCK_PERIODS = [20, 16, 12, 11, 10]
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
    librelane_classic_flow(
        name = sum_stationary_top(n, csa, True, False, split_drain, reset_group) +
               "_sky130hd_{}ns_util{}".format(clock_period, utilization),
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
