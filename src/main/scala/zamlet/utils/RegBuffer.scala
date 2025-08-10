package zamlet.utils

import chisel3._
import chisel3.util._

class RegBuffer[T <: Data](t: T, enable: Boolean = true) extends Module {
  val io = IO(new Bundle {
    val i = Input(t)
    val o = Output(t)
  })

  if (enable) {
    val buffer = RegNext(io.i)
    io.o := buffer
  } else {
    // Bypass mode - direct connection
    io.o := io.i
  }
}

object RegBuffer {
  def apply[T <: Data](input: T, enable: Boolean = true): T = {
    val buffer = Module(new RegBuffer(chiselTypeOf(input), enable))
    buffer.io.i := input
    buffer.io.o
  }
}