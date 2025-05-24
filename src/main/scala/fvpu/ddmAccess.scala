package fvpu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import chisel3.util.{MemoryWritePort}

import scala.io.Source

import fvpu.ModuleGenerator


class ddmAccess(params: FVPUParams) extends Module {
  // This module receives Send and Receive instructions and uses them to connect the
  // distributed data memory with the network.

  val instr = IO(Input(Valid(new SendReceiveInstr(params))))
  val fromNetwork = IO(Input(Valid(UInt(params.width.W))))
  val toNetwork = IO(Output(Valid(UInt(params.width.W))))
  val writeDDM = IO(Output(new MemoryWritePort(UInt(params.width.W), params.ddmAddrWidth, false)))
  val readDDM = IO(Flipped(new ValidReadPort(UInt(params.width.W), params.ddmAddrWidth)))
  val errorBadInstr = IO(Output(Bool()))
  val errorBadFromNetwork = IO(Output(Bool()))

  val readActive = RegInit(false.B)
  val readLength = RegInit(0.U(params.ddmAddrWidth.W))
  val readAddress = RegInit(0.U(params.ddmAddrWidth.W))

  val writeActive = RegInit(false.B)
  val writeLength = RegInit(0.U(params.ddmAddrWidth.W))
  val writeAddress = RegInit(0.U(params.ddmAddrWidth.W))

  toNetwork := readDDM.data

  // Default outputs
  writeDDM.enable := false.B
  writeDDM.address := DontCare
  writeDDM.data := DontCare
  readDDM.address.valid := false.B
  readDDM.address.bits := DontCare
  errorBadInstr := false.B
  errorBadFromNetwork := false.B

  // Handle Send/Receive instructions
  when (instr.valid) {
    when (instr.bits.mode === 0.U) { // Send instruction
      when (readActive) {
        errorBadInstr := true.B
      }.otherwise {
        readActive := true.B
        readLength := instr.bits.length
        readAddress := instr.bits.addr
      }
    }.otherwise { // Receive instruction (mode === 1.U)
      when (writeActive) {
        errorBadInstr := true.B
      }.otherwise {
        writeActive := true.B
        writeLength := instr.bits.length
        writeAddress := instr.bits.addr
      }
    }
  }

  // Handle read operations (Send)
  when (readActive) {
    readDDM.address.valid := true.B
    readDDM.address.bits := readAddress
    readLength := readLength - 1.U
    readAddress := readAddress + 1.U
    when (readLength === 1.U) {
      readActive := false.B
    }
  }

  // Handle write operations (Receive)
  when (fromNetwork.valid) {
    when (!writeActive) {
      errorBadFromNetwork := true.B
    }.otherwise {
      writeDDM.enable := true.B
      writeDDM.address := writeAddress
      writeDDM.data := fromNetwork.bits
      
      writeLength := writeLength - 1.U
      writeAddress := writeAddress + 1.U
      
      when (writeLength === 1.U) {
        writeActive := false.B
      }
    }
  }
}


object ddmAccessGenerator extends ModuleGenerator {

  override def makeModule(args: Seq[String]): Module = {
    // Parse arguments
    if (args.length < 1) {
      println("Usage: <command> <outputDir> ddmAccess <paramsFileName>")
      return null
    }
    val params = FVPUParams.fromFile(args(0));
    return new ddmAccess(params);
  }

}
