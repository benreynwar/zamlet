# Utils module tests

load("@rules_python//python:defs.bzl", "py_test")

# Generate DroppingFifo Verilog with specific parameters
genrule(
    name = "counting_fifo_default_verilog",
    outs = ["counting_fifo_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src:verilog_generator) \\
        $$TMPDIR/counting_fifo_verilog \\
        DroppingFifo \\
        8 4 4
    cat $$TMPDIR/counting_fifo_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src:verilog_generator"],
)

filegroup(
    name = "counting_fifo_default_verilog_files",
    srcs = [":counting_fifo_default_verilog"],
)

# CountingFifo test
py_test(
    name = "test_dropping_fifo_default",
    srcs = ["test_dropping_fifo.py"],
    deps = [
        "//python/zamlet:zamlet",
    ],
    data = [
        ":counting_fifo_default_verilog_files",
    ],
    args = [
        "$(location :counting_fifo_default_verilog_files)",
    ],
    main = "test_dropping_fifo.py",
)