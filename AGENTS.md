# Agent Instructions

Before making RTL/Chisel edits, read and follow `docs_llm/rtl-style.md`.

Before making Python test edits, read and follow `docs_llm/python-test-style.md`.

Before debugging waveforms, read `docs_llm/waveform-debugging.md`.

When checking how LibreLane behaves, use the local source at `~/Code/librelane`.

Keep edits small and explain them before applying patches.

Prefer updating call sites to the new approach over adding compatibility shims
for old names or old behavior.

Let required inputs fail when missing or malformed. Do not hide configuration,
test, or tool errors with defaults unless the default is an intentional part of
the interface.

Do not run Python parse-only checks.
