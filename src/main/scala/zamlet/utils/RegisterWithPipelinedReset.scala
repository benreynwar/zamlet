package zamlet.utils

import chisel3._

class RegisterWithPipelinedReset[T <: Data](
    gen: T,
    resetBudget: ResetPipelineBudget = ResetPipelineBudget(1)) extends Module {
  val io = IO(new Bundle {
    val in = Input(gen.cloneType)
    val out = Output(gen.cloneType)
  })

  require(
    resetBudget.remaining == 1,
    s"RegisterWithPipelinedReset requires exactly one reset pipeline stage, " +
      s"but ${resetBudget.remaining} remain")
  val localReset = ResetPipeline(clock, reset.asBool, 1)
  withReset(localReset) {
    io.out := RegNext(io.in, 0.U.asTypeOf(gen))
  }
}
