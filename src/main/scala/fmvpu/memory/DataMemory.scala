package fmvpu.memory

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import fmvpu.core.FMPVUParams
import fmvpu.network._
import fmvpu.ModuleGenerator
import chisel3.util.UIntToOH
import chisel3.util.{MemoryWritePort, SRAM}

import scala.io.Source


/**
 * Error signals for the DataMemory module
 * @param nBanks Number of memory banks for sizing the error vectors
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class DataMemoryErrors(nBanks: Int) extends Bundle {
  /** Vector indicating which banks have access conflicts this cycle
    * @group Signals
    */
  val bankConflicts = Vec(nBanks, Bool())
}

/**
 * Multi-banked data memory with concurrent read/write access
 * 
 * This module implements a banked memory system where:
 * - Total memory space is divided into multiple independent banks
 * - Each bank can handle one operation (read or write) per cycle
 * - Bank conflicts are detected and reported as errors
 * - Memory has 1-cycle read latency
 * 
 * @param width Data width in bits
 * @param depth Depth per bank (total capacity = depth * nBanks)
 * @param nBanks Number of memory banks
 * @groupdesc Signals The actual hardware fields of the IO Bundle
 */
class DataMemory(width: Int, depth: Int, nBanks: Int) extends Module {
  val nWritePorts = 2
  val nReadPorts = 2
  
  // Address layout: [bank_bits][addr_bits]
  val bankAddrWidth = log2Ceil(nBanks)
  val localAddrWidth = log2Ceil(depth)
  val totalAddrWidth = bankAddrWidth + localAddrWidth

  val io = IO(new Bundle {
    /** Write ports for concurrent write operations
      * @group Signals
      */
    val writes = Input(Vec(nWritePorts, new MemoryWritePort(UInt(width.W), totalAddrWidth, false)))
    
    /** Read ports for concurrent read operations with 1-cycle latency
      * @group Signals
      */
    val reads = Vec(nReadPorts, new ValidReadPort(UInt(width.W), totalAddrWidth))
    
    /** Error status signals indicating bank conflicts and other issues
      * @group Signals
      */
    val errors = Output(new DataMemoryErrors(nBanks))
  })

  // Extract bank indices from addresses
  val writeBanks = VecInit(io.writes.map(_.address(totalAddrWidth - 1, localAddrWidth)))
  val readValids = VecInit(io.reads.map(_.address.valid))
  val readBanks = VecInit(io.reads.map(_.address.bits(totalAddrWidth - 1, localAddrWidth)))

  val bankClashes = Wire(Vec(nBanks, Bool()))
  val bankOutputData = Wire(Vec(nBanks, UInt(width.W)))

  // Generate one memory bank and its arbitration logic
  for (bankIndex <- 0 until nBanks) {
    // Collect all read/write requests targeting this bank
    val bankRequests = Wire(Vec(nReadPorts + nWritePorts, Valid(new ReadWriteInputPort(width, localAddrWidth))))
    
    // Map read requests to this bank
    for (i <- 0 until nReadPorts) {
      val targetThisBank = io.reads(i).address.valid && readBanks(i) === bankIndex.U
      val localAddr = io.reads(i).address.bits(localAddrWidth - 1, 0)
      
      bankRequests(i).valid := targetThisBank
      bankRequests(i).bits.enable := targetThisBank
      bankRequests(i).bits.isWrite := false.B
      bankRequests(i).bits.address := localAddr
      bankRequests(i).bits.data := DontCare
    }
    
    // Map write requests to this bank
    for (i <- 0 until nWritePorts) {
      val targetThisBank = io.writes(i).enable && writeBanks(i) === bankIndex.U
      val localAddr = io.writes(i).address(localAddrWidth - 1, 0)
      val reqIndex = nReadPorts + i
      
      bankRequests(reqIndex).valid := targetThisBank
      bankRequests(reqIndex).bits.enable := targetThisBank
      bankRequests(reqIndex).bits.isWrite := true.B
      bankRequests(reqIndex).bits.address := localAddr
      bankRequests(reqIndex).bits.data := io.writes(i).data
    }
    
    // Arbitrate between multiple requests to same bank (reports conflicts)
    val arbitrator = Module(new ValidMux(new ReadWriteInputPort(width, localAddrWidth), nReadPorts + nWritePorts))
    arbitrator.io.inputs := bankRequests
    bankClashes(bankIndex) := arbitrator.io.error

    // Connect arbitrated request to SRAM
    val sram = SRAM(depth, UInt(width.W), 0, 0, 1)
    val memPort = sram.readwritePorts(0)
    
    memPort.enable := arbitrator.io.output.valid && arbitrator.io.output.bits.enable
    memPort.isWrite := arbitrator.io.output.bits.isWrite
    memPort.writeData := arbitrator.io.output.bits.data
    memPort.address := arbitrator.io.output.bits.address
    
    bankOutputData(bankIndex) := memPort.readData
  }

  // Pipeline read responses (1-cycle memory latency)
  val readOutputValids = RegNext(readValids)
  val readOutputBanks = RegNext(readBanks)
  
  for (i <- 0 until nReadPorts) {
    io.reads(i).data.valid := readOutputValids(i)
    io.reads(i).data.bits := bankOutputData(readOutputBanks(i))
  }
  
  // Pipeline error outputs
  io.errors.bankConflicts := RegNext(bankClashes)
}

/** Generator object for creating DataMemory modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of DataMemory modules with configurable parameters.
  */
object DataMemoryGenerator extends ModuleGenerator {
  /** Create a DataMemory module with the specified parameters.
    *
    * @param args Command line arguments: width, depth, nBanks
    * @return DataMemory module instance configured with the provided parameters
    */
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
