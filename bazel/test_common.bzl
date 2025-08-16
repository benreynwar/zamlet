# Common macros for cocotb tests
# Simplifies creation of cocotb tests with bazel

load("//bazel:defs.bzl", "cocotb_exe", "cocotb_script")
load("@rules_hdl//verilator:defs.bzl", "verilator_cc_library") 
load("//bazel:verilog.bzl", "generate_verilog_rule", "generate_verilog_filegroup", "generate_verilog_library")

def create_module_tests(modules, tests, configs):
    """
    Create cocotb tests that handle simulation setup in bazel.
    
    Args:
        modules: List of tuples (name, top_level, extra_args)
        tests: List of tuples (test_name, test_file, verilog_target, special_args)  
        configs: Dict of config_name -> config_file mappings
    """
    
    # Generate Verilog files
    [generate_verilog_rule(
        name = "{}_{}".format(name, config_name),
        top_level = top_level,
        config_file = "//configs:{}.json".format(config_file),
        extra_args = extra_args,
    ) for name, top_level, extra_args in modules for config_name, config_file in configs.items()]
    
    # Generate Verilog libraries for bazel_rules_hdl
    [generate_verilog_library("{}_{}".format(name, config_name))
     for name, _, _ in modules for config_name, _ in configs.items()]
    
    # Generate compiled simulators using bazel_rules_hdl (deduplicated by verilog_target + config)
    unique_targets = list({(verilog_target, config_name): None 
                          for test_name, test_file, verilog_target, special_args in tests 
                          for config_name, config_file in configs.items()}.keys())
    [verilator_cc_library(
        name = "{}_{}_compiled".format(verilog_target, config_name),
        module = ":{}_{}_verilog_lib".format(verilog_target, config_name),
        module_top = _get_toplevel_for_target(verilog_target, modules),
        trace = True,
        # Use --prefix Vtop to match cocotb's expected class names, --vpi for cocotb support, and --public-flat-rw to expose hierarchy
        vopts = ["--prefix", "Vtop", "--vpi", "--public-flat-rw", "--timescale", "1ns/1ps", "--timing", "--debug", "-CFLAGS", "-DVL_DEBUG", "-CFLAGS", "-DVERILATOR_SIM_DEBUG"],
    ) for verilog_target, config_name in unique_targets]
    
    # Create py_library targets for test modules (required by cocotb_script)
    unique_test_files = list({test_file: None for test_name, test_file, verilog_target, special_args in tests}.keys())
    [native.py_library(
        name = _make_script_name(test_file),
        srcs = [test_file],
        imports = ["."],  # Make test modules directly importable from current directory
        deps = [
            "//python/zamlet:zamlet",  # Python dependencies
            "@zamlet_pip_deps//cocotb",  # Cocotb framework
        ],
    ) for test_file in unique_test_files]

    # Generate cocotb executables and test scripts using bazel_rules_cocotb_verilator
    # First create the cocotb_exe targets (combines binary creation and compilation)
    [cocotb_exe(
        name = "{}_{}_exe".format(test_name, config_name),
        verilog_library = ":{}_{}_verilog_lib".format(verilog_target, config_name),
        module_top = _get_toplevel_for_target(verilog_target, modules),
    ) for test_name, test_file, verilog_target, special_args in tests 
      for config_name, config_file in configs.items()]
    
    # Then create the cocotb_script targets that run the tests
    [cocotb_script(
        name = "{}_{}".format(test_name, config_name),
        binary = ":{}_{}_exe".format(test_name, config_name),
        script = ":{}".format(_make_script_name(test_file)),
        module = test_file.replace(".py", "").split("/")[-1],  # Extract module name from file path
        toplevel = _get_toplevel_for_target(verilog_target, modules),
        env = {
            "ZAMLET_TEST_CONFIG_FILENAME": "configs/{}.json".format(config_file)
        },
        data = [
            "//configs:{}.json".format(config_file),
        ],
    ) for test_name, test_file, verilog_target, special_args in tests 
      for config_name, config_file in configs.items()]

def _get_toplevel_for_target(verilog_target, modules):
    """Get the toplevel module name for a given verilog target"""
    for name, top_level, _ in modules:
        if name == verilog_target:
            return top_level
    fail("Could not find toplevel for verilog_target: {}".format(verilog_target))

def _make_script_name(test_file):
    """Generate a consistent script name from a test file path"""
    return "{}_py".format(test_file.replace(".py", "").replace("/", "_"))
