package fmvpu.utils

import chisel3._
import chisel3.util._
import fmvpu.ModuleGenerator

class SkidBuffer[T <: Data](t: T, enable: Boolean = true) extends Module {
  val io = IO(new Bundle {
    val i = Flipped(DecoupledIO(t))
    val o = DecoupledIO(t)
  })

  if (enable) {
    val buffer = Reg(t)
    val bufferValid = RegInit(false.B)

    io.i.ready := !bufferValid

    when (io.o.ready) {
      // We empty the buffer.
      // This will get overridden in the next section if we fill it up.
      bufferValid := false.B
    }
    when (!io.o.ready && io.i.ready) {
      bufferValid := io.i.valid
    }
    // Only depend on i_ready.  We flip more, but the enable signal doesn't depend on o_ready.
    when (io.i.ready) {
      buffer := io.i.bits
    }

    io.o.valid := io.i.valid || bufferValid
    io.o.bits := Mux(bufferValid, buffer, io.i.bits)
  } else {
    // Bypass mode - direct connection
    io.o <> io.i
  }
}

object SkidBufferGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> SkidBuffer <width>")
      null
    } else {
      val width = args(0).toInt
      new SkidBuffer(UInt(width.W))
    }
  }
}
