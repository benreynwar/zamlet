package zamlet.utils

import chisel3._
import chisel3.util._

class ValidBuffer[T <: Data](t: T, enable: Boolean = true) extends Module {
  val io = IO(new Bundle {
    val i = Input(Valid(t))
    val o = Output(Valid(t))
  })

  if (enable) {
    val buffer = Reg(t)
    val bufferValid = RegNext(io.i.valid, false.B)
    val bufferData = RegNext(io.i.bits)

    io.o.valid := bufferValid
    io.o.bits := bufferData
  } else {
    // Bypass mode - direct connection
    io.o <> io.i
  }
}

object ValidBuffer {
  def apply[T <: Data](input: Valid[T], enable: Boolean = true): Valid[T] = {
    val buffer = Module(new ValidBuffer(chiselTypeOf(input.bits), enable))
    buffer.io.i <> input
    buffer.io.o
  }
}
