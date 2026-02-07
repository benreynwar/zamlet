"""Plot and tabulate per-cycle queue depths, free resources, and throughput."""

import matplotlib.pyplot as plt
import numpy as np

from zamlet.monitor import Monitor


def dump_queue_table(monitor: Monitor, output_path: str,
                     cycle_min: int = 7250, cycle_max: int = 7500):
    """Write a per-cycle table of queue/ident/token metrics to a text file."""
    all_cycles = sorted(monitor.cycle_metrics.keys())
    cycles = [c for c in all_cycles if cycle_min <= c <= cycle_max]
    if not cycles:
        return

    # Collect keys
    kamlet_keys = set()
    token_keys = set()
    for c in cycles:
        m = monitor.cycle_metrics[c]
        kamlet_keys.update(m.kamlet_instr_queue_len.keys())
        token_keys.update(m.lamlet_free_tokens.keys())
    kamlet_keys = sorted(kamlet_keys)
    token_keys = sorted(token_keys)

    # Build header
    cols = ['cycle', 'l_buf', 'l_idents']
    for k in token_keys:
        cols.append(f'tok_k{k}')
    cols += ['l_add', 'l_rem', 'iq_snd', 'iq_rsp', 'net_snd', 'net_blk']
    for k in kamlet_keys:
        cols.append(f'kq_{k}')
    for k in kamlet_keys:
        cols.append(f'ka_{k}')
    for k in kamlet_keys:
        cols.append(f'kr_{k}')

    with open(output_path, 'w') as f:
        f.write('\t'.join(cols) + '\n')
        for c in cycles:
            m = monitor.cycle_metrics[c]
            row = [
                str(c),
                str(m.lamlet_instr_buf_len or 0),
                str(m.lamlet_free_idents or 0),
            ]
            for k in token_keys:
                row.append(str(m.lamlet_free_tokens.get(k, 0)))
            row.append(str(m.lamlet_instr_added))
            row.append(str(m.lamlet_instr_removed))
            row.append('1' if m.ident_query_sent else '')
            row.append('1' if m.ident_query_response else '')
            row.append('1' if m.instr_net_sent else '')
            row.append('1' if m.instr_net_blocked else '')
            for k in kamlet_keys:
                row.append(str(m.kamlet_instr_queue_len.get(k, 0)))
            for k in kamlet_keys:
                row.append(str(m.kamlet_instr_added.get(k, 0)))
            for k in kamlet_keys:
                row.append(str(m.kamlet_instr_removed.get(k, 0)))
            f.write('\t'.join(row) + '\n')


def _window_average(data, window):
    """Return windowed averages of data."""
    n = len(data) // window
    arr = np.array(data[:n * window]).reshape(n, window)
    return arr.mean(axis=1)


def plot_queues(monitor: Monitor, output_path: str, title: str = '',
                window: int = 1, cycle_min: int = 7250,
                cycle_max: int = 7500):
    """Plot queue depths, free resources, and throughput.

    Three panels sharing x-axis:
    1. Queue depths: lamlet buffer + kamlet queue per kamlet
    2. Free resources: free idents + free tokens per kamlet
    3. Throughput: lamlet instructions added/removed per cycle (windowed)
    """
    all_cycles = sorted(monitor.cycle_metrics.keys())
    cycles = [c for c in all_cycles if cycle_min <= c <= cycle_max]
    if not cycles:
        return

    buf_len = []
    free_idents = []
    free_tokens = {}
    instr_added = []
    instr_removed = []
    kamlet_queue = {}
    kamlet_added = {}
    kamlet_removed = {}

    # Collect all keys
    kamlet_keys = set()
    token_keys = set()
    for c in cycles:
        m = monitor.cycle_metrics[c]
        kamlet_keys.update(m.kamlet_instr_queue_len.keys())
        token_keys.update(m.lamlet_free_tokens.keys())

    iq_sent_cycles = []
    iq_resp_cycles = []
    net_sent = []
    net_blocked = []

    for c in cycles:
        m = monitor.cycle_metrics[c]
        buf_len.append(m.lamlet_instr_buf_len or 0)
        free_idents.append(m.lamlet_free_idents or 0)
        instr_added.append(m.lamlet_instr_added)
        instr_removed.append(m.lamlet_instr_removed)
        if m.ident_query_sent:
            iq_sent_cycles.append(c)
        if m.ident_query_response:
            iq_resp_cycles.append(c)
        net_sent.append(1 if m.instr_net_sent else 0)
        net_blocked.append(1 if m.instr_net_blocked else 0)
        for k in token_keys:
            free_tokens.setdefault(k, []).append(
                m.lamlet_free_tokens.get(k, 0))
        for k in kamlet_keys:
            kamlet_queue.setdefault(k, []).append(
                m.kamlet_instr_queue_len.get(k, 0))
            kamlet_added.setdefault(k, []).append(
                m.kamlet_instr_added.get(k, 0))
            kamlet_removed.setdefault(k, []).append(
                m.kamlet_instr_removed.get(k, 0))

    n = len(cycles) // window
    if n == 0:
        return
    w_cycles = _window_average(cycles, window)

    fig, (ax1, ax2, ax3, ax4) = plt.subplots(
        4, 1, figsize=(12, 13), sharex=True)
    if title:
        fig.suptitle(title)

    # Panel 1: Queue depths
    ax1.plot(w_cycles, _window_average(buf_len, window),
             label='lamlet buf', linewidth=1.5)
    for k in sorted(kamlet_keys):
        ax1.plot(w_cycles, _window_average(kamlet_queue[k], window),
                 label=f'kamlet {k}', linewidth=1)
    ax1.set_ylabel('Queue depth')
    ax1.legend(loc='upper right', fontsize='small')
    ax1.grid(True, alpha=0.3)

    # Panel 2: Free resources (dual y-axis)
    ax2.plot(w_cycles, _window_average(free_idents, window),
             label='free idents', linewidth=1.5, color='tab:blue')
    ax2.set_ylabel('Free idents', color='tab:blue')
    ax2.tick_params(axis='y', labelcolor='tab:blue')
    ax2_r = ax2.twinx()
    colors = ['tab:orange', 'tab:green', 'tab:red', 'tab:purple']
    for i, k in enumerate(sorted(token_keys)):
        ax2_r.plot(w_cycles, _window_average(free_tokens[k], window),
                   label=f'tokens k={k}', linewidth=1,
                   color=colors[i % len(colors)])
    ax2_r.set_ylabel('Free tokens', color='tab:orange')
    ax2_r.tick_params(axis='y', labelcolor='tab:orange')
    # Combine legends from both axes
    lines2, labels2 = ax2.get_legend_handles_labels()
    lines2r, labels2r = ax2_r.get_legend_handles_labels()
    ax2.legend(lines2 + lines2r, labels2 + labels2r,
               loc='upper right', fontsize='small')
    ax2.grid(True, alpha=0.3)

    # Panel 3: Throughput (lamlet + kamlet add/remove)
    ax3.plot(w_cycles, _window_average(instr_added, window),
             label='lamlet added', linewidth=1.5)
    ax3.plot(w_cycles, _window_average(instr_removed, window),
             label='lamlet removed', linewidth=1.5)
    for k in sorted(kamlet_keys):
        ax3.plot(w_cycles, _window_average(kamlet_added[k], window),
                 label=f'kamlet {k} added', linewidth=1, linestyle='--')
        ax3.plot(w_cycles, _window_average(kamlet_removed[k], window),
                 label=f'kamlet {k} removed', linewidth=1, linestyle=':')
    ax3.set_ylabel('Instrs/cycle')
    ax3.legend(loc='upper right', fontsize='small')
    ax3.grid(True, alpha=0.3)

    # Panel 4: Instruction network send/blocked
    ax4.bar(cycles, net_sent, width=1.0, label='net sent',
            color='tab:blue', alpha=0.7)
    ax4.bar(cycles, net_blocked, width=1.0, label='net blocked',
            color='tab:red', alpha=0.7)
    ax4.set_xlabel('Cycle')
    ax4.set_ylabel('Network')
    ax4.set_yticks([0, 1])
    ax4.legend(loc='upper right', fontsize='small')
    ax4.grid(True, alpha=0.3)

    # Ident query events as vertical lines
    for ax in (ax1, ax2, ax3, ax4):
        for c in iq_sent_cycles:
            ax.axvline(c, color='red', alpha=0.4, linewidth=0.8,
                       linestyle='--')
        for c in iq_resp_cycles:
            ax.axvline(c, color='green', alpha=0.4, linewidth=0.8,
                       linestyle='--')
    # Add to legend on first panel only
    if iq_sent_cycles:
        ax1.axvline(iq_sent_cycles[0], color='red', alpha=0.4,
                     linewidth=0.8, linestyle='--', label='iq send')
    if iq_resp_cycles:
        ax1.axvline(iq_resp_cycles[0], color='green', alpha=0.4,
                     linewidth=0.8, linestyle='--', label='iq response')
    ax1.legend(loc='upper right', fontsize='small')

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
