# Common DSE macros and functions
# Shared functionality for design space exploration BUILD files

load("@bazel-orfs//:openroad.bzl", "orfs_flow", "orfs_run")
load("@bazel-orfs//:yosys.bzl", "yosys")
load("//bazel:verilog.bzl", "generate_verilog_rule")
load("//dse:orfs_config.bzl", "get_orfs_arguments")

def dse_component_flows(studies, component_type, pdks = ["asap7", "sky130hd"]):
    """
    Generate complete DSE flows for a set of component studies.
    
    Args:
        studies: List of study dictionaries with "name", "top_level", and "config_file" keys
        component_type: String identifier for the component type (e.g., "amlet")
        pdks: List of PDKs to target (default: ["asap7", "sky130hd"])
    """
    
    study_names = ["{}__{}".format(study["name"], pdk) for study in studies for pdk in pdks]
    
    # Generate Verilog for components
    [generate_verilog_rule(
        name = study["name"],
        top_level = study["top_level"],
        config_file = study["config_file"],
        generator_tool = "//dse:zamlet_generator",
        rename_module = study["name"],
    ) for study in studies]

    # OpenROAD flows for each component and PDK
    [orfs_flow(
        name = name,
        top = study_name,
        pdk = "@docker_orfs//:{}".format(pdk),
        arguments = get_orfs_arguments(study["name"], pdk),
        sources = {
            "SDC_FILE": ["//dse:config/constraints_{}.sdc".format(pdk)],
        },
        verilog_files = [":{}.sv".format(study_name)],
    ) for study in studies for pdk in pdks for name, study_name in [("{}__{}".format(study["name"], pdk), study["name"])]]

    # Combined results and timing analysis - floorplan stage (estimated timing)
    [orfs_run(
        name = "{base}_results".format(base = name),
        src = "{name}_floorplan".format(name = name),
        outs = [
            "{name}_stats".format(name = name),
            "{name}_setup_timing.rpt".format(name = name),
            "{name}_hold_timing.rpt".format(name = name),
            "{name}_critical_paths.rpt".format(name = name),
            "{name}_unconstrained.rpt".format(name = name),
            "{name}_clock_skew.rpt".format(name = name),
            "{name}_slack_summary.rpt".format(name = name),
            "{name}_in2reg_paths.rpt".format(name = name),
            "{name}_reg2out_paths.rpt".format(name = name),
            "{name}_reg2reg_paths.rpt".format(name = name),
            "{name}_in2out_paths.rpt".format(name = name),
        ],
        arguments = {
            "OUTPUT": "$(location :{name}_stats)".format(name = name),
            "TARGET_NAME": name,
        },
        script = "//dse:scripts/analysis.tcl",
    ) for name in study_names]

    # Timing reports extraction - route stage (actual routed timing)
    [orfs_run(
        name = "{base}_timing_route".format(base = name),
        src = "{name}_route".format(name = name),
        outs = [
            "{name}_route_stats".format(name = name),
            "{name}_route_setup_timing.rpt".format(name = name),
            "{name}_route_hold_timing.rpt".format(name = name),
            "{name}_route_critical_paths.rpt".format(name = name),
            "{name}_route_unconstrained.rpt".format(name = name),
            "{name}_route_clock_skew.rpt".format(name = name),
            "{name}_route_slack_summary.rpt".format(name = name),
            "{name}_route_in2reg_paths.rpt".format(name = name),
            "{name}_route_reg2out_paths.rpt".format(name = name),
            "{name}_route_reg2reg_paths.rpt".format(name = name),
            "{name}_route_in2out_paths.rpt".format(name = name),
        ],
        arguments = {
            "OUTPUT": "$(location :{name}_route_stats)".format(name = name),
            "TARGET_NAME": "{name}_route".format(name = name),
        },
        script = "//dse:scripts/analysis.tcl",
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
        component_type: String identifier for the component type (e.g., "amlet")  
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
        name = "{}_timing_floorplan".format(component_type),
        srcs = [":{name}_timing_floorplan".format(name = name) for name in study_names],
        visibility = ["//visibility:public"],
    )

    native.filegroup(
        name = "{}_timing_route".format(component_type),
        srcs = [":{name}_timing_route".format(name = name) for name in study_names],
        visibility = ["//visibility:public"],
    )

    native.filegroup(
        name = "{}_timing".format(component_type),
        srcs = [":{name}_timing_floorplan".format(name = name) for name in study_names] +
               [":{name}_timing_route".format(name = name) for name in study_names],
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
