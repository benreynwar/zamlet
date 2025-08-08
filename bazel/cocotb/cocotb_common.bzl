"""Common helper functions for cocotb rules.

Based on helper functions from bazel_rules_hdl/cocotb/cocotb.bzl
Copyright 2023 Antmicro, Licensed under Apache License 2.0
"""

load("@rules_python//python:defs.bzl", "PyInfo")

def list_to_argstring(data, argname, attr = None, operation = None):
    """Convert a list to command line arguments.
    
    Args:
        data: List of values to convert
        argname: Name of the argument flag
        attr: Optional attribute name to extract from each value
        operation: Optional operation to apply to each value
    
    Returns:
        String containing formatted command line arguments
    """
    result = " --{}".format(argname) if data else ""
    for value in data:
        elem = value if attr == None else getattr(value, attr)
        elem = elem if operation == None else operation(elem)
        result += " {}".format(elem)
    return result

def dict_to_argstring(data, argname):
    """Convert a dict to command line arguments.
    
    Args:
        data: Dictionary to convert
        argname: Name of the argument flag
    
    Returns:
        String containing formatted command line arguments
    """
    result = " --{}".format(argname) if data else ""
    for key, value in data.items():
        result += " {}={}".format(key, value)
    return result

def files_to_argstring(data, argname):
    """Convert a list of files to command line arguments using short paths.
    
    Args:
        data: List of File objects
        argname: Name of the argument flag
    
    Returns:
        String containing formatted command line arguments
    """
    return list_to_argstring(data, argname, "short_path")

def pymodules_to_argstring(data, argname):
    """Convert Python modules to command line arguments.
    
    Args:
        data: List of File objects representing Python modules
        argname: Name of the argument flag
    
    Returns:
        String containing formatted command line arguments
    """
    remove_py = lambda s: s.removesuffix(".py")
    return list_to_argstring(data, argname, "basename", remove_py)

def remove_duplicates_from_list(data):
    """Remove duplicates from a list while preserving order.
    
    Args:
        data: List that may contain duplicates
    
    Returns:
        List with duplicates removed
    """
    result = []
    for e in data:
        if e not in result:
            result.append(e)
    return result

def collect_verilog_files(ctx):
    """Collect all Verilog files from sources and dependencies.
    
    Args:
        ctx: Rule context
    
    Returns:
        Depset of Verilog files
    """
    return depset(direct = ctx.files.verilog_sources)

def collect_vhdl_files(ctx):
    """Collect all VHDL files from sources.
    
    Args:
        ctx: Rule context
    
    Returns:
        Depset of VHDL files
    """
    return depset(direct = ctx.files.vhdl_sources)

def collect_python_transitive_imports(ctx):
    """Collect transitive Python import paths.
    
    Args:
        ctx: Rule context
    
    Returns:
        Depset of import paths
    """
    return depset(transitive = [
        dep[PyInfo].imports
        for dep in ctx.attr.deps
        if PyInfo in dep
    ])

def collect_python_direct_imports(ctx):
    """Collect direct Python import paths from test modules.
    
    Args:
        ctx: Rule context
    
    Returns:
        Depset of import paths
    """
    return depset(direct = [module.dirname for module in ctx.files.test_module])

def collect_transitive_files(ctx):
    """Collect all transitive files needed for execution.
    
    Args:
        ctx: Rule context
    
    Returns:
        Depset of files
    """
    py_toolchain = ctx.toolchains["@rules_python//python:toolchain_type"].py3_runtime
    return depset(
        direct = [py_toolchain.interpreter],
        transitive = [dep[PyInfo].transitive_sources for dep in ctx.attr.deps] +
                     [ctx.attr.cocotb_wrapper[PyInfo].transitive_sources] +
                     [py_toolchain.files],
    )

def collect_transitive_runfiles(ctx):
    """Collect all transitive runfiles.
    
    Args:
        ctx: Rule context
    
    Returns:
        Runfiles object
    """
    return ctx.runfiles().merge_all(
        [dep.default_runfiles for dep in ctx.attr.deps] +
        [dep.default_runfiles for dep in ctx.attr.sim],
    )

def get_pythonpath_to_set(ctx):
    """Get PYTHONPATH environment variable value.
    
    Args:
        ctx: Rule context
    
    Returns:
        String with paths to set in PYTHONPATH
    """
    direct_imports = collect_python_direct_imports(ctx).to_list()
    transitive_imports = [
        "../" + path
        for path in collect_python_transitive_imports(ctx).to_list()
    ]
    imports = remove_duplicates_from_list(transitive_imports + direct_imports)
    return ":".join(imports)

def get_path_to_set(ctx):
    """Get PATH environment variable value for simulators.
    
    Args:
        ctx: Rule context
    
    Returns:
        String with paths to add to PATH
    """
    sim_paths = remove_duplicates_from_list([dep.label.workspace_root for dep in ctx.attr.sim])
    path = ":".join(["$PWD/" + str(p) for p in sim_paths])
    return path