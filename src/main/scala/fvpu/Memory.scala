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


class ValidReadPort(width: Int, depth: Int) extends Bundle {
  // Using valid since latency is unknown.
  val addr  = Input(Valid(UInt(log2Ceil(depth).W)));
  val data = Output(Valid(UInt(width.W)));
  }


class WriteMux[T <: Data](gen: T, nWritePorts: Int) extends Module {
  // We take nWritePorts valid/bits signals.
  // If there is exactly 1 valid input then the output corresponds to that input.
  // Otherwise the output is not valid.
  val iWrites = IO(Input(Vec(nWritePorts, Valid(gen))));
  val oWrite = IO(Output(Valid(gen)));
  val error = IO(Output(Bool()));

  val nWritePortsA = (nWritePorts+1)/2;
  val nWritePortsB = nWritePorts - nWritePortsA;

  if (nWritePorts == 1) {
    oWrite := iWrites(0);
    error := false.B;
  } else {
    val writeMuxA = Module(new WriteMux(gen, nWritePortsA));
    for (i <- 0 until nWritePortsA) {
      writeMuxA.iWrites(i) := iWrites(i);
    }
    val aWrite = writeMuxA.oWrite;
    val aError = writeMuxA.error;
    val writeMuxB = Module(new WriteMux(gen, nWritePortsB));
    for (i <- 0 until nWritePortsB) {
      writeMuxB.iWrites(i) := iWrites(i+nWritePortsA);
    }
    val bWrite = writeMuxB.oWrite;
    val bError = writeMuxB.error;
    when (aWrite.valid && bWrite.valid) {
      oWrite.valid := false.B;
      oWrite.bits := DontCare;
      error := true.B;
    }.elsewhen (aWrite.valid) {
      oWrite.valid := true.B;
      oWrite.bits := aWrite.bits;
      error := aError || bError;
    }.elsewhen (bWrite.valid) {
      oWrite.valid := true.B;
      oWrite.bits := bWrite.bits;
      error := aError || bError;
    }.otherwise {
      oWrite.valid := false.B;
      oWrite.bits := DontCare;
      error := aError || bError;
    }
  }
}
