# Common Verilog generation utilities
# Shared functionality for generating Verilog across DSE and test BUILD files

def generate_verilog_rule(name, top_level, config_file, extra_args = [], generator_tool = "//src:verilog_generator", output_suffix = ""):
    """
    Generate a single Verilog file from a config.
    
    Args:
        name: Name for the genrule
        top_level: Top-level module name  
        config_file: Path to config file (e.g., "//configs:bamlet_default.json")
        extra_args: Additional arguments to pass to generator
        generator_tool: Tool to use for generation (default: "//src:verilog_generator")
        output_suffix: Optional suffix for output file naming
    """
    output_name = "{}{}.sv".format(name, output_suffix)
    
    native.genrule(
        name = "{}_verilog".format(name),
        srcs = [config_file],
        outs = [output_name],
        cmd = """
        TMPDIR=$$(mktemp -d)
        $(location {generator_tool}) \\
            $$TMPDIR/{name}_verilog \\
            {top_level} \\
            $(location {config_file}) {extra_args}
        cat $$TMPDIR/{name}_verilog/*.sv > $@
        rm -rf $$TMPDIR
        """.format(
            generator_tool=generator_tool,
            name=name, 
            top_level=top_level,
            config_file=config_file,
            extra_args=" ".join(extra_args)
        ),
        tools = [generator_tool],
    )

def generate_dse_verilog_rule(name, top_level, config_file, extra_args = []):
    """
    Generate Verilog for DSE with module renaming.
    
    Args:
        name: Name for the genrule and output module
        top_level: Original top-level module name
        config_file: Path to config file
        extra_args: Additional arguments to pass to generator
    """
    native.genrule(
        name = "{}_verilog".format(name),
        srcs = [config_file],
        outs = ["{}.sv".format(name)],
        cmd = """
        TMPDIR=$$(mktemp -d)
        TOP_LEVEL={top_level}
        $(location //dse:zamlet_generator) \\
            $$TMPDIR/{name}_verilog \\
            $$TOP_LEVEL \\
            $(location {config_file}) {extra_args}
        # Concatenate all SystemVerilog files and rename the top module
        find $$TMPDIR/{name}_verilog -name "*.sv" -type f | sort | xargs cat | sed 's/^module '$$TOP_LEVEL'(/module {name}(/' > $@
        rm -rf $$TMPDIR
        """.format(
            name=name,
            top_level=top_level, 
            config_file=config_file,
            extra_args=" ".join(extra_args)
        ),
        tools = ["//dse:zamlet_generator"],
    )

def generate_verilog_filegroup(name):
    """
    Create a filegroup for a Verilog file.
    
    Args:
        name: Base name (will create {name}_verilog_files group for {name}_verilog target)
    """
    native.filegroup(
        name = "{}_verilog_files".format(name),
        srcs = [":{}_verilog".format(name)],
    )