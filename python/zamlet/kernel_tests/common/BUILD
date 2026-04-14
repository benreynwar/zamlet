package(default_visibility = ["//python/zamlet/kernel_tests:__subpackages__"])

HEADERS = [
    "encoding.h",
    "util.h",
    "vpu_alloc.h",
    "stdlib.h",
    "stdio.h",
    "string.h",
    "math.h",
    "assert.h",
    "zamlet_custom.h",
    "ara/exp.h",
    "ara/util.h",
    "ara/gemv.h",
    "ara/fdotproduct.h",
    "ara/rivec/vector_defines.h",
]

NON_HEADER_EXPORTS = [
    "crt.S",
    "syscalls.c",
    "test.ld",
    "vpu_alloc.c",
    "ara/util.c",
    "ara/gemv.c",
    "ara/fdotproduct.c",
]

exports_files(HEADERS + NON_HEADER_EXPORTS)

filegroup(
    name = "standard_runtime",
    srcs = ["crt.S", "syscalls.c"],
)

filegroup(
    name = "ara_runtime",
    srcs = ["crt.S", "syscalls.c", "ara/util.c", "vpu_alloc.c"],
)

filegroup(
    name = "headers",
    srcs = HEADERS,
)
