package fmpvu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import chisel3.util.{MemoryWritePort}

import scala.io.Source

import fmpvu.ModuleGenerator


class ddmAccess(params: FMPVUParams) extends Module {
  // This module receives Send and Receive instructions and uses them to connect the
  // distributed data memory with the network.

  val io = IO(new Bundle {
    val instr = Input(Valid(new SendReceiveInstr(params)))
    val fromNetwork = Input(Valid(new HeaderTag(UInt(params.width.W))))
    val toNetwork = Output(Valid(UInt(params.width.W)))
    val writeDDM = Output(new MemoryWritePort(UInt(params.width.W), params.ddmAddrWidth, false))
    val readDDM = Flipped(new ValidReadPort(UInt(params.width.W), params.ddmAddrWidth))
    val errorBadInstr = Output(Bool())
    val errorBadFromNetwork = Output(Bool())
  })

  val readActive = RegInit(false.B)
  val readLength = RegInit(0.U(params.ddmAddrWidth.W))
  val readAddress = RegInit(0.U(params.ddmAddrWidth.W))
  val readStartOffset = RegInit(0.U(params.ddmAddrWidth.W))
  val readStride = RegInit(0.U(params.ddmAddrWidth.W))
  val readWordCount = RegInit(0.U(params.ddmAddrWidth.W))

  val writeActive = RegInit(false.B)
  val writeLength = RegInit(0.U(params.ddmAddrWidth.W))
  val writeAddress = RegInit(0.U(params.ddmAddrWidth.W))
  val writeStartOffset = RegInit(0.U(params.ddmAddrWidth.W))
  val writeStride = RegInit(0.U(params.ddmAddrWidth.W))
  val writeWordCount = RegInit(0.U(params.ddmAddrWidth.W))

  io.toNetwork := io.readDDM.data

  // Default outputs
  io.writeDDM.enable := false.B
  io.writeDDM.address := DontCare
  io.writeDDM.data := DontCare
  io.readDDM.address.valid := false.B
  io.readDDM.address.bits := DontCare
  io.errorBadInstr := false.B
  io.errorBadFromNetwork := false.B

  // Handle Send/Receive instructions
  when (io.instr.valid) {
    when (io.instr.bits.mode === 0.U) { // Send instruction
      when (readActive) {
        io.errorBadInstr := true.B
      }.otherwise {
        readActive := true.B
        readLength := io.instr.bits.length
        readAddress := io.instr.bits.addr
        readStartOffset := io.instr.bits.startOffset
        readStride := io.instr.bits.stride
        readWordCount := 0.U
      }
    }.otherwise { // Receive instruction (mode === 1.U)
      when (writeActive) {
        io.errorBadInstr := true.B
      }.otherwise {
        writeActive := true.B
        writeLength := io.instr.bits.length
        writeAddress := io.instr.bits.addr
        writeStartOffset := io.instr.bits.startOffset
        writeStride := io.instr.bits.stride
        writeWordCount := 0.U
      }
    }
  }

  // Handle read operations (Send)
  when (readActive) {
    val shouldRead = (readWordCount >= readStartOffset) &&
                    ((readWordCount - readStartOffset) % readStride === 0.U)
    
    when (shouldRead) {
      io.readDDM.address.valid := true.B
      io.readDDM.address.bits := readAddress
      readLength := readLength - 1.U
      readAddress := readAddress + 1.U
      
      when (readLength === 1.U) {
        readActive := false.B
      }
    }.otherwise {
      io.readDDM.address.valid := false.B
    }
    
    readWordCount := readWordCount + 1.U
  }

  // Handle write operations (Receive)
  when (io.fromNetwork.valid) {
    when (!writeActive) {
      when (io.fromNetwork.bits.header) {
        // Extract address and length from the header
        val header = io.fromNetwork.bits.bits.asTypeOf(new Header(params))
        writeActive := true.B
        writeLength := header.length
        writeAddress := header.address
        writeStartOffset := 0.U  // Start immediately for header-initiated transfers
        writeStride := 1.U       // Default to consecutive addressing
        writeWordCount := 0.U
      }.otherwise {
        io.errorBadFromNetwork := true.B
      }
    }.otherwise {
      val shouldWrite = (writeWordCount >= writeStartOffset) &&
                       ((writeWordCount - writeStartOffset) % writeStride === 0.U)
      
      when (shouldWrite) {
        io.writeDDM.enable := true.B
        io.writeDDM.address := writeAddress
        io.writeDDM.data := io.fromNetwork.bits.bits
        
        writeLength := writeLength - 1.U
        writeAddress := writeAddress + 1.U
        
        when (writeLength === 1.U) {
          writeActive := false.B
        }
      }
      
      writeWordCount := writeWordCount + 1.U
    }
  }
}


object ddmAccessGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    // Parse arguments
    if (args.length < 1) {
      println("Usage: <command> <outputDir> ddmAccess <paramsFileName>")
      null
    } else {
      val params = FMPVUParams.fromFile(args(0))
      new ddmAccess(params)
    }
  }
}
