load("//bazel:cocotb_rules.bzl", "chisel_module_tests", "chisel_module_tests_no_config")
load("//bazel:defs.bzl", "json_file")

chisel_module_tests(
    generator = "//src/main/scala/zamlet/jamlet:indextocoordswithreg",
    toplevel = "IndexToCoordsWithReg",
    srcs = ["test_moore.py"],
    configs = [
        ("default", "//configs:zamlet_default.json"),
        ("16lanes", "//configs:zamlet_16lanes.json"),
        ("64lanes", "//configs:zamlet_64lanes.json"),
        ("1024lanes", "//configs:zamlet_1024lanes.json"),
    ],
    test_modules = [
      ("zamlet.jamlet_test.test_moore", "indextocoordswithreg_test"),
    ],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/jamlet:coordstoindexwithreg",
    toplevel = "CoordsToIndexWithReg",
    srcs = ["test_moore.py"],
    configs = [
        ("default", "//configs:zamlet_default.json"),
        ("16lanes", "//configs:zamlet_16lanes.json"),
        ("64lanes", "//configs:zamlet_64lanes.json"),
        ("1024lanes", "//configs:zamlet_1024lanes.json"),
    ],
    test_modules = [
      ("zamlet.jamlet_test.test_moore", "coordstoindexwithreg_test"),
    ],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/jamlet:jteinitiator",
    toplevel = "JteInitiator",
    srcs = [
        "jteinitiator_driver.py",
        "test_jteinitiator.py",
    ],
    configs = [
        ("default", "//configs:zamlet_default.json"),
    ],
    test_modules = [
      "zamlet.jamlet_test.test_jteinitiator",
    ],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/jamlet:jamletalu",
    toplevel = "JamletAlu",
    srcs = ["test_jamlet_alu.py"],
    configs = [
        ("default", "//configs:zamlet_default.json"),
    ],
    test_modules = ["zamlet.jamlet_test.test_jamlet_alu"],
)

MXU_TEST_GRID_PARAMS = [
    {
        "name": "jamlet_mxu_test_grid_2x2_mxu2",
        "top": "JamletMxuTestGrid2x2Mxu2",
        "gridRows": 2,
        "gridCols": 2,
        "mxuN": 2,
        "bcBuffer": True,
    },
    {
        "name": "jamlet_mxu_test_grid_4x4_mxu2",
        "top": "JamletMxuTestGrid4x4Mxu2",
        "gridRows": 4,
        "gridCols": 4,
        "mxuN": 2,
        "bcBuffer": True,
    },
    {
        "name": "jamlet_mxu_test_grid_4x4_mxu4",
        "top": "JamletMxuTestGrid4x4Mxu4",
        "gridRows": 4,
        "gridCols": 4,
        "mxuN": 4,
        "bcBuffer": True,
    },
]

[json_file(
    name = params["name"] + "_params",
    data = {
        "gridRows": params["gridRows"],
        "gridCols": params["gridCols"],
        "mxuN": params["mxuN"],
        "bcBuffer": params["bcBuffer"],
    },
) for params in MXU_TEST_GRID_PARAMS]

[chisel_module_tests_no_config(
    generator = "//src/main/scala/zamlet/jamlet:jamletmxutestgrid",
    toplevel = params["top"],
    srcs = ["test_jamlet_mxu.py"],
    generator_args = [
        str(params["gridRows"]),
        str(params["gridCols"]),
        str(params["mxuN"]),
        str(params["bcBuffer"]).lower(),
        params["top"],
    ],
    config = ":" + params["name"] + "_params",
    test_modules = ["zamlet.jamlet_test.test_jamlet_mxu"],
) for params in MXU_TEST_GRID_PARAMS]

chisel_module_tests(
    generator = "//src/main/scala/zamlet/jamlet:jamlet",
    toplevel = "Jamlet",
    srcs = [
        "jamlet_driver.py",
        "test_jamlet.py",
    ],
    configs = [
        ("default", "//configs:zamlet_default.json"),
    ],
    test_modules = ["zamlet.jamlet_test.test_jamlet"],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/jamlet:localexec",
    toplevel = "LocalExec",
    srcs = ["test_localexec.py"],
    configs = [
        ("default", "//configs:zamlet_default.json"),
    ],
    test_modules = ["zamlet.jamlet_test.test_localexec"],
)

test_suite(
    name = "all_tests",
    tests = [
        ":indextocoordswithreg_tests",
        ":coordstoindexwithreg_tests",
        ":jteinitiator_tests",
        ":jamletalu_tests",
        ":jamlet_tests",
        ":localexec_tests",
    ] + [":" + params["top"].lower() + "_tests" for params in MXU_TEST_GRID_PARAMS],
)
