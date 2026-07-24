package(default_visibility = ["//visibility:public"])

load("//bazel:design/systolic/defs.bzl", "sum_stationary_top", "weight_stationary_top")
load(":results.bzl", "flow_name", "systolic_results")

py_binary(
    name = "generate_results",
    srcs = ["generate_results.py"],
    main = "generate_results.py",
)

SUM_2X2 = sum_stationary_top(2, False, True, False, False, 0)
SUM_4X4 = sum_stationary_top(4, False, True, False, False, 0)
WEIGHT_2X2 = weight_stationary_top(2, 0)
WEIGHT_4X4 = weight_stationary_top(4, 0)

AREA_POWER_CONFIGS = [
    ("weight-stationary", WEIGHT_2X2, 2, "sky130hd", "Sky130", "12"),
    ("sum-stationary", SUM_2X2, 2, "sky130hd", "Sky130", "12"),
    ("weight-stationary", WEIGHT_4X4, 4, "sky130hd", "Sky130", "12"),
    ("sum-stationary", SUM_4X4, 4, "sky130hd", "Sky130", "12"),
    ("weight-stationary", WEIGHT_2X2, 2, "asap7sc7p5t", "ASAP7", "1.2"),
    ("sum-stationary", SUM_2X2, 2, "asap7sc7p5t", "ASAP7", "1.2"),
    ("weight-stationary", WEIGHT_4X4, 4, "asap7sc7p5t", "ASAP7", "1.2"),
    ("sum-stationary", SUM_4X4, 4, "asap7sc7p5t", "ASAP7", "1.2"),
]

AREA_POWER_RUNS = {
    "//dse/systolic:" + flow_name(top, pdk, clock_period, 60) + "_analysis": json.encode({
        "design": design,
        "n": n,
        "pdk": pdk,
        "pdk_display": pdk_display,
    })
    for design, top, n, pdk, pdk_display, clock_period in AREA_POWER_CONFIGS
}

DESIGNS = [
    ("sum-stationary", 2, SUM_2X2),
    ("weight-stationary", 2, WEIGHT_2X2),
    ("sum-stationary", 4, SUM_4X4),
    ("weight-stationary", 4, WEIGHT_4X4),
]

FREQUENCY_CONFIGS = [
    {
        "clock_period_ns": clock_period,
        "design": design,
        "n": n,
        "tables": ["frequency"] + (["utilization"] if clock_period == "12" else []),
        "target_utilization_percent": 60,
        "top": top,
    }
    for design, n, top in DESIGNS
    for clock_period in ["12", "11", "10", "9.5", "9", "8.5"]
]

UTILIZATION_CONFIGS = [
    {
        "clock_period_ns": "12",
        "design": design,
        "n": n,
        "tables": ["utilization"],
        "target_utilization_percent": utilization,
        "top": top,
    }
    for design, n, top in DESIGNS
    for utilization in [70, 72, 74, 75]
    if not (design == "weight-stationary" and utilization == 75)
]

STA_CONFIGS = FREQUENCY_CONFIGS + UTILIZATION_CONFIGS

STA_RUNS = {
    "//dse/systolic:" + flow_name(
        config["top"],
        "sky130hd",
        config["clock_period_ns"],
        config["target_utilization_percent"],
    ) + "_sta": json.encode({
        "clock_period_ns": config["clock_period_ns"],
        "design": config["design"],
        "n": config["n"],
        "tables": config["tables"],
        "target_utilization_percent": config["target_utilization_percent"],
    })
    for config in STA_CONFIGS
}

systolic_results(
    name = "results",
    area_power_runs = AREA_POWER_RUNS,
    sta_runs = STA_RUNS,
    # Failed Bazel actions have no consumable output, so expected flow failures
    # must be recorded explicitly rather than listed in sta_runs.
    expected_results = [
        json.encode({
            "clock_period_ns": "12",
            "design": "weight-stationary",
            "n": 2,
            "status": "Global-routing failure",
            "tables": ["utilization"],
            "target_utilization_percent": 75,
        }),
    ],
    output = "systolic_array_results.md",
)
