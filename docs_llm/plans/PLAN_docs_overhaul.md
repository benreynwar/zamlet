# PLAN: docs overhaul

## Division of labor

Ben writes the prose. Claude reviews drafts and helps shape outlines in
conversation. See CLAUDE.md and the `wrap-up` skill for working-pattern detail.

## Audience and goals

Audience is an expert in vector / GPU / accelerator microarchitecture. Three
things a reader should be able to do after reading the docs:

1. Form a working mental model of the microarchitecture.
2. Understand how RVV is implemented on top of it.
3. See what is novel and evaluate the approach — including its weaknesses.

## Headline framing

The doc set is organized around one architectural concept: **the stripe (total
lanes × word size) is the unit of locality.** Distributed cache placement, VRF
slicing, and physical byte layout are all aligned to stripe granularity. A
stripe-aligned, EW-matched access is fully local; anything else triggers a
mesh-wide permutation. One performance cliff, not two tiers.

- **Novelty:** mesh + distributed VRF + stripe-aligned layout means local access
  scales linearly with lane count.
- **Weakness:** off-regime access (stripe-misaligned or EW-mismatched) scales
  with the mesh — exactly what the mesh isn't built for.

EW is one *property* of a stripe (per-stripe metadata), not the headline
concept.

## Terminology

- **stripe** in the docs (codebase still uses `vline`; transition gradually as
  code is touched, no global rename).
- **kinstruction** = kamlet-level instruction. No separate jinstruction tier.
- **waiting item** (codebase: `lamlet_waiting_item.py`), not "pending item".

## Nav and priorities

```
- Home
- Setup
- Architecture
  - Hierarchy overview                          [P0, drafted]
  - Instruction flow                            [P0, drafted]
  - Stripe as the unit of locality              [P0, drafted]
  - Element-width-aware physical layout         [P0, drafted]
  - Register file & VRF distribution            [P1]
  - Distributed cache                           [P1, split from memory.md]
  - Address mapping (alpha/beta/gamma)          [P1, what's left of memory.md]
  - Network                                     [P0]
  - Synchronization                             [P1]
  - Memory model                                [P0, drafted, in cleanup]
- RVV implementation
  - State mapping (vl, vstart, vtype, masks)    [P0]
  - Arithmetic & lane-local ops                 [P0]
  - Loads/stores & indexed access               [P1]
  - Reductions                                  [P0, worked example]
  - Permutations (vrgather, vslide)             [P0, the hard case]
  - Masking, tail, vstart                       [P1]
  - Conformance subset                          [P1, table]
- Worked examples
  - Gather                                      [existing]
  - Reduction                                   [P0]
  - FFT inner loop                              [P2, after PLAN_fft_kernel]
- Novelty & related work                        [P0]
- Known weaknesses & open questions             [P0]
- Modelling
  - Python model                                [P1, flesh out stub]
- Tools
  - LLM usage                                   [existing]
```

## Sequencing

Rough order — P0 first, P1/P2 as time allows:

1. Hierarchy overview — unblocks everything.
2. Instruction flow.
3. Stripe (the headline page).
4. EW-aware physical layout.
5. Memory model.
6. Network.
7. RVV state mapping (anchors the RVV pages).
8. Reductions worked example.
9. Permutations.
10. Novelty & related work.
11. Known weaknesses.
12. P1 pages in any order.
13. P2 (FFT) once `PLAN_fft_kernel.md` is far enough along.

## Status

- `hierarchy.md` — drafted, reviewed.
- `stripe.md` — drafted, first pass stable.
- `instruction_flow.md` — drafted, multiple review passes; close to done pending
  forward-link targets.
- `element_width.md` — drafted, reviewed.
- `memory_model.md` — drafted, in cleanup pending small fixes.
- `vline.md` — superseded by `stripe.md`; decide on archival.
- `memory.md` — to be split into Distributed cache + Address mapping.
- All other pages — not started.

Data-placeholder convention: use `> **TODO(numbers):** ...` so gaps grep cleanly
once the python model is instrumented (separate follow-up, not part of this
plan).
