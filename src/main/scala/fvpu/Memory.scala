package fvpu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import chisel3.util.UIntToOH

import scala.io.Source

import fvpu.ModuleGenerator


class ValidReadPort[T <: Data](gen: T, addrWidth: Int) extends Bundle {
  // Using valid since latency is unknown.
  val address  = Input(Valid(UInt(addrWidth.W)));
  val data = Output(Valid(gen));
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
