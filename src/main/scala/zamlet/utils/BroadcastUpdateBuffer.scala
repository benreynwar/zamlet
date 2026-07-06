package zamlet.utils

import chisel3._
import chisel3.util._

class BroadcastUpdateForwardBuffer[D <: Data, B <: Data](
  dataType: D,
  broadcastType: B,
  update: (D, B) => D,
  enable: Boolean = true,
) extends Module {
  val io = IO(new Bundle {
    val i = Flipped(Decoupled(dataType.cloneType))
    val o = Decoupled(dataType.cloneType)
    val broadcastIn = Flipped(Valid(broadcastType.cloneType))
    val broadcastOut = Valid(broadcastType.cloneType)
  })

  io.broadcastOut := RegEnable(io.broadcastIn, 0.U.asTypeOf(io.broadcastIn), true.B)

  def updateIfBroadcastValid(data: D): D = {
    val updated = Wire(dataType.cloneType)
    updated := data
    when (io.broadcastIn.valid) {
      updated := update(data, io.broadcastIn.bits)
    }
    updated
  }

  if (enable) {
    val storedNext = Wire(dataType.cloneType)
    val stored = RegEnable(storedNext, 0.U.asTypeOf(storedNext), true.B)
    val storedUpdated = updateIfBroadcastValid(stored)
    val storedValidNext = Wire(Bool())
    val storedValid = RegEnable(storedValidNext, false.B, true.B)

    // Forward state is a real pipeline register. The input and output data do
    // not observe this cycle's broadcast; only an entry recirculating in this
    // register is updated before it is stored for another cycle.
    storedNext := storedUpdated
    storedValidNext := storedValid

    io.i.ready := !storedValid || io.o.ready
    io.o.valid := storedValid
    io.o.bits := stored

    when (io.i.fire) {
      storedNext := io.i.bits
      storedValidNext := true.B
    } .elsewhen (io.o.ready) {
      storedValidNext := false.B
    }
  } else {
    io.o <> io.i
    io.broadcastOut := io.broadcastIn
  }
}

class BroadcastUpdateBackwardBuffer[D <: Data, B <: Data](
  dataType: D,
  broadcastType: B,
  update: (D, B) => D,
  enable: Boolean = true,
) extends Module {
  val io = IO(new Bundle {
    val i = Flipped(Decoupled(dataType.cloneType))
    val o = Decoupled(dataType.cloneType)
    val broadcastIn = Flipped(Valid(broadcastType.cloneType))
    val broadcastOut = Valid(broadcastType.cloneType)
    val fromState = Output(Bool())
  })

  io.broadcastOut := io.broadcastIn

  def updateIfBroadcastValid(data: D): D = {
    val updated = Wire(dataType.cloneType)
    updated := data
    when (io.broadcastIn.valid) {
      updated := update(data, io.broadcastIn.bits)
    }
    updated
  }

  if (enable) {
    val storedNext = Wire(dataType.cloneType)
    val stored = RegEnable(storedNext, 0.U.asTypeOf(storedNext), true.B)
    val storedUpdated = updateIfBroadcastValid(stored)
    val storedValidNext = Wire(Bool())
    val storedValid = RegEnable(storedValidNext, false.B, true.B)

    // This is a skid register. Passthrough input is not changed. A resident
    // skid entry is updated by the broadcast that is passing this boundary.
    storedNext := storedUpdated
    storedValidNext := storedValid

    io.i.ready := !storedValid
    io.o.valid := io.i.valid || storedValid
    io.o.bits := Mux(storedValid, storedUpdated, io.i.bits)
    io.fromState := storedValid

    when (io.o.ready) {
      storedValidNext := false.B
    }
    when (!io.o.ready && io.i.ready) {
      storedValidNext := io.i.valid
    }
    when (io.i.ready) {
      storedNext := io.i.bits
    }
  } else {
    io.o <> io.i
    io.broadcastOut := io.broadcastIn
    io.fromState := false.B
  }
}

class BroadcastUpdateBuffer[D <: Data, B <: Data](
  dataType: D,
  broadcastType: B,
  update: (D, B) => D,
  enableForward: Boolean = true,
  enableBackward: Boolean = true,
) extends Module {
  val io = IO(new Bundle {
    val i = Flipped(Decoupled(dataType.cloneType))
    val o = Decoupled(dataType.cloneType)
    val broadcastIn = Flipped(Valid(broadcastType.cloneType))
    val broadcastOut = Valid(broadcastType.cloneType)
    val fromState = Output(Bool())
    val hidden = Output(Valid(dataType.cloneType))
  })

  val backward = Module(new BroadcastUpdateBackwardBuffer(
    dataType,
    broadcastType,
    update,
    enableBackward))
  backward.io.i <> io.i
  backward.io.broadcastIn := io.broadcastIn

  val forward = Module(new BroadcastUpdateForwardBuffer(
    dataType,
    broadcastType,
    update,
    enableForward))
  forward.io.i <> backward.io.o
  forward.io.broadcastIn := backward.io.broadcastOut
  io.o <> forward.io.o
  io.broadcastOut := forward.io.broadcastOut

  if (enableForward) {
    io.fromState := io.o.valid
  } else {
    io.fromState := backward.io.fromState
  }

  if (enableForward && enableBackward) {
    io.hidden.valid := backward.io.fromState && io.o.valid
    io.hidden.bits := backward.io.o.bits
  } else {
    io.hidden.valid := false.B
    io.hidden.bits := DontCare
  }
}
