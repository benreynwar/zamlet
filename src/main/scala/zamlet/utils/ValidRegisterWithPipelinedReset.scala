package zamlet.utils

import chisel3._
import chisel3.util.Valid

class ValidRegisterWithPipelinedReset[T <: Data](
    gen: T,
    resetBudget: ResetPipelineBudget = ResetPipelineBudget(1)) extends Module {
  val io = IO(new Bundle {
    val in = Input(Valid(gen.cloneType))
    val out = Output(Valid(gen.cloneType))
  })

  require(
    resetBudget.remaining == 1,
    s"ValidRegisterWithPipelinedReset requires exactly one reset pipeline stage, " +
      s"but ${resetBudget.remaining} remain")
  val localReset = ResetPipeline(clock, reset.asBool, 1)
  io.out.bits := RegNext(io.in.bits)
  withReset(localReset) {
    io.out.valid := RegNext(io.in.valid, false.B)
  }
}
