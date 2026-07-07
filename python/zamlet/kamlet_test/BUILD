# Kamlet module tests

load("//bazel:cocotb_rules.bzl", "chisel_module_tests", "chisel_module_tests_no_config")

chisel_module_tests(
    generator = "//src/main/scala/zamlet/kamlet:synchronizer",
    toplevel = "Synchronizer",
    srcs = ["test_synchronizer.py"],
    test_modules = ["zamlet.kamlet_test.test_synchronizer"],
    configs = [("default", "//configs:synchronizer_default.json")],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/kamlet:kamletmesh",
    toplevel = "KamletMesh",
    srcs = ["test_kamlet.py"],
    test_modules = ["zamlet.kamlet_test.test_kamlet"],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/kamlet:kamletcacheengine",
    toplevel = "KamletCacheEngine",
    srcs = ["test_kamlet_cache_engine.py"],
    test_modules = ["zamlet.kamlet_test.test_kamlet_cache_engine"],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/kamlet:kamlettransferengine",
    toplevel = "KamletTransferEngine",
    srcs = [
        "kte_driver.py",
        "test_kamlet_transfer_engine.py",
    ],
    test_modules = ["zamlet.kamlet_test.test_kamlet_transfer_engine"],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/kamlet:kamlettlb",
    toplevel = "KamletTlb",
    srcs = ["test_kamlet_tlb.py"],
    test_modules = ["zamlet.kamlet_test.test_kamlet_tlb"],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/kamlet:kamletmeshwithmemlets",
    toplevel = "KamletMeshWithMemlets",
    srcs = [
        "kamlet_mesh_with_memlets_driver.py",
        "ordered_kamlet_memory.py",
        "tag_table_driver.py",
        "test_kamlet_mesh_with_memlets.py",
    ],
    test_modules = ["zamlet.kamlet_test.test_kamlet_mesh_with_memlets"],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/kamlet:kamletmeshwithmemlets",
    toplevel = "KamletMeshWithMemlets",
    target_base = "kamletmeshwithmemlets_transpose",
    srcs = [
        "kamlet_mesh_with_memlets_driver.py",
        "ordered_kamlet_memory.py",
        "tag_table_driver.py",
        "test_kamlet_mesh_with_memlets_transpose.py",
    ],
    test_modules = ["zamlet.kamlet_test.test_kamlet_mesh_with_memlets_transpose"],
)

chisel_module_tests_no_config(
    generator = "//src/main/scala/zamlet/kamlet:tagtable",
    toplevel = "TagTable",
    srcs = [
        "tag_table_driver.py",
        "test_tag_table.py",
    ],
    test_modules = ["zamlet.kamlet_test.test_tag_table"],
    generator_args = ["16", "3", "4", "8", "8", "2"],
)

test_suite(
    name = "all_tests",
    tests = [
        # TODO: Re-enable when fixed
        # ":synchronizer_tests",
        ":tagtable_tests",
        ":kamletcacheengine_tests",
        ":kamletmesh_tests",
        ":kamletmeshwithmemlets_tests",
        ":kamlettransferengine_tests",
        ":kamlettlb_tests",
    ],
)
