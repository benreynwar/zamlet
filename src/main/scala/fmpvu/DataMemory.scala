package fmpvu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import chisel3.util.UIntToOH
import chisel3.util.{MemoryWritePort, SRAM}

import scala.io.Source

import fmpvu.ModuleGenerator


class DataMemory(width: Int, depth: Int, nBanks: Int) extends Module {
  val nWritePorts = 2
  val nReadPorts = 2
  val totalAddrWidth = log2Ceil(depth) + log2Ceil(nBanks)

  val io = IO(new Bundle {
    val writes = Input(Vec(nWritePorts, new MemoryWritePort(UInt(width.W), totalAddrWidth, false)))
    val reads = Vec(nReadPorts, new ValidReadPort(UInt(width.W), totalAddrWidth))
    val errors = Output(Vec(nBanks, Bool()))
  })

  val writeBanks = Wire(Vec(nWritePorts, UInt(log2Ceil(nBanks).W)))
  for (i <- 0 until nWritePorts) {
    writeBanks(i) := io.writes(i).address(totalAddrWidth - 1, log2Ceil(depth))
  }
  val readValids = Wire(Vec(nReadPorts, Bool()))
  val readBanks = Wire(Vec(nReadPorts, UInt(log2Ceil(nBanks).W)))
  for (i <- 0 until nReadPorts) {
    readValids(i) := io.reads(i).address.valid
    readBanks(i) := io.reads(i).address.bits(totalAddrWidth - 1, log2Ceil(depth))
  }

  val bankClashes = Wire(Vec(nBanks, Bool()))
  val bankOutputData = Wire(Vec(nBanks, UInt(width.W)))

  for (bank_index <- 0 until nBanks) {
    val readWrites = Wire(Vec(
      nWritePorts + nReadPorts,
      Valid(new ReadWriteInputPort(width, log2Ceil(depth)))))
    for (i <- 0 until nReadPorts) {
      readWrites(i).valid := io.reads(i).address.valid && readBanks(i) === bank_index.U
      readWrites(i).bits.enable := io.reads(i).address.valid && readBanks(i) === bank_index.U
      readWrites(i).bits.isWrite := false.B
      readWrites(i).bits.address := io.reads(i).address.bits(log2Ceil(depth) - 1, 0)
      readWrites(i).bits.data := DontCare
    }
    for (i <- 0 until nWritePorts) {
      readWrites(nReadPorts + i).valid := io.writes(i).enable && writeBanks(i) === bank_index.U
      readWrites(nReadPorts + i).bits.enable := io.writes(i).enable && writeBanks(i) === bank_index.U
      readWrites(nReadPorts + i).bits.isWrite := true.B
      readWrites(nReadPorts + i).bits.address := io.writes(i).address(log2Ceil(depth) - 1, 0)
      readWrites(nReadPorts + i).bits.data := io.writes(i).data
    }
    val readwriteMux = Module(new ValidMux(new ReadWriteInputPort(width, depth), nReadPorts + nWritePorts))
    readwriteMux.io.inputs := readWrites
    bankClashes(bank_index) := readwriteMux.io.error

    val sramIO = SRAM(depth, UInt(width.W), 0, 0, 1)
    sramIO.readwritePorts(0).enable := readwriteMux.io.output.bits.enable && readwriteMux.io.output.valid
    sramIO.readwritePorts(0).isWrite := readwriteMux.io.output.bits.isWrite
    sramIO.readwritePorts(0).writeData := readwriteMux.io.output.bits.data
    sramIO.readwritePorts(0).address := readwriteMux.io.output.bits.address
    bankOutputData(bank_index) := sramIO.readwritePorts(0).readData
  }

  // Assuming that the latency for the memory is 1 cycle.
  val readOutputValids = RegNext(readValids)
  val readOutputBanks = RegNext(readBanks)
  for (i <- 0 until nReadPorts) {
    io.reads(i).data.valid := readOutputValids(i)
    io.reads(i).data.bits := bankOutputData(readOutputBanks(i))
  }
  
  // Register the bankClashes and output as error wires.
  io.errors := RegNext(bankClashes)

}

object DataMemoryGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 3) {
      println("Usage: <command> <outputDir> DataMemory <width> <depth> <nBanks>")
      null
    } else {
      val width = args(0).toInt
      val depth = args(1).toInt
      val nBanks = args(2).toInt
      new DataMemory(width, depth, nBanks)
    }
  }
}
