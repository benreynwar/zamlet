# RTL Style Notes

These are project style notes for Chisel/RTL work.

## Streams and Stages

- Use `Decoupled` or `Valid` for stages and request/response interfaces.
- Use `Decoupled` when the receiver needs backpressure.
- Use `Valid` when the receiver does not need backpressure.
- Put an explicit buffer between stream stages. Do not hand-build stage valid
  state with unrelated registers when a stream buffer is the stage boundary.
- Name real pipeline stages with the flow prefix and stage number:
  `req0`, `req1`, `req2`, `alloc0`, `alloc1`, etc.
- Use names like `req0Out` and `req1In` for the two sides of a stage buffer.
- Do not continue stage numbering across independent pipelines. Give each
  independent pipeline its own prefix.
- For stream split/join logic, it is okay for one output valid to depend on the
  other output ready when both outputs must fire together.

## Valid, Ready, Fire

- Use the standard terms `valid`, `ready`, and `fire`.
- Do not invent alternate words such as `busy` when the signal is really a
  stage `valid`.
- Use `fire` explicitly in state updates. Avoid helper names that hide whether
  `fire` is included.
- `fire` is fine as an enable condition. Be suspicious of using `fire` to drive
  an output `valid`.
- Keep `valid` independent of `ready` unless implementing an intentional stream
  split/join handshake.

## State

- Prefer `Valid(T)` for table entries or state that has a valid bit.
- Use `RegEnable` or `RegNext`. Avoid raw `Reg` / `RegInit`.
- Persistent table state is different from stream-stage state. Use table state
  for stored entries and buffers for stream stages.
- If a table entry is claimed by a side flow, clear or set the table bit that
  prevents it from being selected again, rather than adding extra exclusion
  logic in later stages.

## Logic Shape

- Avoid gratuitous one-use local wires. Add a named signal only when it clarifies
  ownership, stage, or repeated logic.
- Signal prefixes should show the owning flow/stage.
- Keep valid bits and payload conditions separate when that makes the data path
  clearer.
- Do not add defensive checks into critical path predicates. If an impossible
  state should be detected, add an explicit error wire and leave the normal flow
  predicate simple.

## Errors

- We generally do not recover from protocol errors.
- Bad or impossible states should raise error wires.
- Error checks should not gate normal behavior unless gating is required for the
  intended protocol.
- Register error wires at the output of the module that creates them.
- Do not re-register error wires that are only being forwarded from an internal
  module.
