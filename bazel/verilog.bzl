"""Verilog generation macros for Chisel generators.

Generators follow the convention: generator outputDir configFile [extra_args]
"""

load("//bazel/flow:defs.bzl", "librelane_classic_flow")

def chisel_verilog(name, generator, config, extra_args = []):
    """Generate SystemVerilog from a Chisel generator.

    Creates a genrule named {name}_verilog producing {name}.sv.

    Args:
        name: Base name (e.g. "Jamlet_default")
        generator: Chisel binary label
            (e.g. "//src/main/scala/zamlet/jamlet:jamlet")
        config: Config JSON label
            (e.g. "//configs:zamlet_default.json")
        extra_args: Additional arguments passed to the generator
    """
    extra = " ".join(extra_args)
    native.genrule(
        name = name + "_verilog",
        srcs = [config],
        outs = [name + ".sv"],
        cmd = """
    TMPDIR=$$(mktemp -d)
    $(location {generator}) $$TMPDIR $(location {config}) {extra}
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """.format(
            generator = generator,
            config = config,
            extra = extra,
        ),
        tools = [generator],
    )

def chisel_dse_module(
        name,
        top,
        generator,
        config,
        pdk,
        extra_generator_args = [],
        **flow_kwargs):
    """Generate verilog and run librelane P&R flow.

    Combines chisel_verilog + librelane_classic_flow.

    Creates targets:
        {name}_verilog     - genrule producing {name}.sv
        {name}_sky130hd*   - librelane flow targets

    Args:
        name: Base name (e.g. "Jamlet_default")
        top: Top module name for the flow (e.g. "Jamlet")
        generator: Chisel binary label
        config: Config JSON label
        pdk: PDK target label (e.g. ":sky130hd")
        extra_generator_args: Extra args for the Chisel generator
        **flow_kwargs: Passed to librelane_classic_flow
            (clock_period, core_utilization, pin_order_cfg, etc.)
    """
    chisel_verilog(
        name = name,
        generator = generator,
        config = config,
        extra_args = extra_generator_args,
    )

    librelane_classic_flow(
        name = name + "_sky130hd",
        verilog_files = [":" + name + ".sv"],
        top = top,
        pdk = pdk,
        **flow_kwargs
    )
