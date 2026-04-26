# PLAN: long-latency ALU ops via per-jamlet ALU model

## Goal

Model arithmetic execution as a per-jamlet collection of pipelined / iterative
functional units, with multi-cycle completion tracked by one coroutine per
in-flight kinstr on the kamlet (the existing async style — under
uniform-broadcast dispatch the jamlets run in lockstep, so a single coroutine
drives the per-jamlet fan-out at write time). This is **not** the
`WaitingItem` / `cache_table.waiting_items` machinery, which is for
memory/cache transactions; the existing `rf_info` register-file lock is
sufficient as the in-flight scoreboard. This lets us correctly model the
long-latency ops the python model currently can't express at all:

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

- rounding-mode input and flag outputs on the ALU coroutine,
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

ALU op completion uses the existing `rf_info` register-file lock as the
in-flight scoreboard — no new table is needed. Today every kinstr does
`rf_token = rf_info.start(read_pregs, write_pregs)` at dispatch and
`rf_info.finish(rf_token, ...)` after its synchronous compute+write
(`kinstructions.py:470-481`). For deferred ALU we keep `start` in
`execute` but split `finish`: read-finish happens inside the spawned
coroutine after the read step (leaving room for a future read-latency
model); write-finish happens after the write step.

`execute` stays synchronous — it allocates the RF token and spawns a
single per-kinstr coroutine, then returns. The RS slot frees the same
cycle, exactly as today. The jamlets run in lockstep under
uniform-broadcast dispatch, so one coroutine drives the per-jamlet
fan-out at write time; we don't need n_j coroutines.

The framework lives as methods on the `AluKInstr` base class
(`kinstructions.py`). `execute` claims the rf_info token (including any
declared resources — see "Pipe occupancy" below) and spawns
`_run_alu`, which calls the subclass's `alu_compute` to read operands +
produce staged `AluResult`s, finishes reads immediately, awaits
`latency` cycles, commits the staged writes (also OR-folding any
`fflags` / `vxsat` outputs into the per-jamlet sticky regs), and
finishes writes. Resource releases run on independent spawned
coroutines, each releasing its resource after its declared occupancy
(see "Pipe occupancy").

The dependent-reader stall mechanism is unchanged: `_is_preg_idle`
(`kamlet.py:328`) keys off `rf_info.write[preg]`, which now stays
non-None for `latency` cycles instead of zero — exactly the desired
behaviour. The existing `_drain_pending_pregs` loop (`kamlet.py:317`)
picks up retired pregs as it does today.

This is **not** a `WaitingItem` and **not** an entry on
`cache_table.waiting_items`. Those are for memory/cache transactions
whose hazard machinery (read-set / write-set / cache-slot scans) doesn't
apply to per-jamlet ALU ops; `rf_info` already handles read/write
hazards per-preg. `instr_ident` is freed at dispatch — ALU ops have no
inbound response packets, so they shouldn't keep a response-tag slot
reserved past dispatch.

### Coroutine inputs

The coroutine closes over the kinstr (which provides `renamed`,
`latency`, the per-element `compute`, `get_rm`, and any kinstr-level
fields like `span_id`) and the `rf_token` from `rf_info.start`. That's
all the dispatch path passes in.

`rm_in` is sourced inside the coroutine via `instruction.get_rm(kamlet)`
— a kinstr field if the encoding has one, else a read of the kamlet-local
`vxrm` / `fcsr.rm`. The existing scoreboard ordering guarantees any
prior `csrw` to those CSRs has retired before this kinstr's coroutine
runs, so no dispatch-time snapshot is needed.

Per-jamlet outputs are computed inside the coroutine (post-read):

- Result bytes, written via `write_vreg(..., span_id)`.
- `fflags` (5 bits, FP ops only) — OR-updated into
  `jamlet.sticky_fflags`.
- `vxsat` (1 bit, fixed-point ops only) — OR-updated into
  `jamlet.sticky_vxsat`.

Compute happens inside the coroutine immediately after the read step,
not at dispatch. All long-latency ops in scope have data-independent
latency under the chosen algorithms, so the fixed `latency` await is
correct; retirement-time re-read would only matter for data-dependent
paths (early-terminating SRT), which we defer.

No cross-jamlet traffic per op; sticky accumulator updates are local.

### Pipe occupancy

Pipelined pipes (`int_alu`, `imul`, `fma`-single-op) need no occupancy
datastructure. Coroutines stack — each one holds its `rf_info` write
token for `latency` cycles via its `await` loop, which is structurally
equivalent to "the unit accepts one op per cycle".

Non-pipelined pipes are tracked as named *resources* on `rf_info`,
mirroring the read/write-register machinery already there. The
`Resources` enum (in `register_file_slot.py`) currently lists `IDIV`
and `FMA`; a kamlet's `rf_info` is constructed with `list(Resources)`,
exposing one slot per resource that holds the current claimant's token
or `None`.

`AluKInstr` subclasses opt in by declaring a class-level dict
`resources: dict[Resources, int]` mapping each resource to the number
of cycles it is held. `execute` claims them by passing
`resources=list(self.resources.keys())` to `rf_info.start`; `_run_alu`
spawns one `_release_resource(...)` coroutine per resource, each
releasing its resource via `rf_info.finish(token, resources=[r])`
after its declared occupancy. `Kamlet.is_ready` defers dispatch when
any of `instr.resources` is held.

Concretely:

- `vdiv` / `vrem` declare `{Resources.IDIV: <idiv_latency>}`.
- Multi-cycle `vfdiv` / `vfsqrt` declare `{Resources.FMA: <nr_window>}`
  to hold the FMA pipe across the Newton-Raphson iteration window;
  single FMA ops leave `resources` empty.

Resources live on the kamlet (one coroutine per kinstr drives them).
Under uniform-broadcast dispatch and data-independent latency, all
jamlets' pipes are aligned, so a single kamlet-side resource per pipe
correctly gates dispatch. Decoupling resource release from
write-finish lets a future op declare an occupancy shorter than its
total latency (e.g. an iterative pipe that releases its critical unit
before write-back), without changing the framework.

### Rounding mode plumbing

Rounding mode reaches the ALU via one of two routes, resolved inside
`_run_alu` by `instruction.get_rm(kamlet)`:

- **Kinstr field**: the kinstr carries `rm` directly. Used when the
  encoding already has it (e.g. FP arith ops with an explicit rm field,
  or fixed-point ops that inherit a compile-time-known vxrm).
- **Kamlet-local CSR**: a prior `csrw` kinstr writes `vxrm` / `fcsr.rm`
  into a kamlet-local register; the coroutine reads it at compute time.
  The existing scoreboard ordering guarantees the prior `csrw` has
  retired before this kinstr's coroutine runs, so no dispatch-time
  snapshot is needed. No cross-jamlet read.

Both routes resolve to a concrete `rm_in` value the compute step
consumes. The framework itself doesn't know which route was used.

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
pending write" via `rf_info.write[preg]`. The ALU model slots in cleanly:
`rf_info.start` at dispatch sets the write token, and the coroutine's
deferred `rf_info.finish(write_regs=...)` clears it after the latency
wait. No new hazard concept required.

One subtlety: today the kamlet's execute path marks the preg busy and
writes in the same step, so the `pending_write` window is zero cycles
long. With the ALU model, that window stretches to the pipe latency. The
existing `pending_free` draining (`kamlet.py:317-344`) handles this
without changes — `_is_preg_idle` already keys off `rf_info.write[preg]`
and tolerates the now-non-zero pending-write window.

## Integer divide semantics

RISC-V specifies exact result values for the two edge cases; no traps.

- Divide by zero: `quotient = -1` (all 1s), `remainder = dividend`.
- Signed overflow (`INT_MIN / -1`): `quotient = INT_MIN`, `remainder = 0`.

Both are per-jamlet, per-element, purely local. Compute these in the
coroutine's compute step alongside the normal divide.

Spec ref: `riscv-isa-manual/src/v-st-ext.adoc`, vector integer divide
section (verify exact lines before citing in code).

## Work order

1. **Infra: AluKInstr framework + sticky regs** — add the `AluKInstr`
   base class (`execute` allocates the rf_info token, spawns
   `_run_alu`, which calls `alu_compute`, finishes reads, awaits
   `latency`, commits staged writes, finishes writes). Split
   `rf_info.finish` so reads finish post-`alu_compute` and writes
   finish after the latency wait (the API at `register_file_slot.py`
   already accepts `read_regs=` / `write_regs=` independently). Add
   `sticky_fflags` (5 bits) and `sticky_vxsat` (1 bit) per jamlet,
   OR-updated inside `_run_alu`. Unit test a latency-1 stub op
   end-to-end (dispatch → write → preg visible to a dependent
   reader); a second test that peeks at sticky-reg accumulation.
2. **Infra: pipe-occupancy resources** — extend `KamletRegisterFile`
   with a `Resources` enum and a `resources` dict tracking each
   resource's current claimant token; `start`/`finish` accept a
   `resources=` kwarg. `AluKInstr` declares `resources: dict[Resources,
   int]` (resource → cycles held); `execute` claims them at dispatch,
   `_run_alu` spawns one release coroutine per resource. `is_ready`
   defers when any of the kinstr's resources is held. Unit test issues
   back-to-back ops claiming the same resource and checks dispatch
   defers correctly.
3. **Infra: OR-reduce sync primitive** — extend
   `synchronization.py:Synchronizer` with an OR combine op, parametric
   on width. Unit test with a hand-crafted per-jamlet input and a
   checked lamlet-delivered result. No CSR wiring yet.
4. **Migrate `int_alu` ops** — route `VArithV{v,x,i}Op`, `VCmpV*Op`,
   `VmergeV*`, `VBroadcastOp`, `VidOp`, `VmLogicMm`, `VUnaryOvOp`
   through the ALU model with `latency=1`. `rm_in`/`fflags_out`/
   `vxsat_out` all null. Correctness should be byte-identical with
   the pre-migration model. Run existing vector tests.
5. **Migrate FMA / imul ops** — route `vfadd/vfsub/vfmul/vfma*`,
   `vmul/vmulh*` through fma / imul pipes. Populate `rm_in` from the
   kinstr field where it exists; leave `fflags_out` null (actual
   fflag computation is deferred — see below). Calibrate latencies
   against existing tests.
6. **`vdiv` / `vrem` family** — new kinstrs + decode. Route through
   `idiv` pipe. Implement divide-by-zero and signed-overflow edge
   cases.
7. **`vfrec7` / `vfrsqrt7`** — new kinstrs + ROM tables. 1-cycle on
   `fma`. Per-element, no inter-lane interaction.
8. **`vfdiv` / `vfsqrt`** — new kinstrs. Internally: 3× or 4× FMA-pipe
   occupancy implementing Newton-Raphson, seeded from the same ROMs
   used by step 7. Correctness bit-pattern is *not* required to match
   the final Chisel exactly at this stage.
9. **Doc**: update `docs_llm/TODO.md` to reflect what landed
   (long-latency entry removed or shortened; fixed-point entry's
   "(a) sync-network OR-reduce primitive" prerequisite removed; FP
   correctness entry's OR-reduce dependency removed). Add plan-status
   entry.

Step 4 is where the migration risk lives — every existing vector test
has to pass after the code path changes. It's intentionally sequenced
before the new ops so that the new code is only ever added to a
working multi-cycle model, not a synchronous one.

Step 1 lands the framework for fflags/vxsat alongside the coroutine
itself; steps 2 and 3 add the rest of the substrate. Future plans
(fixed-point ops, FP correctness) plug into a working, tested base
rather than standing it up themselves.

## Risks / open questions

- **Latency numbers** are placeholders until Chisel FMA / multiplier
  pipeline depth is settled. Keep them in `ZamletParams` so the eventual
  calibration is one place.
- **Partial-vline ops** (vl < vlmax, masked writes): already pass through
  `write_vreg(..., byte_offset, span_id)`. The coroutine's per-jamlet
  result carries `byte_offset` and the bytes slice and calls the same
  `write_vreg` at the write step — no new byte-range handling required.
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
  in the model but complicates the coroutine (compute step would need
  to also drive the wait length). Add later only if profiling shows it
  matters.
- **Reduction of single-cycle ops to `latency=0` fast path**. Premature;
  the uniform latency-1 path is simple and correct.
- **Correct-rounded `vfdiv` / `vfsqrt`** matching an explicit N-R
  iteration count bit-for-bit. Needed eventually for Chisel parity; not
  needed for getting kernels running.
- **Long-latency aware scheduling in the compiler** (hoisting `vfdiv`
  earlier to cover its latency). Out of scope for the model; the model
  just reports the latency correctly.
