# Module extensions for librelane flow rules

load(":pdk_repo.bzl", "pdk_config_repo")

def _pdk_config_impl(module_ctx):
    """Module extension to create PDK config repositories."""
    for mod in module_ctx.modules:
        for config in mod.tags.config:
            pdk_config_repo(
                name = config.name,
                pdk = config.pdk,
                scl = config.scl,
            )

pdk_config = module_extension(
    implementation = _pdk_config_impl,
    tag_classes = {
        "config": tag_class(
            attrs = {
                "name": attr.string(mandatory = True, doc = "Repository name"),
                "pdk": attr.string(mandatory = True, doc = "PDK name (e.g., 'sky130A')"),
                "scl": attr.string(mandatory = True, doc = "Standard cell library name"),
            },
        ),
    },
)
