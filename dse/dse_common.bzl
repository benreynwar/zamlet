# Common DSE macros and functions
# Shared functionality for design space exploration BUILD files

load("@bazel-orfs//:openroad.bzl", "orfs_flow", "orfs_run")
load("@bazel-orfs//:yosys.bzl", "yosys")
load("//:verilog_common.bzl", "generate_dse_verilog_rule")

def dse_component_flows(studies, component_type, pdks = ["asap7", "sky130hd"]):
    """
    Generate complete DSE flows for a set of component studies.
    
    Args:
        studies: List of study dictionaries with "name", "top_level", and "config_file" keys
        component_type: String identifier for the component type (e.g., "new_lane", "amlet")
        pdks: List of PDKs to target (default: ["asap7", "sky130hd"])
    """
    
    study_names = ["{}__{}".format(study["name"], pdk) for study in studies for pdk in pdks]
    
    # Generate Verilog for components
    [generate_dse_verilog_rule(
        name = study["name"],
        top_level = study["top_level"],
        config_file = study["config_file"],
    ) for study in studies]

    # OpenROAD flows for each component and PDK
    [orfs_flow(
        name = name,
        top = study_name,
        pdk = "@docker_orfs//:{}".format(pdk),
        arguments = {
            "FILL_CELLS": "",
            "TAPCELL_TCL": "",
            "SKIP_REPORT_METRICS": "1",
            "SKIP_CTS_REPAIR_TIMING": "1", 
            "SKIP_INCREMENTAL_REPAIR": "1",
            "GND_NETS_VOLTAGES": "",
            "PWR_NETS_VOLTAGES": "",
            "GPL_ROUTABILITY_DRIVEN": "0",
            "GPL_TIMING_DRIVEN": "0",
            "SETUP_SLACK_MARGIN": "-10000",
            "TNS_END_PERCENT": "0",
            "SYNTH_HIERARCHICAL": "1",
            "SYNTH_MINIMUM_KEEP_SIZE": "50",
            "PLACE_DENSITY": "0.40",
            "CORE_UTILIZATION": "20",
        },
        sources = {
            "SDC_FILE": ["//dse:config/constraints.sdc"],
        },
        verilog_files = [":{}.sv".format(study_name)],
    ) for study in studies for pdk in pdks for name, study_name in [("{}__{}".format(study["name"], pdk), study["name"])]]

    # Results extraction
    [orfs_run(
        name = "{base}_results".format(base = name),
        src = "{name}_floorplan".format(name = name),
        outs = ["{name}_stats".format(name = name)],
        arguments = {
            "OUTPUT": "$(location :{name}_stats)".format(name = name),
        },
        script = "//dse:scripts/results.tcl",
    ) for name in study_names]

    # Netlist extraction
    [native.genrule(
        name = "{name}_netlist".format(name = name),
        srcs = [":{name}_synth".format(name = name)],
        outs = ["{name}_netlist.v".format(name = name)],
        cmd = """
        NETLIST=$$(echo $(locations :{name}_synth) | tr ' ' '\\n' | grep '\\.v$$' | head -1)
        cp $$NETLIST $@
        """.format(name = name),
    ) for study in studies for pdk in pdks for name, study_name in [("{}__{}".format(study["name"], pdk), study["name"])]]

    # Hierarchical area reports
    [yosys(
        name = "{name}_hierarchy_report".format(name = name),
        srcs = [":{name}_netlist".format(name = name), "//dse:scripts/netlist_hierarchy_report.tcl"],
        outs = ["{name}_hierarchy.txt".format(name = name)],
        arguments = [
            "-p",
            "read_verilog $(location :{name}_netlist); hierarchy -top {top_module}; tee -o $(location {name}_hierarchy.txt) stat -tech".format(name = name, top_module = study_name),
        ],
    ) for study in studies for pdk in pdks for name, study_name in [("{}__{}".format(study["name"], pdk), study["name"])]]

def dse_filegroups(studies, component_type, pdks = ["asap7", "sky130hd"]):
    """
    Generate convenience filegroups for DSE results.
    
    Args:
        studies: List of study dictionaries
        component_type: String identifier for the component type (e.g., "new_lane", "amlet")  
        pdks: List of PDKs to target (default: ["asap7", "sky130hd"])
    """
    
    study_names = ["{}__{}".format(study["name"], pdk) for study in studies for pdk in pdks]
    
    # Main filegroups
    native.filegroup(
        name = "{}_results".format(component_type),
        srcs = [":{name}_results".format(name = name) for name in study_names],
        visibility = ["//visibility:public"],
    )

    native.filegroup(
        name = "{}_hierarchy_reports".format(component_type), 
        srcs = [":{name}_hierarchy_report".format(name = name) for name in study_names],
        visibility = ["//visibility:public"],
    )

    # PDK-specific results
    [native.filegroup(
        name = "{}_results_{}".format(component_type, pdk),
        srcs = [":{}_results".format(name) for name in study_names if name.endswith("__{}".format(pdk))],
        visibility = ["//visibility:public"],
    ) for pdk in pdks]