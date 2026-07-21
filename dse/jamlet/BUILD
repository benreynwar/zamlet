# Jamlet Component DSE

load("//bazel:verilog.bzl", "chisel_dse_module", "chisel_verilog_no_config")
load("//bazel:design/jamlet/defs.bzl", "jamlet_mxu_top")
load("//bazel/flow:defs.bzl", "librelane_classic_flow", "librelane_synth_config")
load("//bazel/flow/sdc:sdc_template.bzl", "sdc_template")
load("@sky130_fd_sc_hd_config//:defs.bzl", "pdk")

pdk(name = "sky130hd")

# Synth config with autoname for readable timing reports
librelane_synth_config(
    name = "synth_autoname",
    synth_autoname = True,
)

librelane_synth_config(
    name = "synth_mxu_preserve_cell",
    synth_autoname = True,
    synth_keep_hierarchy_modules = [
        "JamletMxuCDrainRegister",
        "JamletMxuCell",
        "JamletMxuResetGroup",
        "RegisterWithPipelinedReset",
    ],
)

ZAMLET_CONFIG = "//configs:zamlet_default.json"
JAMLET_PKG = "//src/main/scala/zamlet/jamlet"

# Jamlet top module with custom pin placement
chisel_dse_module(
    name = "Jamlet_default",
    top = "Jamlet",
    generator = JAMLET_PKG + ":jamlet",
    config = ZAMLET_CONFIG,
    pdk = ":sky130hd",
    clock_period = "20.0",
    fp_core_util = "35",
    io_pin_order_cfg = ":jamlet_pin_order.cfg",
)

chisel_dse_module(
    name = "Jamlet_1024lanes",
    top = "Jamlet",
    generator = JAMLET_PKG + ":jamlet",
    config = "//configs:zamlet_1024lanes.json",
    pdk = ":sky130hd",
    clock_period = "20.0",
    fp_core_util = "35",
    io_pin_order_cfg = ":jamlet_pin_order.cfg",
)

chisel_dse_module(
    name = "Jamlet_1024lanes_hard_macros",
    top = "Jamlet",
    generator = JAMLET_PKG + ":jamlet_hard_macros",
    config = "//configs:zamlet_1024lanes.json",
    pdk = ":sky130hd",
    clock_period = "20.0",
    fp_core_util = "35",
    macros = [
        ":Jce_1024lanes_sky130hd_lef",
        ":LocalExec_1024lanes_sky130hd_lef",
        ":Sram_1024lanes_sky130hd_lef",
    ],
    io_pin_order_cfg = ":jamlet_pin_order.cfg",
    synth_config = ":synth_autoname",
)

# (ModuleName, bazel_target_name, extra_generator_args, fp_core_util)
JAMLET_SUB_MODULES = [
    ("RfSlice", "rfslice", [], "35"),
    ("Sram", "sram", [], "35"),
    ("Jce", "jce", [], "35"),
    ("CoordsToIndexWithReg", "coordstoindexwithreg", [], "35"),
    ("IndexToCoordsWithReg", "indextocoordswithreg", [], "35"),
    ("Jte", "jte", [], "40"),
    ("JteInitiator", "jteinitiator", [], "30"),
    ("JteInitiatorA", "jteinitiatorstage", ["A"], "5"),
    ("JteInitiatorB", "jteinitiatorstage", ["B"], "5"),
    ("JteInitiatorC", "jteinitiatorstage", ["C"], "35"),
    ("JteInitiatorD", "jteinitiatorstage", ["D"], "35"),
    ("JteInitiatorE", "jteinitiatorstage", ["E"], "35"),
    ("JteInitiatorF", "jteinitiatorstage", ["F"], "35"),
    ("JteInitiatorG", "jteinitiatorstage", ["G"], "35"),
    ("JteInitiatorH", "jteinitiatorstage", ["H"], "35"),
    ("JteInitiatorI", "jteinitiatorstage", ["I"], "35"),
    ("JteHandler", "jtehandler", [], "30"),
    ("JteHandlerA", "jtehandlerstage", ["A"], "5"),
    ("JteHandlerB", "jtehandlerstage", ["B"], "5"),
    ("JteHandlerC", "jtehandlerstage", ["C"], "35"),
    ("JteHandlerD", "jtehandlerstage", ["D"], "35"),
    ("JteHandlerE", "jtehandlerstage", ["E"], "35"),
    ("JteHandlerF", "jtehandlerstage", ["F"], "35"),
    ("JteHandlerG", "jtehandlerstage", ["G"], "35"),
    ("JteHandlerH", "jtehandlerstage", ["H"], "35"),
    ("JteReceiver", "jtereceiver", [], "30"),
    ("JteState", "jtestate", [], "20"),
]

# (config_name_suffix, config_label)
ZAMLET_CONFIGS = [
    ("default",   "//configs:zamlet_default.json"),
    ("1024lanes", "//configs:zamlet_1024lanes.json"),
]

[chisel_dse_module(
    name = "{}_{}".format(module, cfg_name),
    top = module,
    generator = JAMLET_PKG + ":{}".format(target),
    config = cfg_path,
    pdk = ":sky130hd",
    extra_generator_args = extra_args,
    clock_period = "20.0",
    fp_core_util = core_util,
    synth_config = ":synth_autoname",
) for module, target, extra_args, core_util in JAMLET_SUB_MODULES
  for cfg_name, cfg_path in ZAMLET_CONFIGS]

[chisel_dse_module(
    name = "LocalExec_{}".format(cfg_name),
    top = "LocalExec",
    generator = JAMLET_PKG + ":localexec",
    config = cfg_path,
    pdk = ":sky130hd",
    clock_period = "20.0",
    fp_core_util = "35",
    synth_config = ":synth_autoname",
    sdc_fragments = [":localexec.sdc"],
    run_post_grt_design_repair = True,
    run_post_grt_resizer_timing = True,
) for cfg_name, cfg_path in ZAMLET_CONFIGS]

# VectorRf - generic vector register file slice
chisel_dse_module(
    name = "VectorRf_3r1w",
    top = "VectorRf",
    generator = JAMLET_PKG + ":vectorrf",
    config = "//configs:vector_rf_3r1w.json",
    pdk = ":sky130hd",
    clock_period = "20.0",
    fp_core_util = "40",
)

JAMLET_MXU_CONFIGS = [
    (2, True, True, False, True, False, True, False, 0),
    (4, True, True, False, True, False, True, False, 0),
    (8, True, True, False, True, False, True, True, 4),
    (8, True, True, True, True, False, True, False, 0),
]
JAMLET_MXU_CLOCK_PERIODS = [20, 16, 12, 11, 10]
JAMLET_MXU_UTILIZATIONS = [40, 50, 60, 65, 70]

[
    chisel_verilog_no_config(
        name = jamlet_mxu_top(n, ew_loop, ns_loop, csa, bc, de, backward_reg, split_drain, reset_group),
        generator = JAMLET_PKG + ":jamletmxu",
        extra_args = [
            str(n),
            str(ew_loop).lower(),
            str(ns_loop).lower(),
            str(csa).lower(),
            str(bc).lower(),
            str(de).lower(),
            str(backward_reg).lower(),
            str(split_drain).lower(),
            str(reset_group),
        ],
    )
    for n, ew_loop, ns_loop, csa, bc, de, backward_reg, split_drain, reset_group in JAMLET_MXU_CONFIGS
]

[
    librelane_classic_flow(
        name = jamlet_mxu_top(n, ew_loop, ns_loop, csa, bc, de, backward_reg, split_drain, reset_group) +
               "_sky130hd_{}ns_util{}".format(clock_period, utilization),
        verilog_files = [
            ":" + jamlet_mxu_top(n, ew_loop, ns_loop, csa, bc, de, backward_reg, split_drain, reset_group) + ".sv",
        ],
        top = jamlet_mxu_top(n, ew_loop, ns_loop, csa, bc, de, backward_reg, split_drain, reset_group),
        pdk = ":sky130hd",
        clock_period = "{}.0".format(clock_period),
        fp_core_util = str(utilization),
        io_pin_order_cfg = ":jamlet_mxu{}x{}_pin_order.cfg".format(n, n),
        pnr_sdc_file = ":jamlet_mxu_pnr_sdc",
        signoff_sdc_file = ":jamlet_mxu_signoff_sdc",
        synth_config = ":synth_mxu_preserve_cell",
        design_repair_max_wire_length = "150",
        run_post_grt_resizer_timing = True,
        mid_setup_wns_threshold = "-0.2",
    )
    for n, ew_loop, ns_loop, csa, bc, de, backward_reg, split_drain, reset_group in JAMLET_MXU_CONFIGS
    for clock_period in JAMLET_MXU_CLOCK_PERIODS
    for utilization in JAMLET_MXU_UTILIZATIONS
]

sdc_template(
    name = "jamlet_mxu_pnr_sdc",
    template = "//bazel/flow/sdc:base.sdc",
    clock_period_scale = "0.9",
    input_delay_constraint = "75",
    output_delay_constraint = "55",
)

sdc_template(
    name = "jamlet_mxu_signoff_sdc",
    template = "//bazel/flow/sdc:base.sdc",
    input_delay_constraint = "75",
    output_delay_constraint = "45",
)

chisel_verilog_no_config(
    name = "JamletMxuCell",
    generator = JAMLET_PKG + ":jamletmxucell",
)

librelane_classic_flow(
    name = "JamletMxuCell_sky130hd",
    verilog_files = [":JamletMxuCell.sv"],
    top = "JamletMxuCell",
    pdk = ":sky130hd",
    clock_period = "20.0",
    fp_core_util = "35",
    synth_config = ":synth_autoname",
)
