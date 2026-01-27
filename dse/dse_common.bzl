# Common DSE macros and functions
# Shared functionality for design space exploration BUILD files

load("//bazel/flow:defs.bzl", "librelane_classic_flow")
load("//bazel:verilog.bzl", "generate_verilog_rule")

def dse_component_flows(studies, component_type, pdks = ["sky130hd"]):
    """
    Generate complete DSE flows for a set of component studies.

    Args:
        studies: List of study dictionaries with "name", "top_level", and "config_file" keys
        component_type: String identifier for the component type (e.g., "kamlet")
        pdks: List of PDKs to target (default: ["sky130hd"])
    """

    # Generate Verilog for components
    [generate_verilog_rule(
        name = study["name"],
        top_level = study["top_level"],
        config_file = study["config_file"],
        generator_tool = "//dse:zamlet_generator",
        rename_module = study["name"],
    ) for study in studies]

    # Librelane flows for each component
    # For now only sky130hd is configured
    [librelane_classic_flow(
        name = "{}_{}".format(study["name"], pdk),
        verilog_files = [":{}.sv".format(study["name"])],
        top = study["name"],
        pdk = "@sky130_fd_sc_hd_config//:sky130hd",
        clock_period = "10.0",
        core_utilization = "40",
    ) for study in studies for pdk in pdks if pdk == "sky130hd"]

def dse_filegroups(studies, component_type, pdks = ["sky130hd"]):
    """
    Generate convenience filegroups for DSE results.

    Args:
        studies: List of study dictionaries
        component_type: String identifier for the component type (e.g., "kamlet")
        pdks: List of PDKs to target (default: ["sky130hd"])
    """

    study_names = ["{}_{}".format(study["name"], pdk) for study in studies for pdk in pdks]

    # Main filegroups - librelane produces different outputs
    native.filegroup(
        name = "{}_synthesis".format(component_type),
        srcs = [":{}_synth".format(name) for name in study_names],
        visibility = ["//visibility:public"],
    )

    native.filegroup(
        name = "{}_gds".format(component_type),
        srcs = [":{}_gds".format(name) for name in study_names],
        visibility = ["//visibility:public"],
    )
