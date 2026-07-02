"""Small helpers for querying Zamlet waveforms with pywellen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import pywellen

from zamlet.control_structures import unpack_int_to_fields


TIME_MULTIPLIERS = {
    "ps": 1,
    "ns": 1_000,
    "us": 1_000_000,
    "ms": 1_000_000_000,
}


@dataclass(frozen=True)
class HandshakeSample:
    time_ps: int
    edge: str
    scope: str
    valid: int | None
    ready: int | None
    fields: dict[str, int | None]

    @property
    def accepted(self) -> bool:
        return self.valid == 1 and self.ready == 1


@dataclass(frozen=True)
class SignalChangeSample:
    time_ps: int
    edge: str
    values: dict[str, int | None]


@dataclass(frozen=True)
class PacketHeaderSample:
    time_ps: int
    edge: str
    scope: str
    accepted: bool
    data: int | None
    fields: dict[str, int | None]


def parse_time_ps(text: str | int | None) -> int | None:
    if text is None or isinstance(text, int):
        return text
    value = text.strip().lower()
    for suffix, multiplier in TIME_MULTIPLIERS.items():
        if value.endswith(suffix):
            return int(float(value[: -len(suffix)]) * multiplier)
    return int(value)


def bits_to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value)
    if not text or any(char in text.lower() for char in "xz"):
        return None
    return int(text, 2)


def load_waveform(path: str) -> pywellen.Waveform:
    return pywellen.Waveform(path)


def clock_edges(
    waveform: pywellen.Waveform,
    clock_path: str,
    *,
    start_ps: int | None = None,
    end_ps: int | None = None,
    edge: str = "rise",
) -> Iterable[tuple[int, str]]:
    clock = waveform.get_signal_from_path(clock_path)
    previous = None
    for time_ps, value in clock.all_changes():
        if start_ps is not None and time_ps < start_ps:
            previous = value
            continue
        if end_ps is not None and time_ps > end_ps:
            break
        edge_name = None
        if previous == 0 and value == 1:
            edge_name = "rise"
        elif previous == 1 and value == 0:
            edge_name = "fall"
        elif previous is None:
            edge_name = "initial"
        previous = value
        if edge == "both" and edge_name in ("rise", "fall"):
            yield time_ps, edge_name
        elif edge_name == edge:
            yield time_ps, edge_name


def sample_handshake(
    waveform: pywellen.Waveform,
    *,
    clock_path: str,
    scope: str,
    valid_name: str,
    ready_name: str,
    field_names: dict[str, str],
    start_ps: int | None = None,
    end_ps: int | None = None,
    edge: str = "rise",
) -> Iterable[HandshakeSample]:
    valid = waveform.get_signal_from_path(f"{scope}.{valid_name}")
    ready = waveform.get_signal_from_path(f"{scope}.{ready_name}")
    field_signals = {
        name: waveform.get_signal_from_path(f"{scope}.{signal_name}")
        for name, signal_name in field_names.items()
    }
    for time_ps, edge_name in clock_edges(
        waveform, clock_path, start_ps=start_ps, end_ps=end_ps, edge=edge
    ):
        yield HandshakeSample(
            time_ps=time_ps,
            edge=edge_name,
            scope=scope,
            valid=bits_to_int(valid.value_at_time(time_ps)),
            ready=bits_to_int(ready.value_at_time(time_ps)),
            fields={
                name: bits_to_int(signal.value_at_time(time_ps))
                for name, signal in field_signals.items()
            },
        )


def sample_signal_changes(
    waveform: pywellen.Waveform,
    *,
    clock_path: str,
    signal_paths: Iterable[str],
    start_ps: int | None = None,
    end_ps: int | None = None,
    edge: str = "rise",
) -> Iterable[SignalChangeSample]:
    signals = {
        path: waveform.get_signal_from_path(path)
        for path in signal_paths
    }
    previous_values = {path: None for path in signals}
    for time_ps, edge_name in clock_edges(
        waveform, clock_path, start_ps=start_ps, end_ps=end_ps, edge=edge
    ):
        changed_values = {}
        for path, signal in signals.items():
            value = bits_to_int(signal.value_at_time(time_ps))
            if value != previous_values[path]:
                changed_values[path] = value
                previous_values[path] = value
        if changed_values:
            yield SignalChangeSample(
                time_ps=time_ps,
                edge=edge_name,
                values=changed_values,
            )


def sample_packet_headers(
    waveform: pywellen.Waveform,
    *,
    clock_path: str,
    scope: str,
    packet_prefix: str,
    field_specs: Iterable[tuple[str, int]],
    start_ps: int | None = None,
    end_ps: int | None = None,
    edge: str = "rise",
    accepted_only: bool = True,
) -> Iterable[PacketHeaderSample]:
    valid = waveform.get_signal_from_path(f"{scope}.{packet_prefix}_valid")
    ready = waveform.get_signal_from_path(f"{scope}.{packet_prefix}_ready")
    is_header = waveform.get_signal_from_path(
        f"{scope}.{packet_prefix}_bits_isHeader"
    )
    data = waveform.get_signal_from_path(f"{scope}.{packet_prefix}_bits_data")
    fields = list(field_specs)

    for time_ps, edge_name in clock_edges(
        waveform, clock_path, start_ps=start_ps, end_ps=end_ps, edge=edge
    ):
        accepted = (
            bits_to_int(valid.value_at_time(time_ps)) == 1
            and bits_to_int(ready.value_at_time(time_ps)) == 1
            and bits_to_int(is_header.value_at_time(time_ps)) == 1
        )
        if accepted_only and not accepted:
            continue
        if not accepted and bits_to_int(is_header.value_at_time(time_ps)) != 1:
            continue
        data_value = bits_to_int(data.value_at_time(time_ps))
        yield PacketHeaderSample(
            time_ps=time_ps,
            edge=edge_name,
            scope=scope,
            accepted=accepted,
            data=data_value,
            fields=(
                {name: None for name, _ in fields if name != "_padding"}
                if data_value is None
                else unpack_int_to_fields(data_value, fields)
            ),
        )
