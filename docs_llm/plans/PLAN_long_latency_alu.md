# PLAN: long-latency ALU ops via per-jamlet ALU model

## Goal

Model arithmetic execution as a per-jamlet collection of pipelined / iterative
functional units, with multi-cycle completion tracked through the existing
`WaitingItem` machinery. This lets us correctly model the long-latency ops the
python model currently can't express at all:

- `vdiv.v{v,x}`, `vdivu.v{v,x}`, `vrem.v{v,x}`, `vremu.v{v,x}`
- `vfdiv.v{v,f}`, `vfrdiv.vf`
- `vfsqrt.v`
- `vfrec7.v`, `vfrsqrt7.v`

Today these have no implementation, and all existing vector arithmetic
collapses issue and writeback into the same call (`jamlet.write_vreg(...)` in
`kamlet/kinstructions.py`). The plan is to replace the synchronous path for
**every** per-jamlet ALU op with a uniform multi-cycle model. Single-cycle ops
become a degenerate latency-1 case in the same machinery.

In parallel, this plan lands the *framework* pieces needed by the fixed-point
arithmetic chapter (`vsadd`/`vssub`/`vaadd`/`vasub`/`vsmul`/`vssrl`/`vssra`/
`vnclip`) and by FP correctness (rounding mode, fflags accumulation). The
framework is:

- rounding-mode input and flag outputs on the ALU waiting item,
- per-jamlet sticky `fflags` and `vxsat` accumulators,
- sync-network OR-reduce primitive (shared between fflags and vxsat),
- CSR slots for `vxrm` / `vxsat` / `fcsr`.

The actual fixed-point op implementations, NaN-boxing fixes, `FCvt` rounding
fix, and soft-float reference are **not** in this plan; they land as
follow-ups once the framework is in place. See "Deferred".

Out of scope: any op that touches the network, memory, cross-jamlet
communication, or inter-kamlet sync — except the new OR-reduce primitive
on the sync network, which is framework. See "Boundary" below.

## Algorithm choices (drives latency + resource model)

Picked for lowest area; see conversation log for rationale.

- **FP divide / FP sqrt**: Newton-Raphson iterations on the existing FMA
  datapath, seeded from a small ROM. No dedicated FP divider.
- **`vfrec7` / `vfrsqrt7`**: direct ROM lookup + exponent adjust. These
  *are* the seed stage exposed as instructions; a software Newton-Raphson
  loop built on them would reproduce what `vfdiv` does internally.
- **Integer divide / remainder**: radix-2 SRT in a dedicated small iterative
  unit. Not pipelined (one op resident at a time). Data-independent latency
  (full-width) for modeling simplicity; early-termination is a later
  optimisation.
- **Int multiply / FMA / FP arith / fast int ALU**: pipelined, fixed latency.

The ROM for `vfrec7` is 128 × 7 bits; `vfrsqrt7` is 256 × 7 bits. Combined
~340 bytes per jamlet, implemented as a plain lookup table in python.

## Architectural model

### Per-jamlet pipes

Four independent functional units per jamlet:

| Pipe       | Latency (cycles) | Pipelined? | Ops                                        |
|------------|------------------|------------|--------------------------------------------|
| `int_alu`  | 1                | yes        | add/sub/logic/shift/compare/merge/vid/     |
|            |                  |            | broadcast, mask-register bitwise ops       |
| `imul`     | 3                | yes        | vmul / vmulh / vmulhsu / vmulhu            |
| `idiv`     | ~32              | no         | vdiv / vdivu / vrem / vremu                |
| `fma`      | 4 (single FMA)   | yes        | all FP arith; vfdiv/vfsqrt occupy the pipe |
|            | 10–14 (vfdiv/    |            | for a dependent N-R chain; vfrec7/vfrsqrt7 |
|            |  vfsqrt, TBD)    |            | are 1-cycle on this pipe                   |

Latencies are initial targets, subject to calibration once Chisel lands.
The model treats them as parameters (`ZamletParams` entries) so both sides
stay in sync.

"Pipelined" means "accepts one op per cycle". "Not pipelined" means one
op occupies the unit for its full latency before a new op can issue.

### Boundary

The jamlet ALU model owns exactly the ops listed above (per-jamlet,
data-in-data-out on the register slice). Everything else stays on its
existing path:

- Sync-network ops (`ReduceSync`, cross-jamlet reductions).
- Slides, `vrgather`, `vcompress` — data movement.
- Loads, stores, cache-backed ops.
- Scalar extract / insert (`vmv.x.s`, `vmv.s.x`, `vfmv.*`).
- J2J packet ops, `WriteRegElement` from the lamlet.
- Partial per-jamlet contribution of a reduction **does** run on the ALU
  (it's a local arithmetic op). The cross-jamlet reduction phase does not.

### Completion tracking

One `JamletAluWaitingItem(WaitingItem)` per **(jamlet, instr_ident)** pair.
A single long-latency kinstr produces `n_j` waiting items, one per jamlet,
all keyed by the kinstr's `instr_ident`.

Kamlet side: a counter keyed by `instr_ident`, initialised to `n_j` when
the kinstr dispatches, decremented when a jamlet's item calls back. When
the counter hits zero, the kamlet releases the RF lock and retires the
kinstr from the scoreboard (`kamlet.py:138-165` pending-free path).

### `JamletAluWaitingItem` shape

Fields:

- `instr_ident`: propagated from the kinstr.
- `pipe_tag`: one of {`int_alu`, `imul`, `idiv`, `fma`}. Drives which
  jamlet-side queue the item lives in.
- `cycles_remaining`: int, decremented once per cycle in `monitor_jamlet`.
- `dst_preg`, `byte_offset`, `result_bytes`: what to write at retirement.
- `span_id`: propagated through to the eventual `write_vreg` for RF lock
  bookkeeping.
- `rm_in`: rounding mode for this op (None for ops that don't use one).
  Sourced either from a kinstr field or from the current `vxrm` / `fcsr.rm`
  value snapshotted at dispatch — see "Rounding mode plumbing" below.
- `fflags_out`: per-element OR of RISC-V accrued exception flags
  (`NV|DZ|OF|UF|NX`) produced by this op on this jamlet. None for non-FP ops.
- `vxsat_out`: bool, set by fixed-point ops that saturated on this jamlet.
  None for non-fixed-point ops.

Dispatch-time paths populate `fflags_out` / `vxsat_out` alongside the
computed result. At retirement, the per-jamlet sticky accumulators
(`jamlet.sticky_fflags`, `jamlet.sticky_vxsat`) are OR-updated. No
cross-jamlet traffic per op.

Dispatch-time result computation:

- When the kinstr fires at the jamlet, operands are read from the RF slice,
  the result is computed immediately, and the bytes are stashed in the
  waiting item.
- `cycles_remaining` is set from the pipe latency.
- On retirement (`cycles_remaining == 0`), the item writes `result_bytes`
  into the destination preg and signals completion to the kamlet.

We pick dispatch-time compute (not retirement-time) because every long-
latency op in scope has data-independent latency under the chosen
algorithms. Retirement-time re-read would only matter for data-dependent
paths (early-terminating SRT), which we defer.

### Pipe occupancy

Each jamlet holds:

- An `int_alu` pipeline register (or short shift register if we model
  multi-cycle later) — pipelined, so a new op each cycle.
- An `imul` pipeline shift register — pipelined.
- A single-slot `idiv` resident register — busy flag blocks dispatch.
- An `fma` pipeline shift register — pipelined for single ops. When a
  multi-cycle op (`vfdiv` / `vfsqrt`) is iterating, subsequent FMA issues
  block until its N-R chain clears.

Dispatch from kamlet to jamlet stalls when the target pipe is not free.
"Not free" for pipelined pipes means `no slot available this cycle`;
for non-pipelined pipes means `busy flag set`.

### Rounding mode plumbing

CSR plumbing does **not** need a dispatch-time CSR read path. Rounding mode
reaches the ALU via one of two routes:

- **Kinstr field**: the kinstr carries `rm` directly. Used when the
  encoding already has it (e.g. FP arith ops with an explicit rm field,
  or fixed-point ops that inherit a compile-time-known vxrm).
- **Param write beforehand**: a prior kinstr writes `vxrm` / `fcsr.rm`
  into a kamlet-local register, and subsequent ALU ops snapshot that
  value at dispatch. No cross-jamlet read.

Both variants resolve to a concrete `rm_in` value on the waiting item
at dispatch time. The ALU model itself doesn't know which route was
used.

### Sticky flag accumulation and OR-reduce

Each jamlet owns a small sticky register pair:

- `sticky_fflags` — 5 bits, OR-accumulated from FP ops.
- `sticky_vxsat` — 1 bit, OR-accumulated from fixed-point ops.

These accumulate silently during normal execution. They are never reset
implicitly; only an explicit clear-flags kinstr clears them.

Software observes them via CSR reads (`frflags`, `csrr vxsat`). Those
reads are lamlet-side and trigger a **sync-network OR-reduce** across
all jamlets, delivering the reduced value to the lamlet. The reduce is
request-driven (lazy): no per-op sync traffic, only on CSR-read.

The OR-reduce primitive is new infrastructure and lands as part of this
plan. Precedent: the existing MIN reduce in `synchronization.py:Synchronizer`.
OR is structurally the same with a different combine op. Once built, it
serves both `vxsat` and `fflags`; the same primitive is also on the critical
path for the fixed-point TODO (TODO.md:162).

Width coverage for the OR-reduce: 5 bits (fflags) and 1 bit (vxsat) are
the immediate uses. Generalising to arbitrary widths is not required now,
but the primitive should be parametric so later consumers don't force a
second pass.

### Hazard interaction

Rename / scoreboard (`kamlet.py`) already tracks "preg is busy with a
pending write" and defers dependent dispatch. The ALU model slots in
cleanly: the preg is marked busy at dispatch, the waiting item clears it
at retirement. No new hazard concept required.

One subtlety: today the kamlet's execute path marks the preg busy and
writes in the same step, so the `pending_write` window is zero cycles
long. With the ALU model, that window stretches to the pipe latency. The
existing `pending_free` draining (`kamlet.py:138-165`) should handle this
without changes — it already tolerates in-flight references.

## Integer divide semantics

RISC-V specifies exact result values for the two edge cases; no traps.

- Divide by zero: `quotient = -1` (all 1s), `remainder = dividend`.
- Signed overflow (`INT_MIN / -1`): `quotient = INT_MIN`, `remainder = 0`.

Both are per-jamlet, per-element, purely local. Compute these in the
dispatch-time path alongside the normal divide, before enqueuing the
waiting item.

Spec ref: `riscv-isa-manual/src/v-st-ext.adoc`, vector integer divide
section (verify exact lines before citing in code).

## Work order

1. **Infra: `JamletAluWaitingItem`** — subclass of `WaitingItem` with the
   full field set above (pipe_tag, cycles_remaining, dst_preg/byte_offset/
   result_bytes/span_id, rm_in, fflags_out, vxsat_out). Per-jamlet
   registration / monitor loop wiring. Focused unit test with a latency-1
   stub op end-to-end (dispatch → retirement → preg visible to a dependent
   reader).
2. **Infra: per-jamlet pipes** — one pipelined shift-register abstraction,
   one single-slot resident abstraction. Parametrised by latency. Occupancy
   check + enqueue. Test in isolation.
3. **Infra: sticky flag accumulators** — add `sticky_fflags` (5 bits) and
   `sticky_vxsat` (1 bit) per jamlet. Retirement path OR-updates them when
   the waiting item's `fflags_out` / `vxsat_out` is non-null. No consumers
   yet; verify accumulation via a unit test that peeks at the jamlet state.
4. **Infra: OR-reduce sync primitive** — extend
   `synchronization.py:Synchronizer` with an OR combine op, parametric on
   width. Unit test with a hand-crafted per-jamlet input and a checked
   lamlet-delivered result. No CSR wiring yet.
5. **Migrate `int_alu` ops** — route `VArithV{v,x,i}Op`, `VCmpV*Op`,
   `VmergeV*`, `VBroadcastOp`, `VidOp`, `VmLogicMm`, `VUnaryOvOp` through
   the ALU model with `latency=1`. `rm_in`/`fflags_out`/`vxsat_out` all
   null. Correctness should be byte-identical with the pre-migration
   model. Run existing vector tests.
6. **Migrate FMA / imul ops** — route `vfadd/vfsub/vfmul/vfma*`,
   `vmul/vmulh*` through fma / imul pipes. Populate `rm_in` from the
   kinstr field where it exists; leave `fflags_out` null (actual fflag
   computation is deferred — see below). Calibrate latencies against
   existing tests.
7. **`vdiv` / `vrem` family** — new kinstrs + decode. Route through `idiv`
   pipe. Implement divide-by-zero and signed-overflow edge cases.
8. **`vfrec7` / `vfrsqrt7`** — new kinstrs + ROM tables. 1-cycle on `fma`.
   Per-element, no inter-lane interaction.
9. **`vfdiv` / `vfsqrt`** — new kinstrs. Internally: 3× or 4× FMA-pipe
   occupancy implementing Newton-Raphson, seeded from the same ROMs used
   by step 8. Correctness bit-pattern is *not* required to match the
   final Chisel exactly at this stage.
10. **Doc**: update `docs_llm/TODO.md` to reflect what landed (long-latency
    entry removed or shortened; fixed-point entry's "(a) sync-network
    OR-reduce primitive" prerequisite removed; FP correctness entry's
    OR-reduce dependency removed). Add plan-status entry.

Step 5 is where the migration risk lives — every existing vector test has
to pass after the code path changes. It's intentionally sequenced before
the new ops so that the new code is only ever added to a working
multi-cycle model, not a synchronous one.

Steps 3 and 4 land the framework for fflags/vxsat without any consumer
using it yet. That's deliberate: future plans (fixed-point ops, FP
correctness) plug into a working, tested substrate rather than standing
it up themselves.

## Risks / open questions

- **Latency numbers** are placeholders until Chisel FMA / multiplier
  pipeline depth is settled. Keep them in `ZamletParams` so the eventual
  calibration is one place.
- **Partial-vline ops** (vl < vlmax, masked writes): already pass through
  `write_vreg(..., byte_offset, span_id)`. The ALU model must preserve
  whatever byte-range invariant the caller expects; easiest is to stash
  `byte_offset` + `result_bytes` slice in the waiting item and call the
  same `write_vreg` at retirement.
- **Reservation station interaction**: today, `kamlet.py`'s dispatch loop
  calls `instruction.execute(kamlet)` synchronously and releases the
  station slot. With deferred retirement, station-slot release needs to
  happen at retirement, not dispatch. Double-check this doesn't collide
  with `reservation_station_depth`-level backpressure.
- **vfrec7 / vfrsqrt7 exact bit patterns**: RVV mandates specific ROM
  contents (spec table). Implementing the table verbatim is non-negotiable
  for conformance; flag if this is onerous.
- **Correct rounding for vfdiv / vfsqrt**: the RVV spec allows 1 ULP for
  these. Python-native float division already rounds to nearest-even at
  binary64; for FP32 destinations, round-to-nearest-even via `struct.pack`
  is fine. Correctness against the exact N-R iteration sequence (which
  may differ from native division in low bits) is a separate concern —
  start with native division for simplicity, refine only if we need
  Chisel bit-accurate behaviour.
- **`vstart` / masking**: honour whatever the rest of the vector pipeline
  does today. Don't introduce new undisturbed-tail behaviour in the ALU
  migration.

## Deferred

- **Fixed-point arithmetic chapter** (`vsadd` / `vssub` / `vaadd` / `vasub`
  / `vsmul` / `vssrl` / `vssra` / `vnclip` + `vxrm` / `vxsat`). Their
  framework lands here (OR-reduce primitive, sticky `vxsat`, `rm_in`
  field); the ops themselves are a follow-up plan. See TODO.md:159-176.
- **FP correctness fixes** — NaN-boxing, `FCvt` rounding mode, NaN payload
  propagation, fflags population from a soft-float reference. The
  framework is ready once this plan lands (OR-reduce, sticky `fflags`,
  `rm_in` plumbing); each correctness fix is a focused follow-up. See
  TODO.md:73-93 and `docs_llm/plans/PLAN_fp_nan_boxing.md`.
- **`vfredosum.vs` / `vfwredosum.vs`** (ordered float reductions). Unrelated
  to the ALU model; tracked in TODO.md:94-97.
- **Data-dependent int-divide latency** (early termination). Saves cycles
  in the model but complicates the waiting item. Add later only if
  profiling shows it matters.
- **Reduction of single-cycle ops to `latency=0` fast path**. Premature;
  the uniform latency-1 path is simple and correct.
- **Correct-rounded `vfdiv` / `vfsqrt`** matching an explicit N-R
  iteration count bit-for-bit. Needed eventually for Chisel parity; not
  needed for getting kernels running.
- **Long-latency aware scheduling in the compiler** (hoisting `vfdiv`
  earlier to cover its latency). Out of scope for the model; the model
  just reports the latency correctly.
