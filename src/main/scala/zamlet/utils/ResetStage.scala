package zamlet.utils

import chisel3._
import chisel3.util._

class ResetStage extends RawModule {
  val clock = IO(Input(Clock()))
  val resetIn = IO(Input(Reset()))
  val resetOut = IO(Output(Reset()))

  withClockAndReset(clock, resetIn) {
    // This should work ok for sync and async, but it
    // is one more stage than we'd need for sync.
    // Not sure how to get around this.
    val ff1 = RegNext(resetIn)
    val ff2 = RegNext(ff1)
    resetOut := ff2
  }
}

object ResetStage {
  def apply(clock: Clock, resetIn: Reset): Reset = {
    val resetStage = Module(new ResetStage)
    resetStage.clock := clock
    resetStage.resetIn := resetIn
    resetStage.resetOut
  }
}
