package fmvpu.memory

import chisel3._
import chisel3.util.log2Ceil
import chisel3.util.Valid
import fmvpu.core.FMPVUParams
import fmvpu.network._
import fmvpu.ModuleGenerator
import chisel3.util.UIntToOH
import chisel3.util.{MemoryWritePort, MemoryReadPort}


/**
 * Error signals for the RegisterFile module
 * @param nWritePorts Number of write ports for sizing the error vectors
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class RegisterFileErrors(nWritePorts: Int) extends Bundle {
  /** Indicates if multiple write ports attempted to write to the same address this cycle
    * @group Signals
    */
  val writeConflict = Bool()
}

/**
 * Multi-port register file with write conflict detection
 * 
 * This module implements a register file that supports:
 * - Multiple concurrent read ports (combinational read)
 * - Multiple concurrent write ports with conflict detection
 * - Write conflicts are detected and reported as errors
 * - All reads are combinational (no latency)
 * 
 * @param width Data width in bits
 * @param depth Number of registers
 * @param nReadPorts Number of concurrent read ports
 * @param nWritePorts Number of concurrent write ports
 * @groupdesc Signals The actual hardware fields of the IO Bundle
 */
class RegisterFile(width: Int, depth: Int, nReadPorts: Int, nWritePorts: Int) extends Module {
  val io = IO(new Bundle {
    /** Write ports for concurrent write operations
      * @group Signals
      */
    val writes = Input(Vec(nWritePorts, new MemoryWritePort(UInt(width.W), log2Ceil(depth), false)))
    
    /** Read ports for concurrent read operations (combinational)
      * @group Signals
      */
    val reads = Vec(nReadPorts, new MemoryReadPort(UInt(width.W), log2Ceil(depth)))
    
    /** Error status signals indicating write conflicts
      * @group Signals
      */
    val errors = Output(new RegisterFileErrors(nWritePorts))
  })

  // Register file storage
  val registers = Reg(Vec(depth, UInt(width.W)))

  // Convert write addresses to one-hot encoding for conflict detection
  val writeOneHots = VecInit(io.writes.map(port => UIntToOH(port.address)))
  
  // Check for write conflicts across all addresses
  val addressConflicts = Wire(Vec(depth, Bool()))
  
  for (addr <- 0 until depth) {
    // Collect all valid write requests targeting this address
    val writesToThisAddr = Wire(Vec(nWritePorts, Valid(UInt(width.W))))
    for (portIdx <- 0 until nWritePorts) {
      val targetThisAddr = writeOneHots(portIdx)(addr) && io.writes(portIdx).enable
      writesToThisAddr(portIdx).valid := targetThisAddr
      writesToThisAddr(portIdx).bits := io.writes(portIdx).data
    }
    
    // Use ValidMux to arbitrate writes and detect conflicts
    val writeArbiter = Module(new ValidMux(UInt(width.W), nWritePorts))
    writeArbiter.io.inputs := writesToThisAddr
    addressConflicts(addr) := writeArbiter.io.error
    
    // Apply the arbitrated write if valid
    when(writeArbiter.io.output.valid) {
      registers(addr) := writeArbiter.io.output.bits
    }
  }

  // Combinational reads
  for (portIdx <- 0 until nReadPorts) {
    io.reads(portIdx).data := registers(io.reads(portIdx).address)
  }
  
  // Report write conflicts
  io.errors.writeConflict := addressConflicts.reduce(_ || _)
}


/** Generator object for creating RegisterFile modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of RegisterFile modules with configurable parameters.
  */
object RegisterFileGenerator extends ModuleGenerator {
  /** Create a RegisterFile module with the specified parameters.
    *
    * @param args Command line arguments: width, depth, nReadPorts, nWritePorts
    * @return RegisterFile module instance configured with the provided parameters
    */
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
