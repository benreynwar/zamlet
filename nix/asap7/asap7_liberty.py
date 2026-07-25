#!/usr/bin/env python3
"""Normalize ASAP7 Liberty timing and capacitance units for LibreLane."""

from __future__ import annotations

import argparse
import gzip
from pathlib import Path
from typing import Iterator

import numpy as np
from liberty.parser import parse_liberty
from liberty.types import EscapedString, Group


TIME_SCALE = 1.0 / 1000.0
CAPACITANCE_SCALE = 1.0 / 1000.0

TIME_VARIABLES = {
    "constrained_pin_transition",
    "input_net_transition",
    "input_transition_time",
    "related_pin_transition",
}
CAPACITANCE_VARIABLES = {"total_output_net_capacitance"}
UNSCALED_VARIABLES = {"normalized_voltage"}

TIME_ATTRIBUTES = {
    "default_max_transition",
    "max_transition",
}
CAPACITANCE_ATTRIBUTES = {
    "capacitance",
    "default_output_pin_cap",
    "fall_capacitance",
    "fall_capacitance_range",
    "max_capacitance",
    "rise_capacitance",
    "rise_capacitance_range",
}
TIME_VALUE_GROUPS = {
    "cell_fall",
    "cell_rise",
    "fall_constraint",
    "fall_transition",
    "normalized_driver_waveform",
    "rise_constraint",
    "rise_transition",
}
# Liberty internal-power values use voltage_unit * current_unit * time_unit.
# ASAP7's 1V * 1mA * 1ps gives fJ/transition. Normalizing time_unit to
# LibreLane's 1ns changes the table unit to pJ/transition, so divide the
# numeric values by 1000 to preserve the physical energy per transition.
POWER_VALUE_GROUPS = {
    "fall_power",
    "rise_power",
}


def walk_groups(group: Group) -> Iterator[Group]:
    yield group
    for child in group.groups:
        yield from walk_groups(child)


def scale_value(value: object, scale: float) -> object:
    if isinstance(value, list):
        return [scale_value(item, scale) for item in value]
    if isinstance(value, (float, int)):
        return float(format_number(value * scale))
    raise TypeError(f"Cannot scale Liberty value {value!r}")


def format_number(value: float) -> str:
    return f"{value:.15g}"


def scale_array(group: Group, name: str, scale: float) -> None:
    values = group.get_array(name) * scale
    rows = np.atleast_2d(values)
    group[name] = [
        EscapedString(", ".join(format_number(value) for value in row))
        for row in rows
    ]


def template_variables(library: Group) -> dict[str, dict[int, str]]:
    templates: dict[str, dict[int, str]] = {}
    for group in library.groups:
        if group.group_name not in {"lu_table_template", "power_lut_template"}:
            continue
        if len(group.args) != 1:
            raise ValueError(f"Invalid template arguments: {group.args!r}")
        variables = {
            axis: group[f"variable_{axis}"]
            for axis in (1, 2, 3)
            if f"variable_{axis}" in group
        }
        templates[str(group.args[0])] = variables
    return templates


def group_variables(
    group: Group, templates: dict[str, dict[int, str]]
) -> dict[int, str]:
    if group.group_name in {"lu_table_template", "power_lut_template"}:
        return {
            axis: group[f"variable_{axis}"]
            for axis in (1, 2, 3)
            if f"variable_{axis}" in group
        }
    if group.args:
        return templates.get(str(group.args[0]), {})
    return {}


def normalize_library(library: Group) -> Group:
    if library["time_unit"] != EscapedString("1ps"):
        raise ValueError(f"Expected time_unit 1ps, got {library['time_unit']!r}")

    capacitance_unit = library["capacitive_load_unit"]
    if capacitance_unit != [1.0, "ff"]:
        raise ValueError(
            "Expected capacitive_load_unit (1, ff), "
            f"got {capacitance_unit!r}"
        )

    library["time_unit"] = EscapedString("1ns")
    library["capacitive_load_unit"] = [1, "pf"]

    templates = template_variables(library)
    for group in walk_groups(library):
        for name in TIME_ATTRIBUTES:
            if name in group:
                group[name] = scale_value(group[name], TIME_SCALE)
        for name in CAPACITANCE_ATTRIBUTES:
            if name in group:
                group[name] = scale_value(group[name], CAPACITANCE_SCALE)

        for axis, variable in group_variables(group, templates).items():
            index = f"index_{axis}"
            if index not in group:
                continue
            if variable in TIME_VARIABLES:
                scale_array(group, index, TIME_SCALE)
            elif variable in CAPACITANCE_VARIABLES:
                scale_array(group, index, CAPACITANCE_SCALE)
            elif variable not in UNSCALED_VARIABLES:
                raise ValueError(
                    f"Unknown Liberty table variable {variable!r} "
                    f"in {group.group_name}"
                )

        if group.group_name in TIME_VALUE_GROUPS and "values" in group:
            scale_array(group, "values", TIME_SCALE)
        elif group.group_name in POWER_VALUE_GROUPS and "values" in group:
            scale_array(group, "values", TIME_SCALE)
        elif "values" in group:
            raise ValueError(
                f"Unknown units for values in Liberty group {group.group_name}"
            )

    return library


def read_liberty(path: Path) -> str:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as liberty:
        return liberty.read()


def write_liberty(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    if path.suffix == ".gz":
        with temporary.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
                compressed.write(text.encode())
    else:
        temporary.write_text(text)
    temporary.replace(path)


def normalize_file(path: Path) -> None:
    library = parse_liberty(read_liberty(path))
    normalize_library(library)
    write_liberty(path, str(library) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("liberty", nargs="+", type=Path)
    args = parser.parse_args()

    for path in args.liberty:
        normalize_file(path)


if __name__ == "__main__":
    main()
