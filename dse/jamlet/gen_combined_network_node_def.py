#!/usr/bin/env python3
"""Generate DEF template for CombinedNetworkNode hard macro.

This script must be run via: openroad -python <script> [args]

It uses OpenROAD's Tech API to load the tech LEF and query layer properties
for correct pin dimensions.
"""

import argparse
import json
import math
import sys
from decimal import Decimal

from openroad import Tech


def get_pin_geometry(tech_lef_path, v_layer_name, h_layer_name, v_width_mult=2, h_width_mult=2):
    """Get pin geometry from tech LEF layers."""
    ord_tech = Tech()
    ord_tech.readLef(tech_lef_path)

    db = ord_tech.getDB()
    tech = db.getTech()

    dbu = tech.getDbUnitsPerMicron()

    v_layer = tech.findLayer(v_layer_name)
    h_layer = tech.findLayer(h_layer_name)

    if v_layer is None:
        raise ValueError(f"Layer '{v_layer_name}' not found in tech LEF")
    if h_layer is None:
        raise ValueError(f"Layer '{h_layer_name}' not found in tech LEF")

    v_width = int(Decimal(v_width_mult) * v_layer.getWidth())
    h_width = int(Decimal(h_width_mult) * h_layer.getWidth())

    # Length = max(min_area / width, width)
    v_length = max(
        int(math.ceil(v_layer.getArea() * dbu * dbu / v_width)),
        v_width,
    )
    h_length = max(
        int(math.ceil(h_layer.getArea() * dbu * dbu / h_width)),
        h_width,
    )

    # Min spacing = width + layer spacing
    v_spacing = v_width + v_layer.getSpacing()
    h_spacing = h_width + h_layer.getSpacing()

    return {
        'dbu': dbu,
        'v_layer': v_layer_name,
        'h_layer': h_layer_name,
        'v_width': v_width,
        'h_width': h_width,
        'v_length': v_length,
        'h_length': h_length,
        'v_spacing': v_spacing,
        'h_spacing': h_spacing,
    }


def generate_decoupled_pins(prefix: str, data_width: int, is_flipped: bool) -> list[tuple[str, str]]:
    """Generate pin names for a Decoupled interface."""
    pins = []
    if is_flipped:
        pins.append((f"{prefix}_ready", "OUTPUT"))
        pins.append((f"{prefix}_valid", "INPUT"))
        for i in range(data_width):
            pins.append((f"{prefix}_bits_data[{i}]", "INPUT"))
        pins.append((f"{prefix}_bits_isHeader", "INPUT"))
    else:
        pins.append((f"{prefix}_ready", "INPUT"))
        pins.append((f"{prefix}_valid", "OUTPUT"))
        for i in range(data_width):
            pins.append((f"{prefix}_bits_data[{i}]", "OUTPUT"))
        pins.append((f"{prefix}_bits_isHeader", "OUTPUT"))
    return pins


def generate_pins(config: dict) -> list[tuple[str, str]]:
    """Generate all pins for CombinedNetworkNode from config."""
    pins = []

    data_width = config['wordBytes'] * 8
    n_a_channels = config['nAChannels']
    n_b_channels = config['nBChannels']
    x_pos_width = config['xPosWidth']
    y_pos_width = config['yPosWidth']

    pins.append(("clock", "INPUT"))
    pins.append(("reset", "INPUT"))

    for i in range(x_pos_width):
        pins.append((f"io_thisX[{i}]", "INPUT"))
    for i in range(y_pos_width):
        pins.append((f"io_thisY[{i}]", "INPUT"))

    for ch in range(n_a_channels):
        pins.extend(generate_decoupled_pins(f"io_aNi_{ch}", data_width, is_flipped=True))
        pins.extend(generate_decoupled_pins(f"io_aSi_{ch}", data_width, is_flipped=True))
        pins.extend(generate_decoupled_pins(f"io_aEi_{ch}", data_width, is_flipped=True))
        pins.extend(generate_decoupled_pins(f"io_aWi_{ch}", data_width, is_flipped=True))
        pins.extend(generate_decoupled_pins(f"io_aNo_{ch}", data_width, is_flipped=False))
        pins.extend(generate_decoupled_pins(f"io_aSo_{ch}", data_width, is_flipped=False))
        pins.extend(generate_decoupled_pins(f"io_aEo_{ch}", data_width, is_flipped=False))
        pins.extend(generate_decoupled_pins(f"io_aWo_{ch}", data_width, is_flipped=False))

    pins.extend(generate_decoupled_pins("io_aHi", data_width, is_flipped=True))
    pins.extend(generate_decoupled_pins("io_aHo", data_width, is_flipped=False))

    for ch in range(n_b_channels):
        pins.extend(generate_decoupled_pins(f"io_bNi_{ch}", data_width, is_flipped=True))
        pins.extend(generate_decoupled_pins(f"io_bSi_{ch}", data_width, is_flipped=True))
        pins.extend(generate_decoupled_pins(f"io_bEi_{ch}", data_width, is_flipped=True))
        pins.extend(generate_decoupled_pins(f"io_bWi_{ch}", data_width, is_flipped=True))
        pins.extend(generate_decoupled_pins(f"io_bNo_{ch}", data_width, is_flipped=False))
        pins.extend(generate_decoupled_pins(f"io_bSo_{ch}", data_width, is_flipped=False))
        pins.extend(generate_decoupled_pins(f"io_bEo_{ch}", data_width, is_flipped=False))
        pins.extend(generate_decoupled_pins(f"io_bWo_{ch}", data_width, is_flipped=False))

    pins.extend(generate_decoupled_pins("io_bHi", data_width, is_flipped=True))
    pins.extend(generate_decoupled_pins("io_bHo", data_width, is_flipped=False))

    return pins


def assign_pins_to_edges(pins: list[tuple[str, str]], config: dict) -> dict[str, list[str]]:
    """Assign pins to edges based on interface type.

    Pin ordering is designed for alignment:
    - West aWi aligns with East aEo (west-to-east flow)
    - West aWo aligns with East aEi (east-to-west flow)
    - South aSo aligns with North aNi (north-to-south flow)
    - South aSi aligns with North aNo (south-to-north flow)
    """
    n_a_channels = config['nAChannels']
    n_b_channels = config['nBChannels']

    def get_interface_pins(prefix: str) -> list[str]:
        return [name for name, _ in pins if name.startswith(prefix + "_") or name == prefix]

    # West: aWi, aWo, bWi, bWo, aHi, aHo, control signals
    west = []
    for ch in range(n_a_channels):
        west.extend(get_interface_pins(f"io_aWi_{ch}"))
        west.extend(get_interface_pins(f"io_aWo_{ch}"))
    for ch in range(n_b_channels):
        west.extend(get_interface_pins(f"io_bWi_{ch}"))
        west.extend(get_interface_pins(f"io_bWo_{ch}"))
    west.extend(get_interface_pins("io_aHi"))
    west.extend(get_interface_pins("io_aHo"))
    west.append("clock")
    west.append("reset")
    for i in range(config['xPosWidth']):
        west.append(f"io_thisX[{i}]")
    for i in range(config['yPosWidth']):
        west.append(f"io_thisY[{i}]")

    # East: aEo (aligns with aWi), aEi (aligns with aWo), same for B
    east = []
    for ch in range(n_a_channels):
        east.extend(get_interface_pins(f"io_aEo_{ch}"))
        east.extend(get_interface_pins(f"io_aEi_{ch}"))
    for ch in range(n_b_channels):
        east.extend(get_interface_pins(f"io_bEo_{ch}"))
        east.extend(get_interface_pins(f"io_bEi_{ch}"))

    # South: aSo (aligns with aNi), aSi (aligns with aNo), same for B
    # Order: aSo, aSi, bSo, bSi to align with north's aNi, aNo, bNi, bNo
    south = []
    for ch in range(n_a_channels):
        south.extend(get_interface_pins(f"io_aSo_{ch}"))
        south.extend(get_interface_pins(f"io_aSi_{ch}"))
    for ch in range(n_b_channels):
        south.extend(get_interface_pins(f"io_bSo_{ch}"))
        south.extend(get_interface_pins(f"io_bSi_{ch}"))

    # North: bHi, bHo (no south counterpart), then aNi, aNo, bNi, bNo
    north = []
    north.extend(get_interface_pins("io_bHi"))
    north.extend(get_interface_pins("io_bHo"))
    for ch in range(n_a_channels):
        north.extend(get_interface_pins(f"io_aNi_{ch}"))
        north.extend(get_interface_pins(f"io_aNo_{ch}"))
    for ch in range(n_b_channels):
        north.extend(get_interface_pins(f"io_bNi_{ch}"))
        north.extend(get_interface_pins(f"io_bNo_{ch}"))

    return {'west': west, 'east': east, 'north': north, 'south': south}


def calculate_die_dimensions(edges: dict[str, list[str]], geom: dict,
                             edge_margin: int) -> tuple[int, int]:
    """Calculate minimum die dimensions based on pin counts."""
    max_vertical_pins = max(len(edges['west']), len(edges['east']))
    die_height = 2 * edge_margin + (max_vertical_pins + 1) * geom['h_spacing']

    max_horizontal_pins = max(len(edges['north']), len(edges['south']))
    die_width = 2 * edge_margin + (max_horizontal_pins + 1) * geom['v_spacing']

    return die_width, die_height


def generate_def(pins: list[tuple[str, str]], edges: dict[str, list[str]],
                 die_width: int, die_height: int, geom: dict,
                 edge_margin: int) -> str:
    """Generate DEF file content."""
    pin_dir = {name: direction for name, direction in pins}

    # Use minimum spacing for pins
    h_spacing = geom['h_spacing']
    v_spacing = geom['v_spacing']

    # West: W-labelled pins at south, others at north
    west_w_pins = [p for p in edges['west'] if '_aW' in p or '_bW' in p]
    west_other_pins = [p for p in edges['west'] if p not in west_w_pins]

    west_pos = {}
    y = edge_margin
    for pin in west_w_pins:
        y += h_spacing
        west_pos[pin] = y

    y = die_height - edge_margin - len(west_other_pins) * h_spacing
    for pin in west_other_pins:
        west_pos[pin] = y
        y += h_spacing

    # East: all pins at south (to align with west W-labelled pins)
    east_pos = {}
    y = edge_margin
    for pin in edges['east']:
        y += h_spacing
        east_pos[pin] = y

    # North: bHi/bHo at west, N-labelled at east
    north_other_pins = [p for p in edges['north'] if '_bHi' in p or '_bHo' in p]
    north_n_pins = [p for p in edges['north'] if p not in north_other_pins]

    north_pos = {}
    x = edge_margin
    for pin in north_other_pins:
        x += v_spacing
        north_pos[pin] = x

    x = die_width - edge_margin - len(north_n_pins) * v_spacing
    for pin in north_n_pins:
        north_pos[pin] = x
        x += v_spacing

    # South: pins at east side
    south_pos = {}
    x = die_width - edge_margin - len(edges['south']) * v_spacing
    for pin in edges['south']:
        south_pos[pin] = x
        x += v_spacing

    lines = [
        "VERSION 5.8 ;",
        "DIVIDERCHAR \"/\" ;",
        "BUSBITCHARS \"[]\" ;",
        "DESIGN CombinedNetworkNode ;",
        f"UNITS DISTANCE MICRONS {geom['dbu']} ;",
        f"DIEAREA ( 0 0 ) ( {die_width} {die_height} ) ;",
        "",
    ]

    total_pins = sum(len(e) for e in edges.values())
    lines.append(f"PINS {total_pins} ;")

    h_half = geom['h_width'] // 2
    v_half = geom['v_width'] // 2

    # West/East use horizontal layer (pins extend inward horizontally)
    for pin in edges['west']:
        y = west_pos[pin]
        direction = pin_dir[pin]
        lines.append(f"    - {pin} + NET {pin} + DIRECTION {direction} + USE SIGNAL")
        lines.append(f"      + LAYER {geom['h_layer']} ( 0 {-h_half} ) ( {geom['h_length']} {h_half} )")
        lines.append(f"      + PLACED ( 0 {y} ) N ;")

    for pin in edges['east']:
        y = east_pos[pin]
        direction = pin_dir[pin]
        lines.append(f"    - {pin} + NET {pin} + DIRECTION {direction} + USE SIGNAL")
        lines.append(f"      + LAYER {geom['h_layer']} ( {-geom['h_length']} {-h_half} ) ( 0 {h_half} )")
        lines.append(f"      + PLACED ( {die_width} {y} ) N ;")

    # North/South use vertical layer (pins extend inward vertically)
    for pin in edges['north']:
        x = north_pos[pin]
        direction = pin_dir[pin]
        lines.append(f"    - {pin} + NET {pin} + DIRECTION {direction} + USE SIGNAL")
        lines.append(f"      + LAYER {geom['v_layer']} ( {-v_half} {-geom['v_length']} ) ( {v_half} 0 )")
        lines.append(f"      + PLACED ( {x} {die_height} ) N ;")

    for pin in edges['south']:
        x = south_pos[pin]
        direction = pin_dir[pin]
        lines.append(f"    - {pin} + NET {pin} + DIRECTION {direction} + USE SIGNAL")
        lines.append(f"      + LAYER {geom['v_layer']} ( {-v_half} 0 ) ( {v_half} {geom['v_length']} )")
        lines.append(f"      + PLACED ( {x} 0 ) N ;")

    lines.append("END PINS")
    lines.append("")
    lines.append("END DESIGN")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Generate DEF template for CombinedNetworkNode hard macro')
    parser.add_argument('--tech-lef', required=True, help='Tech LEF file')
    parser.add_argument('--config', required=True, help='JSON config file')
    parser.add_argument('--output', required=True, help='Output DEF file')
    parser.add_argument('--v-layer', default='met2', help='Vertical pin layer')
    parser.add_argument('--h-layer', default='met3', help='Horizontal pin layer')
    parser.add_argument('--edge-margin', type=float, default=20.0, help='Edge margin in microns')
    parser.add_argument('--die-area', help='Die area as "x0 y0 x1 y1" in microns (overrides auto-calc)')

    args = parser.parse_args()

    geom = get_pin_geometry(args.tech_lef, args.v_layer, args.h_layer)

    edge_margin = int(args.edge_margin * geom['dbu'])

    with open(args.config) as f:
        config = json.load(f)

    pins = generate_pins(config)
    edges = assign_pins_to_edges(pins, config)

    if args.die_area:
        x0, y0, x1, y1 = [float(v) for v in args.die_area.split()]
        die_width = int((x1 - x0) * geom['dbu'])
        die_height = int((y1 - y0) * geom['dbu'])
    else:
        die_width, die_height = calculate_die_dimensions(edges, geom, edge_margin)

    print(f"Pin geometry from {args.tech_lef}:", file=sys.stderr)
    print(f"  {args.v_layer}: width={geom['v_width']}, length={geom['v_length']}, "
          f"spacing={geom['v_spacing']}", file=sys.stderr)
    print(f"  {args.h_layer}: width={geom['h_width']}, length={geom['h_length']}, "
          f"spacing={geom['h_spacing']}", file=sys.stderr)
    print(f"Pins: {len(pins)}", file=sys.stderr)
    print(f"  West: {len(edges['west'])}, East: {len(edges['east'])}", file=sys.stderr)
    print(f"  North: {len(edges['north'])}, South: {len(edges['south'])}", file=sys.stderr)
    print(f"Die: {die_width/geom['dbu']:.1f}um x {die_height/geom['dbu']:.1f}um", file=sys.stderr)

    def_content = generate_def(pins, edges, die_width, die_height, geom, edge_margin)

    with open(args.output, 'w') as f:
        f.write(def_content)

    print(f"Wrote {args.output}", file=sys.stderr)


if __name__ == '__main__':
    main()
