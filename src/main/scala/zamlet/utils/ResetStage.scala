package zamlet.utils

import chisel3._
import chisel3.util._

class ResetSynchronizer extends RawModule {
  val clock = IO(Input(Clock()))
  val resetIn = IO(Input(Reset()))
  val resetOut = IO(Output(Reset()))

  // Async assert, sync deassert. Use this only at a reset-domain boundary.
  // Module-local reset timing/fanout buffering should use ResetPipeline.
  withClockAndReset(clock, resetIn) {
    val ff1 = RegNext(resetIn)
    val ff2 = RegNext(ff1)
    resetOut := ff2
  }
}

object ResetSynchronizer {
  def apply(clock: Clock, resetIn: Reset): Reset = {
    val resetSynchronizer = Module(new ResetSynchronizer)
    resetSynchronizer.clock := clock
    resetSynchronizer.resetIn := resetIn
    resetSynchronizer.resetOut
  }
}

case class ResetPipelineBudget(remaining: Int) {
  def consume(stages: Int, owner: String): ResetPipelineBudget = {
    require(
      remaining >= stages,
      s"$owner requires $stages reset pipeline stages, but only $remaining remain")
    copy(remaining = remaining - stages)
  }
}

case class ResetPipelineOutput(
  childReset: Reset,
  localReset: Reset,
  childBudget: ResetPipelineBudget
)

class ResetPipeline(stages: Int) extends RawModule {
  require(stages > 0, "ResetPipeline needs at least one stage")

  val clock = IO(Input(Clock()))
  val resetIn = IO(Input(Bool()))
  val resetOut = IO(Output(Reset()))

  withClock(clock) {
    // This is a data pipeline for reset, not state reset by reset. The caller
    // must hold resetIn high long enough to fill the requested pipeline depth.
    val pipe = Reg(Vec(stages, Bool()))
    pipe(0) := resetIn
    for (stage <- 1 until stages) {
      pipe(stage) := pipe(stage - 1)
    }
    resetOut := pipe(stages - 1)
  }
}

object ResetPipeline {
  def apply(
      clock: Clock,
      resetIn: Bool,
      stages: Int,
      budget: ResetPipelineBudget,
      owner: String,
  ): ResetPipelineOutput = {
    val childBudget = budget.consume(stages, owner)
    ResetPipelineOutput(
      childReset = apply(clock, resetIn, stages),
      localReset = apply(clock, resetIn, budget.remaining),
      childBudget = childBudget)
  }

  def apply(clock: Clock, resetIn: Bool, stages: Int): Reset = {
    val resetPipeline = Module(new ResetPipeline(stages))
    resetPipeline.clock := clock
    resetPipeline.resetIn := resetIn
    resetPipeline.resetOut
  }
}
