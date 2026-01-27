# Tile sources for Shuttle system integration

# Shuttle-only sources (no lamlet dependency)
filegroup(
    name = "shuttle_sources",
    srcs = [
        "Configs.scala",
        "Generator.scala",
        "ShuttleSystem.scala",
        "ShuttleTop.scala",
    ],
    visibility = ["//visibility:public"],
)

# All tile sources including Oamlet (requires lamlet)
filegroup(
    name = "tile_sources",
    srcs = glob(["*.scala"]),
    visibility = ["//visibility:public"],
)
