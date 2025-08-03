package fmvpu.utils

import chisel3._
import chisel3.util._
import fmvpu.ModuleGenerator

class DecoupledBuffer[T <: Data](t: T, enable: Boolean = true) extends Module {
  val io = IO(new Bundle {
    val i = Flipped(DecoupledIO(t))
    val o = DecoupledIO(t)
  })

  if (enable) {
    val buffer = Reg(t)
    val bufferValid = RegInit(false.B)

    when (io.i.valid && io.i.ready) {
      buffer := io.i.bits
      bufferValid := true.B
    } .elsewhen (io.o.ready) {
      bufferValid := false.B
    }

    io.i.ready := !bufferValid || io.o.ready
    io.o.valid := bufferValid
    io.o.bits := buffer
  } else {
    // Bypass mode - direct connection
    io.o <> io.i
  }
}

object DecoupledBufferGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> DecoupledBuffer <width>")
      null
    } else {
      val width = args(0).toInt
      new DecoupledBuffer(UInt(width.W))
    }
  }
}
