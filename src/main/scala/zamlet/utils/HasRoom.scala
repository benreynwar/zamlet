package zamlet.utils

import chisel3._
import chisel3.util._

class HasRoom[+T <: Data](t: T, inputLatency: Int = 0) extends Bundle {
  // constant
  // Indicates how many cycles of data the downstream needs to be able
  // accept after it lowers hasRoom.
  val latency = inputLatency

  // signals
  val valid = Output(Bool())
  val hasRoom = Input(Bool())
  val bits = Output(t)
}

object HasRoom {
  def apply[T <: Data](t: T, inputLatency: Int = 0): HasRoom[T] = new HasRoom(t, inputLatency)

  def fromDecoupled[T <: Data](s: DecoupledIO[T]): HasRoom[T] = {
    val r = Wire(HasRoom(s.bits.cloneType, 0))
    r.valid := s.valid && r.hasRoom
    r.bits := s.bits
    s.ready := r.hasRoom
    r
  }

}

// FIXME: When we connect two HasRoom signals we need to confirm that the latency is the same.

class HasRoomForwardBuffer[T <: Data](t: T, inputLatency: Int, enable: Boolean = true) extends Module {
  val outputLatency = if (enable) inputLatency + 1 else inputLatency
  val io = IO(new Bundle {
    val i = Flipped(HasRoom(t, inputLatency))
    val o = HasRoom(t, outputLatency)
  })
  io.i.hasRoom := io.o.hasRoom
  if (enable) {
    io.o.valid := RegNext(io.i.valid, false.B)
    io.o.bits := RegNext(io.i.bits)
  } else {
    io.o.valid := io.i.valid
    io.o.bits := io.i.bits
  }
}

object HasRoomForwardBuffer {
  def apply[T <: Data](input: HasRoom[T], enable: Boolean = true): HasRoom[T] = {
    val buffer = Module(new HasRoomForwardBuffer(input.bits.cloneType, input.latency, enable))
    buffer.io.i <> input
    buffer.io.o
  }
}

class HasRoomBackwardBuffer[T <: Data](t: T, inputLatency: Int, enable: Boolean = true) extends Module {
  val outputLatency = if (enable) inputLatency + 1 else inputLatency
  val io = IO(new Bundle {
    val i = Flipped(HasRoom(t, inputLatency))
    val o = HasRoom(t, outputLatency)
  })
  io.o.valid := io.i.valid
  io.o.bits := io.i.bits
  if (enable) {
    io.i.hasRoom := RegNext(io.o.hasRoom, true.B)
  } else {
    io.i.hasRoom := io.o.hasRoom
  }
}

object HasRoomBackwardBuffer {
  def apply[T <: Data](input: HasRoom[T], enable: Boolean = true): HasRoom[T] = {
    val buffer = Module(new HasRoomBackwardBuffer(input.bits.cloneType, input.latency, enable))
    buffer.io.i <> input
    buffer.io.o
  }
}
