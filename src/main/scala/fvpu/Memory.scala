package fvpu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import chisel3.util.UIntToOH
import chisel3.util.DecoupledIO

import scala.io.Source

import fvpu.ModuleGenerator


class ValidReadPort[T <: Data](t: T, addrWidth: Int) extends Bundle {
  // Using valid since latency is unknown.
  val address  = Input(Valid(UInt(addrWidth.W)));
  val data = Output(Valid(t));
  }

// The inputs ports going to a one-port memory
// Excludes the output data port for situations where we're going through
// logic that can't handle a bi-directional interface.
class ReadWriteInputPort(width: Int, addrWidth: Int) extends Bundle {
  val address = UInt(addrWidth.W);
  val data = UInt(width.W);
  val enable = Bool();
  val isWrite = Bool();
}

// Similar to ReadyValidIO but supports backpressure by passing tokens backwards.
// The sender receives tokens, and can send one cycle of data for each token
// received
// Pipelining this is simpler than ReadyValidIO but it requires a buffer at the 
// receiver of the same size as the latency to get full throughput.
class TokenValid[T <: Data](t: T) extends Bundle {
  val valid = Input(Bool())
  val bits = Input(t)
  val token = Output(Bool())
}

class Bus(width: Int) extends TokenValid(new HeaderTag(UInt(width.W))) {

  def toValid(): Valid[UInt] = {
    val v = Wire(Valid(UInt(width.W)))
    v.valid := valid
    v.bits := bits.bits
    v
  }

  def fromValid(v: Valid[UInt]): Unit = {
    valid := v.valid
    token := false.B
    bits.header := false.B
    bits.bits := v.bits
  }
}



class HeaderTag[T <: Data](t: T) extends Bundle {
  val header = Bool()
  val bits = t
}

class TokenValidToReadyValid[T <: Data](t: T, nTokens: Int) extends Module {
  val input = IO(new TokenValid(t))
  val output = IO(DecoupledIO(t))
  val errorOverflow = IO(Output(Bool()))
  val errorUnexpectedToken = IO(Output(Bool()))

  val rxTokens = RegInit(nTokens.U(log2Ceil(nTokens+1).W))

  errorOverflow := false.B
  errorUnexpectedToken := false.B
  when (input.valid) {
    when (!output.ready) {
      errorOverflow := true.B
    }
  }
  output.valid := input.valid
  output.bits := input.bits

  input.token := (rxTokens > 0.U)
  when (input.token && input.valid) {
  }.elsewhen (input.token) {
    rxTokens := rxTokens - 1.U
  }.elsewhen (input.valid) {
    rxTokens := rxTokens + 1.U
    when (rxTokens === nTokens.U) {
      errorUnexpectedToken := true.B
    }
  }
}

class ReadyValidToTokenValid[T <: Data](t: T, nTokens: Int) extends Module {
  val input = IO(Flipped(DecoupledIO(t)))
  val output = IO(Flipped(new TokenValid(t)))
  val errorUnexpectedToken = IO(Output(Bool()))

  val txTokens = RegInit(0.U(log2Ceil(nTokens+1).W))

  errorUnexpectedToken := false.B

  output.bits := input.bits
  output.valid := (txTokens > 0.U) && input.valid

  input.ready := (txTokens > 0.U)

  when (output.token && output.valid) {
  }.elsewhen (output.token) {
    txTokens := txTokens + 1.U
  }.elsewhen (output.valid) {
    txTokens := txTokens - 1.U
    when (txTokens === 0.U) {
      errorUnexpectedToken := true.B
    }
  }
}

class ReadyValid2Mux[T <: Data](t: T) extends Module {
  val inputA = IO(Flipped(DecoupledIO(t)))
  val inputB = IO(Flipped(DecoupledIO(t)))
  val output = IO(DecoupledIO(t))
  val sel = IO(Input(Bool()))
  val enable = IO(Input(Bool()))

  when (enable) {
    inputA.ready := sel && output.ready
    inputB.ready := (!sel) && output.ready
    output.valid := Mux(sel, inputA.valid, inputB.valid)
    output.bits := Mux(sel, inputA.bits, inputB.bits)
  }.otherwise {
    inputA.ready := false.B
    inputB.ready := false.B
    output.valid := false.B
    output.bits := DontCare
  }
}

class ReadyValidSplit[T <: Data](t: T) extends Module {
  val input = IO(Flipped(DecoupledIO(t)))
  val outputA = IO(DecoupledIO(t))
  val outputB = IO(DecoupledIO(t))
  val sel = IO(Input(Bool()))

  when (sel) {
    input <> outputA
    outputB.valid := false.B
    outputB.bits := DontCare
  }.otherwise {
    input <> outputB
    outputA.valid := false.B
    outputA.bits := DontCare
  }
}

object MuxSplitReadyValid {
  def apply[T <: Data](t: T, input: DecoupledIO[T], sel: Bool): (DecoupledIO[T], DecoupledIO[T]) = {
    val outputA = Wire(DecoupledIO(t))
    val outputB = Wire(DecoupledIO(t))
    when (sel) {
      outputA <> input
      outputB.valid := false.B
      outputB.bits := DontCare
    }.otherwise {
      outputB <> input
      outputA.valid := false.B
      outputA.bits := DontCare
    }
    (outputA, outputB)
  }
}

class ReadyValidMux[T <: Data](t: T, nInputs: Int) extends Module {
  val inputs = IO(Vec(nInputs, Flipped(DecoupledIO(t))))
  val output = IO(DecoupledIO(t))
  val sel = IO(Input(UInt(log2Ceil(nInputs).W)))
  val enable = IO(Input(Bool()))

  when (enable) {
    for (i <- 0 until nInputs) {
      inputs(i).ready := (sel === i.U) && output.ready
    }
    output.valid := inputs(sel).valid
    output.bits := inputs(sel).bits
  }.otherwise {
    for (i <- 0 until nInputs) {
      inputs(i).ready := false.B
    }
    output.valid := false.B
    output.bits := DontCare
  }
}


class ValidMux[T <: Data](gen: T, nInputs: Int) extends Module {
  // We take nInputs valid/bits signals.
  // If there is exactly 1 valid input then the output corresponds to that input.
  // Otherwise the output is not valid.
  val inputs = IO(Input(Vec(nInputs, Valid(gen))));
  val output = IO(Output(Valid(gen)));
  val error = IO(Output(Bool()));

  val nInputsA = (nInputs+1)/2;
  val nInputsB = nInputs - nInputsA;

  if (nInputs == 1) {
    output := inputs(0);
    error := false.B;
  } else {
    val validMuxA = Module(new ValidMux(gen, nInputsA));
    val validMuxB = Module(new ValidMux(gen, nInputsB));
    for (i <- 0 until nInputsA) {
      validMuxA.inputs(i) := inputs(i);
    }
    for (i <- 0 until nInputsB) {
      validMuxB.inputs(i) := inputs(i+nInputsA);
    }
    val aIntermed = validMuxA.output;
    val aError = validMuxA.error;
    val bIntermed = validMuxB.output;
    val bError = validMuxB.error;
    when (aIntermed.valid && bIntermed.valid) {
      output.valid := false.B;
      output.bits := DontCare;
      error := true.B;
    }.elsewhen (aIntermed.valid) {
      output.valid := true.B;
      output.bits := aIntermed.bits;
      error := aError || bError;
    }.elsewhen (bIntermed.valid) {
      output.valid := true.B;
      output.bits := bIntermed.bits;
      error := aError || bError;
    }.otherwise {
      output.valid := false.B;
      output.bits := DontCare;
      error := aError || bError;
    }
  }
}
