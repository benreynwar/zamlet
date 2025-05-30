package fmpvu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import chisel3.util.UIntToOH
import chisel3.util.{MemoryWritePort, MemoryReadPort}

import scala.io.Source

import fmpvu.ModuleGenerator


class RegisterFile(width: Int, depth: Int, nReadPorts: Int, nWritePorts: Int) extends Module {
  val io = IO(new Bundle {
    val writes = Input(Vec(nWritePorts, new MemoryWritePort(UInt(width.W), log2Ceil(depth), false)))
    val reads = Vec(nReadPorts, new MemoryReadPort(UInt(width.W), log2Ceil(depth)))
  })

  val contents = Reg(Vec(depth, UInt(width.W)))

  // For each location in memory this should contain how many write ports are trying to write to that location.
  val oneHots = Wire(Vec(nWritePorts, UInt(depth.W)))
  for (port_index <- 0 until nWritePorts) {
    oneHots(port_index) := UIntToOH(io.writes(port_index).address)
  }
  val writeClashes = Wire(Vec(depth, Bool()))
  for (addr <- 0 until depth) {
    val validWrites = Wire(Vec(nWritePorts, Valid(UInt(width.W))))
    for (port_index <- 0 until nWritePorts) {
      validWrites(port_index).valid := oneHots(port_index)(addr) && io.writes(port_index).enable
      validWrites(port_index).bits := io.writes(port_index).data
    }
    val finalWrite = Wire(Valid(UInt(width.W)))
    val mux = Module(new ValidMux(UInt(width.W), nWritePorts))
    mux.io.inputs := validWrites
    finalWrite := mux.io.output
    writeClashes(addr) := mux.io.error
    when(finalWrite.valid) {
      contents(addr) := finalWrite.bits
    }
  }
  val writeClash = writeClashes.exists(x => x)

  for (port_index <- 0 until nReadPorts) {
    io.reads(port_index).data := contents(io.reads(port_index).address)
  }

}


object RegisterFileGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 4) {
      println("Usage: <command> <outputDir> RegisterFile <width> <depth> <nReadPorts> <nWritePorts>")
      null
    } else {
      val width = args(0).toInt
      val depth = args(1).toInt
      val nReadPorts = args(2).toInt
      val nWritePorts = args(3).toInt
      new RegisterFile(width, depth, nReadPorts, nWritePorts)
    }
  }
}
