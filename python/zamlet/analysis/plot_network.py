"""Plot network congestion as a grid of arrows between jamlets."""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

from zamlet.message import Direction
from zamlet.monitor import Monitor, KamletSnapshot


# Tag state colors: 0=empty, 1=unsent(red), 2=pending(blue), 3=complete(green)
TAG_COLORS = {
    0: (0.85, 0.85, 0.85),
    1: (0.9, 0.2, 0.2),
    2: (0.2, 0.4, 0.9),
    3: (0.2, 0.8, 0.2),
}


def _draw_network(ax, monitor, cycles, all_positions):
    """Draw the network congestion arrows on the given axes."""
    n_cycles = len(cycles)

    present_count = {}
    blocked_count = {}

    for c in cycles:
        m = monitor.cycle_metrics[c]
        for (jx, jy, ch, direction), (present, moving) in m.router_outputs.items():
            if direction == Direction.H:
                continue
            key = (jx, jy, ch, direction)
            if present:
                present_count[key] = present_count.get(key, 0) + 1
                if not moving:
                    blocked_count[key] = blocked_count.get(key, 0) + 1

    dir_delta = {
        Direction.N: (0, -1),
        Direction.S: (0, 1),
        Direction.E: (1, 0),
        Direction.W: (-1, 0),
    }

    spacing = 0.08
    narrow = 0.03
    perp_offset = {
        (Direction.E, 0): (0, spacing),
        (Direction.E, 1): (0, narrow),
        (Direction.W, 0): (0, -narrow),
        (Direction.W, 1): (0, -spacing),
        (Direction.N, 0): (-spacing, 0),
        (Direction.N, 1): (-narrow, 0),
        (Direction.S, 0): (narrow, 0),
        (Direction.S, 1): (spacing, 0),
    }

    # Draw nodes
    for (jx, jy) in sorted(all_positions):
        px, py = jx, -jy
        ax.plot(px, py, 'ko', markersize=10, zorder=5)
        ax.annotate(f'({jx},{jy})', (px, py),
                    textcoords="offset points", xytext=(0, 12),
                    ha='center', fontsize=7, zorder=6)

    cmap = LinearSegmentedColormap.from_list(
        'blocked',
        [(0, 0.8, 0), (0, 0.4, 1), (1, 0, 0)])

    margin = 0.15
    for (jx, jy, ch, direction), n_present in present_count.items():
        dx, dy = dir_delta[direction]
        dest = (jx + dx, jy + dy)
        if dest not in all_positions:
            continue

        n_blocked = blocked_count.get((jx, jy, ch, direction), 0)
        present_frac = n_present / n_cycles
        blocked_frac = n_blocked / n_present

        color = cmap(blocked_frac)
        alpha = max(0.15, present_frac)

        ox, oy = perp_offset[(direction, ch)]
        x0 = jx + dx * margin + ox
        y0 = -(jy + dy * margin) + oy
        x1 = jx + dx * (1 - margin) + ox
        y1 = -(jy + dy * (1 - margin)) + oy

        arrow = mpatches.FancyArrowPatch(
            (x0, y0), (x1, y1),
            arrowstyle='->', mutation_scale=20,
            linewidth=3, color=color, alpha=alpha, zorder=3,
        )
        ax.add_patch(arrow)

    xs = [p[0] for p in all_positions]
    ys = [p[1] for p in all_positions]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)

    ax.set_aspect('equal')
    ax.set_xlim(x_min - 0.5, x_max + 0.5)
    ax.set_ylim(-y_max - 0.5, -y_min + 0.5)
    ax.set_xlabel('x')
    ax.set_ylabel('y (flipped)')
    ax.grid(True, alpha=0.15)

    return cmap


def _draw_kamlet_state(ax, snapshots: dict, cycle: int):
    """Draw kamlet state boxes showing instructions and WITEM tags.

    snapshots: {(kx, ky): KamletSnapshot} for the chosen cycle.
    """
    if not snapshots:
        ax.text(0.5, 0.5, 'No snapshots', ha='center', va='center',
                transform=ax.transAxes, fontsize=10, color='gray')
        return

    # Determine kamlet grid from snapshot keys
    k_positions = sorted(snapshots.keys())
    # Normalize to grid indices
    all_kx = sorted(set(kx for kx, _ in k_positions))
    all_ky = sorted(set(ky for _, ky in k_positions))
    kx_to_col = {kx: i for i, kx in enumerate(all_kx)}
    ky_to_row = {ky: i for i, ky in enumerate(all_ky)}
    n_cols = len(all_kx)
    n_rows = len(all_ky)

    # Layout: each kamlet box is placed in a grid cell
    # Box dimensions in data coords
    box_w = 0.85
    box_h = 0.85
    pad = 0.08

    for (kx, ky), snap in snapshots.items():
        col = kx_to_col[kx]
        row = ky_to_row[ky]
        # Box position: col goes right, row goes down (y flipped)
        bx = col
        by = -(row)

        # Draw box outline
        rect = mpatches.FancyBboxPatch(
            (bx - box_w / 2, by - box_h / 2), box_w, box_h,
            boxstyle='round,pad=0.02',
            facecolor='#f8f8f8', edgecolor='#666', linewidth=1,
            zorder=2)
        ax.add_patch(rect)

        # Label
        ax.text(bx, by + box_h / 2 - pad, f'({kx},{ky})',
                ha='center', va='top', fontsize=7, fontweight='bold',
                zorder=3)

        # Instructions (up to 2)
        y_cursor = by + box_h / 2 - pad - 0.10
        for iname, iident in snap.next_instructions[:2]:
            # Shorten long names
            short = iname
            if len(short) > 14:
                short = short[:13] + '..'
            label = f'{short} [{iident}]'
            ax.text(bx - box_w / 2 + pad, y_cursor, label,
                    ha='left', va='top', fontsize=5, fontfamily='monospace',
                    zorder=3)
            y_cursor -= 0.09

        if not snap.next_instructions:
            ax.text(bx - box_w / 2 + pad, y_cursor, '(empty queue)',
                    ha='left', va='top', fontsize=5, color='gray',
                    zorder=3)
            y_cursor -= 0.09

        # WITEMs with tag squares
        sq_size = 0.035
        sq_gap = 0.005
        max_tags_shown = 16

        for witem_snap in snap.witems:
            short = witem_snap.name
            if len(short) > 12:
                short = short[:11] + '..'
            label = f'{short}[{witem_snap.instr_ident}]'
            ax.text(bx - box_w / 2 + pad, y_cursor, label,
                    ha='left', va='top', fontsize=4.5,
                    fontfamily='monospace', zorder=3)
            y_cursor -= 0.07

            # Draw tag squares
            tags = witem_snap.tag_states[:max_tags_shown]
            n_tags = len(tags)
            row_start_x = bx - box_w / 2 + pad
            for ti, tstate in enumerate(tags):
                sx = row_start_x + ti * (sq_size + sq_gap)
                sy = y_cursor
                color = TAG_COLORS.get(tstate, TAG_COLORS[0])
                sq = mpatches.Rectangle(
                    (sx, sy), sq_size, sq_size,
                    facecolor=color, edgecolor='#aaa',
                    linewidth=0.3, zorder=3)
                ax.add_patch(sq)
            if n_tags > 0:
                y_cursor -= sq_size + sq_gap + 0.02

    # Set axis limits
    ax.set_xlim(-0.6, n_cols - 0.4)
    ax.set_ylim(-(n_rows - 1) - 0.6, 0.6)
    ax.set_aspect('equal')
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(f'Kamlet state (cycle {cycle})', fontsize=9)

    # Legend for tag colors
    legend_y = -(n_rows - 1) - 0.45
    legend_x = -0.4
    for label, tstate in [('unsent', 1), ('pending', 2), ('complete', 3)]:
        color = TAG_COLORS[tstate]
        sq = mpatches.Rectangle(
            (legend_x, legend_y), sq_size, sq_size,
            facecolor=color, edgecolor='#aaa', linewidth=0.3, zorder=3)
        ax.add_patch(sq)
        ax.text(legend_x + sq_size + 0.02, legend_y + sq_size / 2,
                label, ha='left', va='center', fontsize=5, zorder=3)
        legend_x += 0.25


def plot_network(monitor: Monitor, output_path: str, title: str = '',
                 cycle_min: int = 10600, cycle_max: int = 11400):
    """Plot network congestion and kamlet state side-by-side.

    Left pane: network arrows showing congestion.
    Right pane: per-kamlet instruction queue and WITEM tag states
    at the midpoint cycle of the window.
    """
    all_cycles = sorted(monitor.cycle_metrics.keys())
    cycles = [c for c in all_cycles if cycle_min <= c <= cycle_max]
    if not cycles:
        return

    # Collect jamlet positions
    all_positions = set()
    for c in cycles:
        m = monitor.cycle_metrics[c]
        for (jx, jy, ch, direction) in m.router_outputs:
            if direction != Direction.H:
                all_positions.add((jx, jy))
    if not all_positions:
        return
    all_positions.add((0, -1))  # lamlet node

    # Find midpoint cycle snapshot
    mid_cycle = cycles[len(cycles) // 2]
    mid_metrics = monitor.cycle_metrics.get(mid_cycle)
    snapshots = mid_metrics.kamlet_snapshots if mid_metrics else {}

    # Determine if we have snapshots to show
    has_snapshots = bool(snapshots)

    xs = [p[0] for p in all_positions]
    ys = [p[1] for p in all_positions]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)

    net_w = max(6, (x_max - x_min + 1) * 2)
    net_h = max(6, (y_max - y_min + 1) * 2)

    if has_snapshots:
        fig, (ax_net, ax_state) = plt.subplots(
            1, 2, figsize=(net_w + 5, net_h),
            gridspec_kw={'width_ratios': [net_w, 5]})
    else:
        fig, ax_net = plt.subplots(figsize=(net_w, net_h))
        ax_state = None

    if title:
        fig.suptitle(title, fontsize=11)

    cmap = _draw_network(ax_net, monitor, cycles, all_positions)

    # Colorbar for network pane
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(0, 1))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax_net, shrink=0.6, pad=0.02)
    cbar.set_label('Blocked fraction (when present)')

    if ax_state is not None:
        _draw_kamlet_state(ax_state, snapshots, mid_cycle)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
