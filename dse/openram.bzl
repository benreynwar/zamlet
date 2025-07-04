"""Bazel rules for OpenRAM SRAM generation"""

def _openram_sram_impl(ctx):
    """Implementation for openram_sram rule"""
    
    # Calculate OpenRAM output name based on parameters
    byte_size = int((ctx.attr.word_size * ctx.attr.num_words) / 1024 / 8)
    if ctx.attr.num_rw_ports == 1 and ctx.attr.num_r_ports == 0 and ctx.attr.num_w_ports == 0:
        ports_human = "1rw"
    else:
        ports_human = "{}rw{}r{}w".format(ctx.attr.num_rw_ports, ctx.attr.num_r_ports, ctx.attr.num_w_ports)
    
    write_size = ctx.attr.write_size if ctx.attr.write_size > 0 else ctx.attr.word_size
    openram_name = "sky130_sram_{}kbytes_{}_{}x{}_{}".format(
        byte_size, ports_human, ctx.attr.word_size, ctx.attr.num_words, write_size
    )
    
    # Create output files using the user-provided name for bazel targets
    sram_name = ctx.attr.name
    outputs = []
    
    # Define output file extensions
    extensions = ["v", "lib", "lef", "gds", "sp", "py", "html"]
    extensions = ["py", "html", "v", "gds", "lef", "lvs.sp"]
    
    for ext in extensions:
        output_file = ctx.actions.declare_file("{}.{}".format(sram_name, ext))
        outputs.append(output_file)
    
    # Create OpenRAM JSON config file
    config_json = {
        "word_size": ctx.attr.word_size,
        "num_words": ctx.attr.num_words,
        "write_size": ctx.attr.write_size if ctx.attr.write_size > 0 else ctx.attr.word_size,
        "num_rw_ports": ctx.attr.num_rw_ports,
        "num_r_ports": ctx.attr.num_r_ports,
        "num_w_ports": ctx.attr.num_w_ports,
    }
    
    # TODO: There is likely a standard JSON conversion for bazel
    config_content = str(config_json).replace("'", '"')
    
    config_file = ctx.actions.declare_file("{}_config.json".format(sram_name))
    ctx.actions.write(
        output = config_file,
        content = config_content,
    )
    
    # Create local OpenRAM command
    openram_cmd = """
    set -euo pipefail
    
    # Use current working directory (bazel sandbox) directly
    WORK_DIR=$(pwd)
    
    # Copy config file to current directory for OpenRAM access
    cp {config_file} ./config.json
    
    # Activate OpenRAM virtual environment and set environment variables
    echo "Activating OpenRAM virtual environment..."
    source /opt/python-venv/bin/activate
    export OPENRAM_HOME=/opt/OpenRAM/compiler
    export OPENRAM_TECH=/opt/OpenRAM/technology
    export PDK_ROOT=/opt/pdk
    export OPENRAM_DISABLE_CONDA=1
    export HOME=$WORK_DIR
    
    # Check if OpenRAM is available
    if ! python3 -c "import openram" 2>/dev/null; then
        echo "ERROR: OpenRAM Python module not found! Make sure OpenRAM is installed."
        exit 1
    fi
    
    # Convert JSON config to Python config and run OpenRAM
    python3 /workspace/dse/openram_scripts/json_to_config.py ./config.json ./openram_config.py
    
    # Run OpenRAM but don't exit on failure yet - capture output first
    set +e
    python3 /workspace/dse/openram_scripts/openram_compiler.py ./openram_config.py 2>&1 | tee ./openram_output.log
    OPENRAM_EXIT_CODE=$?
    set -e
    
    if [ $OPENRAM_EXIT_CODE -ne 0 ]; then
        echo "ERROR: OpenRAM failed with exit code $OPENRAM_EXIT_CODE"
        exit $OPENRAM_EXIT_CODE
    fi
    
    # Copy outputs to bazel output locations (they should already be in current dir)
    """.format(
        config_file = config_file.path,
    )
    
    # Add copy commands for each output file using OpenRAM naming
    for i, ext in enumerate(extensions):
        openram_cmd += "cp ./{}.{} {}\n".format(
            openram_name, ext, outputs[i].path
        )
    
    openram_cmd += "\n# Clean up temporary files\nrm -f ./config.json ./openram_output.log\n"
    
    # Create the action
    ctx.actions.run_shell(
        inputs = [config_file],
        outputs = outputs,
        command = openram_cmd,
        use_default_shell_env = True,
        mnemonic = "OpenRAMSRAM",
        progress_message = "Generating SRAM {}".format(sram_name),
    )
    
    return [DefaultInfo(files = depset(outputs))]

openram_sram = rule(
    implementation = _openram_sram_impl,
    attrs = {
        "word_size": attr.int(
            mandatory = True,
            doc = "Size of each word in bits"
        ),
        "num_words": attr.int(
            mandatory = True,
            doc = "Number of words in the SRAM"
        ),
        "write_size": attr.int(
            default = 0,
            doc = "Minimum write size (0 means same as word_size)"
        ),
        "num_rw_ports": attr.int(
            default = 1,
            doc = "Number of read/write ports"
        ),
        "num_r_ports": attr.int(
            default = 0,
            doc = "Number of read-only ports"
        ),
        "num_w_ports": attr.int(
            default = 0,
            doc = "Number of write-only ports"
        ),
    },
    doc = "Generate SRAM using OpenRAM",
)
