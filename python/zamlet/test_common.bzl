# Common test macros and functions
# Shared functionality for module test BUILD files

load("@rules_python//python:defs.bzl", "py_test")
load("//:verilog_common.bzl", "generate_verilog_rule", "generate_verilog_filegroup")

def generate_verilog_for_modules(modules, configs):
    """
    Generate Verilog files for each module + config combination.
    
    Args:
        modules: List of tuples (name, top_level, extra_args)
        configs: Dict of config_name -> config_file mappings
    """
    [generate_verilog_rule(
        name = "{}_{}".format(name, config_name),
        top_level = top_level,
        config_file = "//configs:{}.json".format(config_file),
        extra_args = extra_args,
    ) for name, top_level, extra_args in modules for config_name, config_file in configs.items()]

def generate_verilog_filegroups(modules, configs):
    """
    Create filegroups for all Verilog files.
    
    Args:
        modules: List of tuples (name, top_level, extra_args)
        configs: Dict of config_name -> config_file mappings
    """
    [generate_verilog_filegroup("{}_{}".format(name, config_name)) 
     for name, _, _ in modules for config_name, _ in configs.items()]

def generate_module_tests(tests, configs):
    """
    Generate all tests for each config.
    
    Args:
        tests: List of tuples (test_name, test_file, verilog_target, special_args)
        configs: Dict of config_name -> config_file mappings
    """
    [py_test(
        name = "{}_{}".format(test_name, config_name),
        srcs = [test_file],
        deps = [
            "//python/zamlet:zamlet",
        ],
        data = [
            ":{}_{}_verilog_files".format(verilog_target, config_name),
            "//configs:{}.json".format(config_file),
        ],
        args = special_args + [
            "$(location :{}_{}_verilog_files)".format(verilog_target, config_name),
            "$(location //configs:{}.json)".format(config_file),
        ],
        main = test_file,
    ) for test_name, test_file, verilog_target, special_args in tests for config_name, config_file in configs.items()]

def create_module_tests(modules, tests, configs):
    """
    Complete test setup: generate Verilog, filegroups, and tests.
    
    Args:
        modules: List of tuples (name, top_level, extra_args)
        tests: List of tuples (test_name, test_file, verilog_target, special_args)
        configs: Dict of config_name -> config_file mappings
    """
    generate_verilog_for_modules(modules, configs)
    generate_verilog_filegroups(modules, configs)
    generate_module_tests(tests, configs)