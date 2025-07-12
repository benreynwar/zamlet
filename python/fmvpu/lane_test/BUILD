# RegisterFileAndFriends, ALU, and InstructionMemory module tests

load("@rules_python//python:defs.bzl", "py_test")
load("//:chisel.bzl", "chisel_binary")

# Generate Verilog file for RegisterFileAndFriends
genrule(
    name = "rff_verilog",
    srcs = ["//configs:lane_default.json"],
    outs = ["rff.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src:verilog_generator) \\
        $$TMPDIR/rff_verilog \\
        RegisterFileAndFriends \\
        $(location //configs:lane_default.json)
    cat $$TMPDIR/rff_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src:verilog_generator"],
)

# Create filegroup to expose the generated Verilog file
filegroup(
    name = "rff_verilog_files",
    srcs = [":rff_verilog"],
)

# Basic RFF test
py_test(
    name = "test_rff_basic",
    srcs = ["test_rff_basic.py"],
    deps = [
        "//python/fmvpu:fmvpu",
    ],
    data = [
        ":rff_verilog_files",
    ],
    args = [
        "$(location :rff_verilog_files)",
    ],
    main = "test_rff_basic.py",
)

# Generate Verilog file for ALU
genrule(
    name = "alu_verilog",
    srcs = ["//configs:lane_default.json"],
    outs = ["alu.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src:verilog_generator) \\
        $$TMPDIR/alu_verilog \\
        ALU \\
        $(location //configs:lane_default.json) \\
        1
    cat $$TMPDIR/alu_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src:verilog_generator"],
)

# Create filegroup to expose the generated ALU Verilog file
filegroup(
    name = "alu_verilog_files",
    srcs = [":alu_verilog"],
)

# Basic ALU test
py_test(
    name = "test_alu_basic",
    srcs = ["test_alu_basic.py"],
    deps = [
        "//python/fmvpu:fmvpu",
    ],
    data = [
        ":alu_verilog_files",
    ],
    args = [
        "$(location :alu_verilog_files)",
    ],
    main = "test_alu_basic.py",
)

# Generate Verilog file for AluRS
genrule(
    name = "alurs_verilog",
    srcs = ["//configs:lane_default.json"],
    outs = ["alurs.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src:verilog_generator) \\
        $$TMPDIR/alurs_verilog \\
        AluRS \\
        $(location //configs:lane_default.json)
    cat $$TMPDIR/alurs_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src:verilog_generator"],
)

# Create filegroup to expose the generated AluRS Verilog file
filegroup(
    name = "alurs_verilog_files",
    srcs = [":alurs_verilog"],
)

# Basic AluRS test
py_test(
    name = "test_alurs_basic",
    srcs = ["test_alurs_basic.py"],
    deps = [
        "//python/fmvpu:fmvpu",
    ],
    data = [
        ":alurs_verilog_files",
    ],
    args = [
        "$(location :alurs_verilog_files)",
    ],
    main = "test_alurs_basic.py",
)

# Generate Verilog file for InstructionMemory
genrule(
    name = "instruction_memory_verilog",
    srcs = ["//configs:lane_default.json"],
    outs = ["instruction_memory.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src:verilog_generator) \\
        $$TMPDIR/instruction_memory_verilog \\
        InstructionMemory \\
        $(location //configs:lane_default.json)
    cat $$TMPDIR/instruction_memory_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src:verilog_generator"],
)

# Create filegroup to expose the generated InstructionMemory Verilog file
filegroup(
    name = "instruction_memory_verilog_files",
    srcs = [":instruction_memory_verilog"],
)

# Basic InstructionMemory test
py_test(
    name = "test_instruction_memory_basic",
    srcs = ["test_instruction_memory.py"],
    deps = [
        "//python/fmvpu:fmvpu",
    ],
    data = [
        ":instruction_memory_verilog_files",
    ],
    args = [
        "--verilog-file",
        "$(location :instruction_memory_verilog_files)",
    ],
    main = "test_instruction_memory.py",
)

# Generate Verilog file for NewLane
genrule(
    name = "lane_verilog",
    srcs = ["//configs:lane_default.json"],
    outs = ["lane.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src:verilog_generator) \\
        $$TMPDIR/lane_verilog \\
        NewLane \\
        $(location //configs:lane_default.json)
    cat $$TMPDIR/lane_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src:verilog_generator"],
)

# Create filegroup to expose the generated NewLane Verilog file
filegroup(
    name = "lane_verilog_files",
    srcs = [":lane_verilog"],
)

# Basic NewLane test
py_test(
    name = "test_lane_basic",
    srcs = ["test_lane.py"],
    deps = [
        "//python/fmvpu:fmvpu",
    ],
    data = [
        ":lane_verilog_files",
    ],
    args = [
        "$(location :lane_verilog_files)",
    ],
    main = "test_lane.py",
)

# Generate Verilog file for PacketSwitch
genrule(
    name = "packet_switch_verilog",
    srcs = ["//configs:lane_default.json"],
    outs = ["packet_switch.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src:verilog_generator) \\
        $$TMPDIR/packet_switch_verilog \\
        PacketSwitch \\
        $(location //configs:lane_default.json)
    cat $$TMPDIR/packet_switch_verilog/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src:verilog_generator"],
)

# Create filegroup to expose the generated PacketSwitch Verilog file
filegroup(
    name = "packet_switch_verilog_files",
    srcs = [":packet_switch_verilog"],
)

# Basic PacketSwitch test
py_test(
    name = "test_packet_switch_basic",
    srcs = ["test_packet_switch.py"],
    deps = [
        "//python/fmvpu:fmvpu",
    ],
    data = [
        ":packet_switch_verilog_files",
    ],
    args = [
        "$(location :packet_switch_verilog_files)",
    ],
    main = "test_packet_switch.py",
)