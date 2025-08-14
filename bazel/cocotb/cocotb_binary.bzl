"""Cocotb binary rule for creating simulation executables.

Links a verilator_cc_library static library with cocotb's verilator.cpp
and VPI library using cc_binary to create a cocotb-enabled simulation executable.
"""

load("@rules_cc//cc:defs.bzl", "CcInfo")
load("@rules_python//python:defs.bzl", "PyInfo")
load("@bazel_tools//tools/cpp:toolchain_utils.bzl", "find_cpp_toolchain")

def _cocotb_binary_impl(ctx):
    """Implementation of cocotb_binary rule.
    
    Creates a cc_binary that links the verilator_cc_library with cocotb's
    verilator.cpp main file and VPI library.
    """
    
    # Get the verilator cc_library target
    verilator_cc_lib = ctx.attr.verilator_cc_library
    if not verilator_cc_lib or CcInfo not in verilator_cc_lib:
        fail("cocotb_binary requires a verilator_cc_library target with CcInfo")
    
    # Get cocotb dependency for runfiles
    cocotb_dep = ctx.attr._cocotb_dep
    if not cocotb_dep or PyInfo not in cocotb_dep:
        fail("Missing cocotb dependency with PyInfo provider")
    
    # Get all files from cocotb (both runfiles and transitive sources)
    all_files = []
    if hasattr(cocotb_dep[DefaultInfo], 'default_runfiles'):
        runfiles = cocotb_dep[DefaultInfo].default_runfiles.files
        all_files.extend(runfiles.to_list())
    all_files.extend(cocotb_dep[PyInfo].transitive_sources.to_list())
    
    # Find cocotb's verilator.cpp from the cocotb dependency
    cocotb_verilator_cpp = None
    for src in all_files:
        if src.basename == "verilator.cpp" and "verilator" in src.path:
            cocotb_verilator_cpp = src
            break
    
    if not cocotb_verilator_cpp:
        available_cpp_files = [src.path for src in all_files if src.extension == "cpp"]
        fail("Could not find verilator.cpp in cocotb dependency sources.\n" +
             "Available cpp files: {}\n".format(available_cpp_files) +
             "Check that cocotb is properly installed with verilator support.")
    
    # Use cc_binary to link everything together
    executable = ctx.actions.declare_file(ctx.label.name)
    
    cc_toolchain = find_cpp_toolchain(ctx)
    feature_configuration = cc_common.configure_features(
        ctx = ctx,
        cc_toolchain = cc_toolchain,
        requested_features = ctx.features,
        unsupported_features = ctx.disabled_features,
    )
    
    # Get Python headers for compilation
    if not ctx.attr._py_cc_headers or CcInfo not in ctx.attr._py_cc_headers:
        fail("Python C headers not available. Ensure @rules_python//python/cc:current_py_cc_headers is properly configured.")
    py_cc_headers = ctx.attr._py_cc_headers[CcInfo]
    
    # Compile cocotb's verilator.cpp
    compilation_contexts = [
        verilator_cc_lib[CcInfo].compilation_context,
        py_cc_headers.compilation_context,
    ]
    
    compilation_context, compilation_outputs = cc_common.compile(
        name = ctx.label.name + "_cocotb_compile",
        actions = ctx.actions,
        feature_configuration = feature_configuration,
        cc_toolchain = cc_toolchain,
        srcs = [cocotb_verilator_cpp],
        compilation_contexts = compilation_contexts,
    )
    
    # Get cocotb VPI library paths from the cocotb dependency
    cocotb_vpi_lib = None
    cocotb_lib_dirs = []
    
    # Search for all library files in the cocotb libs directory
    cocotb_libraries = []
    for src in all_files:
        # Look for any .so files in the cocotb libs directory
        if (src.basename.startswith("lib") and src.extension in ["so", "a", "dylib"] and 
            "libs" in src.path):
            cocotb_libraries.append(src)
            if src.dirname not in cocotb_lib_dirs:
                cocotb_lib_dirs.append(src.dirname)
            # Keep the VPI library reference
            if "libcocotbvpi_verilator" in src.basename:
                cocotb_vpi_lib = src
    
    # Create linker inputs for all cocotb libraries
    libs_to_link = []
    for lib_file in cocotb_libraries:
        lib_to_link = cc_common.create_library_to_link(
            actions = ctx.actions,
            feature_configuration = feature_configuration,
            cc_toolchain = cc_toolchain,
            dynamic_library = lib_file,
        )
        libs_to_link.append(lib_to_link)
    
    if not libs_to_link:
        fail("No cocotb libraries found in cocotb dependency")
    
    linker_input = cc_common.create_linker_input(
        owner = ctx.label,
        libraries = depset(libs_to_link),
    )
    
    cocotb_linking_context = cc_common.create_linking_context(
        linker_inputs = depset([linker_input]),
    )

    # Build link flags for Python library
    link_flags = []
    
    # Get Python CC libs for linking
    if not ctx.attr._py_cc_libs or CcInfo not in ctx.attr._py_cc_libs:
        fail("Python C libraries not available. Ensure @rules_python//python/cc:current_py_cc_libs is properly configured.")
    py_cc_libs = ctx.attr._py_cc_libs[CcInfo]
    
    # Link verilator library + cocotb main + all cocotb libraries + Python libs
    linking_contexts = [
        verilator_cc_lib[CcInfo].linking_context,
        cocotb_linking_context,
        py_cc_libs.linking_context,
    ]
    
    linking_outputs = cc_common.link(
        name = ctx.label.name,
        actions = ctx.actions,
        feature_configuration = feature_configuration,
        cc_toolchain = cc_toolchain,
        compilation_outputs = compilation_outputs,
        linking_contexts = linking_contexts,
        user_link_flags = link_flags,
    )
    
    # Set up runfiles
    runfiles = ctx.runfiles(
        files = ctx.files.test_module + ctx.files.data + cocotb_libraries,
    )
    
    # Add verilator cc_library runfiles  
    runfiles = runfiles.merge(verilator_cc_lib[DefaultInfo].default_runfiles)
    
    # Add cocotb dependency runfiles (including pygpi module)
    runfiles = runfiles.merge(cocotb_dep[DefaultInfo].default_runfiles)
    
    # Merge runfiles from Python dependencies (including cocotb)
    for dep in ctx.attr.deps:
        if DefaultInfo in dep:
            runfiles = runfiles.merge(dep[DefaultInfo].default_runfiles)
    
    return [DefaultInfo(executable = linking_outputs.executable, runfiles = runfiles)]

# Define attributes for cocotb_binary rule
_cocotb_binary_attrs = {
    "data": attr.label_list(
        doc = "Runtime data files needed by the test",
        allow_files = True,
        default = [],
    ),
    "deps": attr.label_list(
        doc = "Python libraries needed by the test modules",
        providers = [PyInfo],
        default = [],
    ),
    "hdl_toplevel": attr.string(
        doc = "The name of the HDL toplevel module",
        mandatory = True,
    ),
    "test_module": attr.label_list(
        doc = "Python test modules containing cocotb tests",
        allow_files = [".py"],
        allow_empty = False,
        mandatory = True,
    ),
    "verilator_cc_library": attr.label(
        doc = "The verilator_cc_library target to use for simulation",
        mandatory = True,
        providers = [DefaultInfo],
    ),
    "waves": attr.bool(
        doc = "Record signal traces",
        default = True,
    ),
    "_cocotb_dep": attr.label(
        doc = "Cocotb Python dependency for accessing verilator.cpp and VPI libraries",
        default = "@zamlet_pip_deps//cocotb",
        providers = [PyInfo, DefaultInfo],
    ),
    "_py_cc_libs": attr.label(
        doc = "Python C libraries for linking",
        default = "@rules_python//python/cc:current_py_cc_libs",
        providers = [CcInfo],
    ),
    "_py_cc_headers": attr.label(
        doc = "Python C headers for compilation",
        default = "@rules_python//python/cc:current_py_cc_headers",
        providers = [CcInfo],
    ),
}

cocotb_binary = rule(
    implementation = _cocotb_binary_impl,
    attrs = _cocotb_binary_attrs,
    toolchains = [
        "@rules_python//python:toolchain_type",
        "@bazel_tools//tools/cpp:toolchain_type",
    ],
    fragments = ["cpp"],
    executable = True,
)