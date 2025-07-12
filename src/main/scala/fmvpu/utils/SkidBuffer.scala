package fmvpu.utils

import chisel3._
import chisel3.util._
import fmvpu.ModuleGenerator

class SkidBuffer[T <: Data](t: T) extends Module {
  val io = IO(new Bundle {
    val i = Flipped(DecoupledIO(t))
    val o = DecoupledIO(t)
  })

  val buffer = Reg(t)
  val bufferValid = RegInit(false.B)

  io.i.ready := !bufferValid

  when (io.o.ready) {
    // We empty the buffer.
    // This will get overridden in the next section if we fill it up.
    bufferValid := false.B
  }
  when (io.i.valid && io.i.ready) {
    // We know the buffer is empty since i_ready is 1
    when (!io.o.ready) {
      // We have to go into the buffer
      buffer := io.i.bits
      bufferValid := true.B
    }
  }

  io.o.valid := io.i.valid || bufferValid
  io.o.bits := Mux(bufferValid, buffer, io.i.bits)
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
