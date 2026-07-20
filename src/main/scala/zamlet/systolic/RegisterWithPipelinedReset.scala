package zamlet.systolic

import chisel3._
import zamlet.utils.{ResetPipeline, ResetPipelineBudget}

class RegisterWithPipelinedReset[T <: Data](
    gen: T,
    resetBudget: ResetPipelineBudget = ResetPipelineBudget(1)) extends Module {
  val io = IO(new Bundle {
    val in = Input(gen.cloneType)
    val out = Output(gen.cloneType)
  })

  resetBudget.consume(1, "RegisterWithPipelinedReset")
  val localReset = ResetPipeline(clock, reset.asBool, 1)
  withReset(localReset) {
    io.out := RegNext(io.in, 0.U.asTypeOf(gen))
  }
}
