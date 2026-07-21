def _find_nix_cvc_impl(repository_ctx):
    repository_ctx.watch(repository_ctx.path(Label("//:shell.nix")))
    repository_ctx.watch(repository_ctx.path(Label("//nix:common.nix")))
    repository_ctx.watch(repository_ctx.path(Label("//nix:cvc.nix")))

    result = repository_ctx.execute(["which", "cvc64"])
    if result.return_code != 0:
        fail("cvc64 not found. Are you in the refreshed nix-shell?")

    repository_ctx.symlink(result.stdout.strip(), "cvc64")
    repository_ctx.file("BUILD.bazel", '''
filegroup(
    name = "cvc_bin",
    srcs = ["cvc64"],
    visibility = ["//visibility:public"],
)
''')

find_nix_cvc = repository_rule(
    implementation = _find_nix_cvc_impl,
    local = True,
    environ = ["PATH"],
)
