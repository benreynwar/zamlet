# Common macros for cocotb tests
# Simplifies creation of cocotb tests with bazel

load("//bazel:defs.bzl", "cocotb_test", "cocotb_binary")
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
        # Use --prefix Vtop to match cocotb's expected class names
        vopts = ["--prefix", "Vtop"],
    ) for verilog_target, config_name in unique_targets]
    
    # Generate cocotb binaries and tests using our new rules
    # First create the cocotb_binary targets
    [cocotb_binary(
        name = "{}_{}_binary".format(test_name, config_name),
        verilator_cc_library = ":{}_{}_compiled".format(verilog_target, config_name),
        hdl_toplevel = _get_toplevel_for_target(verilog_target, modules),
        test_module = [test_file],
        data = [
            "//configs:{}.json".format(config_file),
        ],
        deps = [
            "//python/zamlet:zamlet",  # Python dependencies
        ],
        waves = True,
    ) for test_name, test_file, verilog_target, special_args in tests 
      for config_name, config_file in configs.items()]
    
    # Then create the cocotb_test targets that run the binaries
    [cocotb_test(
        name = "{}_{}".format(test_name, config_name),
        binary = ":{}_{}_binary".format(test_name, config_name),
        test_module = [test_file],
        deps = [
            "//python/zamlet:zamlet",  # Python dependencies
            "@zamlet_pip_deps//cocotb",  # Cocotb framework
        ],
    ) for test_name, test_file, verilog_target, special_args in tests 
      for config_name, config_file in configs.items()]

def _get_toplevel_for_target(verilog_target, modules):
    """Get the toplevel module name for a given verilog target"""
    for name, top_level, _ in modules:
        if name == verilog_target:
            return top_level
    fail("Could not find toplevel for verilog_target: {}".format(verilog_target))