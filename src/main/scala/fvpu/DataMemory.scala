package fvpu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import chisel3.util.UIntToOH
import chisel3.util.{MemoryWritePort, SRAM}

import scala.io.Source

import fvpu.ModuleGenerator


class DataMemory(width: Int, depth: Int, nBanks: Int) extends Module {

  val nWritePorts = 2;
  val nReadPorts = 2;
  val totalAddrWidth = log2Ceil(depth) + log2Ceil(nBanks);

  val writes = IO(Input(Vec(nWritePorts, new MemoryWritePort(UInt(width.W), totalAddrWidth, false))));
  val reads = IO(Vec(nReadPorts, new ValidReadPort(UInt(width.W), totalAddrWidth)));
  val errors = IO(Vec(nBanks, Bool()));

  val writeBanks = Wire(Vec(nWritePorts, UInt(log2Ceil(nBanks).W)));
  for (i <- 0 until nWritePorts) {
    writeBanks(i) := writes(i).address(totalAddrWidth-1, log2Ceil(depth));
  }
  val readValids = Wire(Vec(nReadPorts, Bool()));
  val readBanks = Wire(Vec(nReadPorts, UInt(log2Ceil(nBanks).W)));
  for (i <- 0 until nReadPorts) {
    readValids(i) := reads(i).address.valid;
    readBanks(i) := reads(i).address.bits(totalAddrWidth-1, log2Ceil(depth));
  }

  var bankClashes = Wire(Vec(nBanks, Bool()));
  var bankOutputData = Wire(Vec(nBanks, UInt(width.W)));

  for (bank_index <- 0 until nBanks) {
    val readWrites = Wire(Vec(
      nWritePorts+nReadPorts,
      Valid(new ReadWriteInputPort(width, log2Ceil(depth)))));
    for (i <- 0 until nReadPorts) {
      readWrites(i).valid := reads(i).address.valid && readBanks(i) === bank_index.U;
      readWrites(i).bits.enable := reads(i).address.valid && readBanks(i) === bank_index.U;
      readWrites(i).bits.isWrite := false.B;
      readWrites(i).bits.address := reads(i).address.bits(log2Ceil(depth)-1, 0);
      readWrites(i).bits.data := DontCare
    }
    for (i <- 0 until nWritePorts) {
      readWrites(nReadPorts+i).valid := writes(i).enable && writeBanks(i) === bank_index.U;
      readWrites(nReadPorts+i).bits.enable := writes(i).enable && writeBanks(i) === bank_index.U;
      readWrites(nReadPorts+i).bits.isWrite := true.B;
      readWrites(nReadPorts+i).bits.address := writes(i).address(log2Ceil(depth)-1, 0);
      readWrites(nReadPorts+i).bits.data := writes(i).data;
    }
    val readwriteMux = Module(new ValidMux(new ReadWriteInputPort(width, depth), nReadPorts + nWritePorts));
    readwriteMux.inputs := readWrites;
    bankClashes(bank_index) := readwriteMux.error;

    val sramIO = SRAM(depth, UInt(width.W), 0, 0, 1);
    sramIO.readwritePorts(0).enable := readwriteMux.output.bits.enable && readwriteMux.output.valid;
    sramIO.readwritePorts(0).isWrite := readwriteMux.output.bits.isWrite;
    sramIO.readwritePorts(0).writeData := readwriteMux.output.bits.data;
    sramIO.readwritePorts(0).address := readwriteMux.output.bits.address;
    bankOutputData(bank_index) := sramIO.readwritePorts(0).readData;
  }

  // Assuming that the latency for the memory is 1 cycle.
  val readOutputValids = RegNext(readValids);
  val readOutputBanks = RegNext(readBanks);
  for (i <- 0 until nReadPorts) {
    reads(i).data.valid := readOutputValids(i);
    reads(i).data.bits := bankOutputData(readOutputBanks(i));
  }
  
  // Register the bankClashes and output as error wires.
  errors := RegNext(bankClashes);

}

object DataMemoryGenerator extends ModuleGenerator {

  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 3) {
      println("Usage: <command> <outputDir> DataMemory <width> <depth> <nBanks>");
      return null;
    }
    val width = args(0).toInt;
    val depth = args(1).toInt;
    val nBanks = args(2).toInt;
    return new DataMemory(width, depth, nBanks);
  }

}
