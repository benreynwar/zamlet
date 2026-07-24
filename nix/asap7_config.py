#!/usr/bin/env python3
"""Adapt the ORFS ASAP7 platform for use with LibreLane.

ORFS provides a working OpenROAD-flow configuration for ASAP7, while LibreLane
does not currently provide an ASAP7 PDK configuration. This script maps the
ORFS platform settings to current LibreLane variables under
`libs.tech/librelane`.

Physical views are installed separately by `asap7.nix` using the open_pdks
directory layout.
"""

from __future__ import annotations

import argparse
import gzip
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


SCL = "asap7sc7p5t"


@dataclass(frozen=True)
class TclExpression:
    """A Tcl expression which must be evaluated instead of quoted."""

    value: str


class OrfsAsap7:
    """Read required values from one pinned ORFS ASAP7 platform tree."""

    def __init__(self, platform: Path):
        self.platform = platform
        self.config_mk = platform / "config.mk"
        self.legacy_scl_config = platform / "openlane" / SCL / "config.tcl"

    def make_var(self, name: str) -> str:
        """Resolve an ORFS config.mk variable for the RVT/NLDM library."""
        result = subprocess.run(
            [
                "make",
                "-s",
                "-f",
                str(self.config_mk),
                "--eval=print-%: ; @echo $($*)",
                f"print-{name}",
                f"PLATFORM_DIR={self.platform}",
                "PRIMARY_VT=RVT",
                "PRIMARY_VT_TAG=R",
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        value = result.stdout.strip()
        if not value:
            raise ValueError(f"ORFS variable {name} is missing or empty")
        return value

    def legacy_scl_var(self, name: str) -> str:
        """Read ASAP7 metadata that ORFS has not moved into config.mk."""
        pattern = re.compile(
            rf'^set ::env\({re.escape(name)}\)\s+"?([^"\n]+?)"?\s*$'
        )
        for line in self.legacy_scl_config.read_text().splitlines():
            if match := pattern.match(line):
                return match.group(1)
        raise ValueError(f"ASAP7 SCL metadata {name} is missing")

    def routing_layers(self) -> list[str]:
        """Return routing layers in technology-LEF order."""
        tech_lef = Path(self.make_var("TECH_LEF"))
        layers: list[str] = []
        current_layer: str | None = None
        for line in tech_lef.read_text().splitlines():
            if match := re.match(r"\s*LAYER\s+(\S+)", line):
                current_layer = match.group(1)
            elif current_layer and re.match(r"\s*TYPE\s+ROUTING\s*;", line):
                layers.append(current_layer)
                current_layer = None
            elif current_layer and re.match(r"\s*END\s+", line):
                current_layer = None
        if not layers:
            raise ValueError(f"No routing layers found in {tech_lef}")
        return layers

    def write_tracks(self, output: Path) -> None:
        """Convert ORFS make_tracks commands to LibreLane tracks.info rows."""
        pattern = re.compile(
            r"^make_tracks (\S+) -x_offset (\S+) -x_pitch (\S+) "
            r"-y_offset (\S+) -y_pitch (\S+)$"
        )
        rows: list[str] = []
        source = self.platform / "openRoad" / "make_tracks.tcl"
        for line in source.read_text().splitlines():
            if match := pattern.match(line.strip()):
                layer, x_offset, x_pitch, y_offset, y_pitch = match.groups()
                rows.extend(
                    [
                        f"{layer} X {x_offset} {x_pitch}",
                        f"{layer} Y {y_offset} {y_pitch}",
                    ]
                )
        if not rows:
            raise ValueError(f"No make_tracks commands found in {source}")
        output.write_text("\n".join(rows) + "\n")

    def write_set_rc(self, output: Path) -> None:
        """Write ORFS wire RC values using LibreLane's pF/um convention."""
        source = self.platform / "setRC.tcl"
        capacitance = re.compile(
            r"(?P<prefix>-capacitance\s+)"
            r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)"
        )
        count = 0

        def normalize(match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            value_pf = float(match.group("value")) / 1000
            return match.group("prefix") + f"{value_pf:.15g}"

        source_text = source.read_text()
        text = capacitance.sub(normalize, source_text)
        if count == 0:
            raise ValueError(f"No wire capacitances found in {source}")
        if count != source_text.count("-capacitance"):
            raise ValueError(f"Malformed wire capacitance in {source}")
        output.write_text(text)


def liberty_value(path: Path, name: str) -> str:
    """Read scalar operating-condition metadata from a Liberty file."""
    opener = gzip.open if path.suffix == ".gz" else open
    pattern = re.compile(rf"\s*{re.escape(name)}\s*:\s*([^;]+);")
    with opener(path, "rt") as liberty:
        for line in liberty:
            if match := pattern.match(line):
                return match.group(1).strip()
    raise ValueError(f"{name} is missing from {path}")


def corner_name(kind: str, process: str, liberty: Path) -> str:
    """Name a corner from the operating conditions declared by its Liberty."""
    temperature = int(float(liberty_value(liberty, "nom_temperature")))
    temperature_text = f"n{abs(temperature):02d}" if temperature < 0 else f"{temperature:03d}"
    voltage = float(liberty_value(liberty, "nom_voltage"))
    voltage_text = f"{voltage:.2f}".replace(".", "v")
    return f"{kind}_{process}_{temperature_text}C_{voltage_text}"


def installed_liberty_paths(paths: Sequence[Path], directory: str) -> list[str]:
    """Map ORFS Liberty archives to their installed uncompressed locations."""
    return [
        f"{directory}/{path.name.removesuffix('.gz')}"
        for path in paths
    ]


def quote_tcl(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def format_value(value: object) -> str:
    if isinstance(value, TclExpression):
        return value.value
    if isinstance(value, Mapping):
        fields: list[str] = []
        for key, item in value.items():
            item_text = " ".join(item) if isinstance(item, list) else str(item)
            fields.extend([str(key), f'"{item_text}"'])
        return quote_tcl(" ".join(fields))
    if isinstance(value, list):
        return quote_tcl(" ".join(str(item) for item in value))
    return quote_tcl(str(value))


def write_config(path: Path, heading: str, values: Mapping[str, object]) -> None:
    lines = [f"# {heading}", "# Generated from pinned ORFS ASAP7 sources; do not edit.", ""]
    lines.extend(f"set ::env({name}) {format_value(value)}" for name, value in values.items())
    path.write_text("\n".join(lines) + "\n")


def build_configs(orfs: OrfsAsap7, pdk: Path) -> None:
    """Build native LibreLane PDK- and SCL-level configuration dictionaries."""
    config_root = pdk / "libs.tech" / "librelane"
    scl_config_root = config_root / SCL
    scl_config_root.mkdir(parents=True, exist_ok=True)

    pdk_ref = "$::env(PDK_ROOT)/$::env(PDK)"
    scl_ref = f"{pdk_ref}/libs.ref/$::env(STD_CELL_LIBRARY)"
    config_ref = f"{pdk_ref}/libs.tech/librelane"
    tech_lef_source = Path(orfs.make_var("TECH_LEF"))

    fast_sources = [Path(value) for value in orfs.make_var("BC_NLDM_LIB_FILES").split()]
    typical_sources = [Path(value) for value in orfs.make_var("TC_NLDM_LIB_FILES").split()]
    slow_sources = [Path(value) for value in orfs.make_var("WC_NLDM_LIB_FILES").split()]
    lib_ref = f"{scl_ref}/lib"
    libraries = {
        "min_*": installed_liberty_paths(fast_sources, lib_ref),
        "nom_*": installed_liberty_paths(typical_sources, lib_ref),
        "max_*": installed_liberty_paths(slow_sources, lib_ref),
    }

    corners = [
        corner_name("min", "ff", fast_sources[0]),
        corner_name("nom", "tt", typical_sources[0]),
        corner_name("max", "ss", slow_sources[0]),
    ]
    routing_adjustment = orfs.make_var("ROUTING_LAYER_ADJUSTMENT")

    pdk_config = {
        "STD_CELL_LIBRARY": SCL,
        "VDD_PIN": "VDD",
        "GND_PIN": "VSS",
        "TECH_LEFS": {"*": f"{scl_ref}/techlef/{tech_lef_source.name}"},
        "PRIMARY_GDSII_STREAMOUT_TOOL": "klayout",
        "DEFAULT_CORNER": corners[1],
        "STA_CORNERS": corners,
        # ORFS ASAP7 designs use 10-20 ps; use the conservative end of that range.
        "CLOCK_UNCERTAINTY_CONSTRAINT": "0.02",
        "RT_MIN_LAYER": orfs.make_var("MIN_ROUTING_LAYER"),
        "RT_MAX_LAYER": orfs.make_var("MAX_ROUTING_LAYER"),
        "GRT_LAYER_ADJUSTMENTS": [
            routing_adjustment for _ in orfs.routing_layers()
        ],
        "FP_TRACKS_INFO": f"{config_ref}/{SCL}/tracks.info",
        "PDN_CFG": f"{config_ref}/pdn.tcl",
        "SET_RC_TCL": f"{config_ref}/setRC.tcl",
        "FP_TAPCELL_DIST": "25",
        "IO_PIN_H_LAYER": orfs.make_var("IO_PLACER_H"),
        "IO_PIN_V_LAYER": orfs.make_var("IO_PLACER_V"),
        "KLAYOUT_TECH": f"{pdk_ref}/libs.tech/klayout/asap7.lyt",
        "KLAYOUT_PROPERTIES": f"{pdk_ref}/libs.tech/klayout/asap7.lyp",
        "KLAYOUT_DRC_RUNSET": f"{pdk_ref}/libs.tech/klayout/asap7.lydrc",
        "RCX_RULESETS": {"*": f"{config_ref}/rcx_patterns.rules"},
    }

    fill_cells = orfs.make_var("FILL_CELLS").split()
    decap_cells = [cell for cell in fill_cells if cell.startswith("DECAP")]
    buffer_cell, buffer_input, buffer_output = orfs.make_var(
        "MIN_BUF_CELL_AND_PORTS"
    ).split()
    tiehi_cell, tiehi_port = orfs.make_var("TIEHI_CELL_AND_PORT").split()
    tielo_cell, tielo_port = orfs.make_var("TIELO_CELL_AND_PORT").split()
    tap_cell = orfs.make_var("TAP_CELL_NAME")

    # ORFS keeps these ASAP7 library choices only in its old OpenLane adapter.
    cts_root_buffer = orfs.legacy_scl_var("ROOT_CLK_BUFFER")
    cts_buffers = orfs.legacy_scl_var("CTS_CLK_BUFFER_LIST").split()
    max_transition_ps = float(orfs.legacy_scl_var("DEFAULT_MAX_TRAN"))

    scl_config = {
        "SCL_POWER_PINS": ["VDD"],
        "SCL_GROUND_PINS": ["VSS"],
        "CELL_LEFS": TclExpression(f"[glob {scl_ref}/lef/*.lef]"),
        "CELL_GDS": TclExpression(f"[glob {scl_ref}/gds/*.gds]"),
        "CELL_VERILOG_MODELS": TclExpression(f"[glob {scl_ref}/verilog/*.v]"),
        "LIB": libraries,
        "FILL_CELLS": fill_cells,
        "DECAP_CELLS": decap_cells,
        "OUTPUT_CAP_LOAD": orfs.make_var("ABC_LOAD_IN_FF"),
        # ORFS records this ASAP7 value in ps; LibreLane requires ns.
        "DEFAULT_MAX_TRAN": max_transition_ps / 1000,
        "SYNTH_DRIVING_CELL": f"{buffer_cell}/{buffer_output}",
        "SYNTH_TIEHI_CELL": f"{tiehi_cell}/{tiehi_port}",
        "SYNTH_TIELO_CELL": f"{tielo_cell}/{tielo_port}",
        "SYNTH_BUFFER_CELL": f"{buffer_cell}/{buffer_input}/{buffer_output}",
        "SYNTH_EXCLUDED_CELL_FILE": f"{config_ref}/{SCL}/no_synth.cells",
        "PNR_EXCLUDED_CELL_FILE": f"{config_ref}/{SCL}/pnr_excluded.cells",
        "PLACE_SITE": orfs.make_var("PLACE_SITE"),
        "WELLTAP_CELL": tap_cell,
        "ENDCAP_CELL": tap_cell,
        # Padding must not be added to physical-only cells inserted after placement.
        "CELL_PAD_EXCLUDE": [tap_cell, "FILLER*", "DECAP*"],
        "CTS_ROOT_BUFFER": cts_root_buffer,
        "CTS_CLK_BUFFERS": cts_buffers,
        "GPL_CELL_PADDING": "2",
        "DPL_CELL_PADDING": "2",
        "SYNTH_LATCH_MAP": f"{config_ref}/{SCL}/cells_latch.v",
        "SYNTH_FA_MAP": f"{config_ref}/{SCL}/cells_adders.v",
    }

    write_config(
        config_root / "config.tcl",
        "ASAP7 process configuration for LibreLane",
        pdk_config,
    )
    write_config(
        scl_config_root / "config.tcl",
        "ASAP7 RVT 7.5-track library configuration for LibreLane",
        scl_config,
    )
    excluded_cells = orfs.make_var("DONT_USE_CELLS").split()
    (scl_config_root / "pnr_excluded.cells").write_text(
        "\n".join(excluded_cells) + "\n"
    )
    orfs.write_tracks(scl_config_root / "tracks.info")
    orfs.write_set_rc(config_root / "setRC.tcl")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orfs-platform", required=True, type=Path)
    parser.add_argument("--pdk-output", required=True, type=Path)
    args = parser.parse_args()
    build_configs(OrfsAsap7(args.orfs_platform), args.pdk_output)


if __name__ == "__main__":
    main()
