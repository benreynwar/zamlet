def _find_nix_iverilog_impl(repository_ctx):
    repository_ctx.watch(repository_ctx.path(Label("//:shell.nix")))
    repository_ctx.watch(repository_ctx.path(Label("//nix:common.nix")))

    for tool in ["iverilog", "vvp"]:
        result = repository_ctx.execute(["which", tool])
        if result.return_code != 0:
            fail("{} not found. Are you in the refreshed nix-shell?".format(tool))
        repository_ctx.symlink(result.stdout.strip(), "bin/" + tool)

    repository_ctx.file("BUILD.bazel", '''
filegroup(
    name = "iverilog",
    srcs = ["bin/iverilog"],
    visibility = ["//visibility:public"],
)

filegroup(
    name = "vvp",
    srcs = ["bin/vvp"],
    visibility = ["//visibility:public"],
)
''')

find_nix_iverilog = repository_rule(
    implementation = _find_nix_iverilog_impl,
    local = True,
    environ = ["PATH"],
)
