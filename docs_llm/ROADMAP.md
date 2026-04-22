# Roadmap

Top goal: working hardware — a P&R'd chip and an FPGA-emulated system that
runs interesting programs.

## Milestones

1. **Python model covers the full RVV spec.** Reference implementation for
   every vector instruction.

2. **Python model runs real, performant programs.** FFT is the first concrete
   target; later kernels expose further hardware/compiler gaps.

3. **Kamlet mesh in RTL, P&R at 100 MHz in Skywater 130.** Full RVV coverage
   is not required at this stage — enough to run interesting programs.

4. **Kamlet mesh simulating on an FPGA.**

5. **RTL lamlet implementation, integrated with Shuttle and the kamlet mesh.**

6. **Entire system running on an FPGA.** Again, full RVV coverage is not
   required at this stage.

## How plans map to milestones

Plans live in `plans/` and are indexed in `plan_status.md`. Most current plans
feed milestones 1–2 (ISA coverage + kernel performance). RTL/P&R and FPGA work
(3–6) is tracked more loosely for now — add plans as those phases heat up.
