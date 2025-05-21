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


class WritePort(width: Int, depth: Int) extends Bundle {
  val enable =  Bool();
  val addr  = UInt(log2Ceil(depth).W);
  val data = UInt(width.W);
  }

class ReadPort(width: Int, depth: Int) extends Bundle {
  val enable =  Input(Bool());
  val addr  = Input(UInt(log2Ceil(depth).W));
  val data = Output(UInt(width.W));
  }

class WriteMux(width: Int, nWritePorts: Int) extends Module {
  // We take nWritePorts valid/bits signals.
  // If there is exactly 1 valid input then the output corresponds to that input.
  // Otherwise the output is not valid.
  val iWrites = IO(Input(Vec(nWritePorts, Valid(UInt(width.W)))));
  val oWrite = IO(Output(Valid(UInt(width.W))));
  val error = IO(Output(Bool()));

  val nWritePortsA = (nWritePorts+1)/2;
  val nWritePortsB = nWritePorts - nWritePortsA;

  if (nWritePorts == 1) {
    oWrite := iWrites(0);
    error := false.B;
  } else {
    val writeMuxA = Module(new WriteMux(width, nWritePortsA));
    for (i <- 0 until nWritePortsA) {
      writeMuxA.iWrites(i) := iWrites(i);
    }
    val aWrite = writeMuxA.oWrite;
    val aError = writeMuxA.error;
    val writeMuxB = Module(new WriteMux(width, nWritePortsB));
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

class RegisterFile(width: Int, depth: Int, nReadPorts: Int, nWritePorts: Int) extends Module {

  val writes = IO(Input(Vec(nWritePorts, new WritePort(width, depth))));
  val reads = IO(Vec(nReadPorts, new ReadPort(width, depth)));

  val contents = Reg(Vec(depth, UInt(width.W)));

  // For each location in memory this should contain how many write ports are trying to write to that location.
  val oneHots = Wire(Vec(nWritePorts, UInt(depth.W))); 
  for (port_index <- 0 until nWritePorts) {
    oneHots(port_index) := UIntToOH(writes(port_index).addr);
  }
  val writeClashes = Wire(Vec(depth, Bool()));
  for (addr <- 0 until depth) {
    val validWrites = Wire(Vec(nWritePorts, Valid(UInt(width.W))));
    for (port_index <- 0 until nWritePorts) {
      validWrites(port_index).valid := oneHots(port_index)(addr) && writes(port_index).enable;
      validWrites(port_index).bits := writes(port_index).data;
    }
    val finalWrite = Wire(Valid(UInt(width.W)));
    val writeMux = Module(new WriteMux(width, nWritePorts));
    writeMux.iWrites := validWrites;
    finalWrite := writeMux.oWrite;
    writeClashes(addr) := writeMux.error;
    when(finalWrite.valid) {
      contents(addr) := finalWrite.bits
    }
  }
  val writeClash = writeClashes.exists(x => x);

  for (port_index <- 0 until nReadPorts) {
    reads(port_index).data := contents(reads(port_index).addr);
  }

}


object RegisterFileGenerator extends ModuleGenerator {

  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 4) {
      println("Usage: <command> <outputDir> RegisterFile <width> <depth> <nReadPorts> <nWritePorts>");
      return null;
    }
    val width = args(0).toInt;
    val depth = args(1).toInt;
    val nReadPorts = args(2).toInt;
    val nWritePorts = args(3).toInt;
    return new RegisterFile(width, depth, nReadPorts, nWritePorts);
  }

}
