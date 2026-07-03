# Waveform Debugging

Use waveform tools when a failing hardware test needs timing-level evidence.
Prefer inspecting real handshakes and state transitions over guessing from the
test code.

The repo `nix-shell` includes `pywellen` for reading waveforms. Shared waveform
helper code lives in `python/zamlet/analysis/wave_query.py`.

Use helpers when they make the investigation clearer, especially for repeatable
queries such as clock-edge sampling and valid/ready handshakes.

When debugging starts to require repetitive ad hoc scripts, consider adding a
small helper. Keep helpers focused on the query shape that is actually being
repeated. Avoid building broad tooling before the useful pattern is clear.

Pay attention to whether a helper is helping. If a helper is awkward,
misleading, or too specific to reuse, simplify it or delete it. The goal is
better evidence with less manual error, not more code.
