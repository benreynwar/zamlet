package fmpvu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import chisel3.util.DecoupledIO

import fmpvu.ModuleGenerator

/**
 * Configuration bundle for FifoOrDelay module
 * @param depth Maximum buffer depth for sizing the delay field
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class FifoOrDelayConfig(depth: Int) extends Bundle {
  /** Mode selection: true for FIFO mode, false for delay mode
    * @group Signals
    */
  val isFifo = Bool()
  
  /** Delay amount in cycles for delay mode (0 = passthrough, ignored in FIFO mode)
    * @group Signals
    */
  val delay = UInt(log2Ceil(depth+1).W)
}

/**
 * Configurable FIFO or fixed-delay buffer
 * 
 * This module can operate in two modes:
 * - FIFO mode: Traditional first-in-first-out queue with flow control
 * - Delay mode: Fixed-delay shift register with configurable delay length
 * 
 * The mode is selected at runtime via configuration signals. In delay mode,
 * data flows through the buffer with a fixed latency, while FIFO mode
 * implements proper ready/valid handshaking with backpressure.
 * 
 * @param t Data type for the buffer elements
 * @param depth Maximum buffer depth (must be > 0)
 * @groupdesc Signals The actual hardware fields of the IO Bundle
 */
class FifoOrDelay[T <: Data](t: T, depth: Int) extends Module {
  assert(depth > 0)
  
  val io = IO(new Bundle {
    /** Configuration interface with valid/ready semantics
      * @group Signals
      */
    val config = Input(Valid(new FifoOrDelayConfig(depth)))
    
    /** Input data stream with ready/valid handshaking
      * @group Signals
      */
    val input = Flipped(DecoupledIO(t))
    
    /** Output data stream with ready/valid handshaking
      * @group Signals
      */
    val output = DecoupledIO(t)
  })

  // Internal storage and control registers
  val regs = Reg(Vec(depth, Valid(t)))
  val readAddress = RegInit(0.U(log2Ceil(depth).W))
  val writeAddress = RegInit(0.U(log2Ceil(depth).W))

  // Mode and state tracking
  val isFifo = RegInit(true.B)
  val empty = RegInit(true.B)
  val full = RegInit(false.B)
  val zeroDelay = RegInit(false.B)
  val count = RegInit(0.U(log2Ceil(depth+1).W))

  // Flow control and output logic
  io.input.ready := !full
  when (isFifo) {
    // FIFO mode: output valid when not empty, data from read address
    io.output.valid := !empty
    io.output.bits := regs(readAddress).bits
  }.otherwise {
    // Delay mode: either passthrough (zero delay) or from buffer
    when (zeroDelay) {
      io.output.valid := io.input.valid
      io.output.bits := io.input.bits
    }.otherwise {
      io.output.valid := regs(readAddress).valid
      io.output.bits := regs(readAddress).bits
    }
  }

  // Configuration logic
  when (io.config.valid) {
    isFifo := io.config.bits.isFifo
    zeroDelay := false.B
    count := 0.U
    
    when (io.config.bits.isFifo) {
      // Initialize for FIFO mode
      readAddress := 0.U
      writeAddress := 0.U
      empty := true.B
      full := false.B
    }.otherwise {
      // Initialize for delay mode
      // Read address starts (delay) positions behind write address
      empty := false.B
      full := false.B
      writeAddress := 0.U
      when (io.config.bits.delay > 0.U) {
        readAddress := (depth.U - io.config.bits.delay)
      }.otherwise {
        zeroDelay := true.B
        readAddress := 0.U
      }
    }
    
    // Clear all storage
    for (i <- 0 until depth) {
      regs(i).valid := false.B
    }
  }.otherwise {
    // Normal operation logic
    
    // Read address management
    // In delay mode: always increments
    // In FIFO mode: increments only when data is consumed
    when (!isFifo || (io.output.valid && io.output.ready)) {
      when (readAddress === (depth-1).U) {
        readAddress := 0.U
      }.otherwise {
        readAddress := readAddress + 1.U
      }
    }
    
    // Write address management and data storage
    // In delay mode: always increments
    // In FIFO mode: increments only when data is accepted
    when (!isFifo || (io.input.valid && io.input.ready)) {
      regs(writeAddress).bits := io.input.bits
      regs(writeAddress).valid := io.input.valid
      when (writeAddress === (depth-1).U) {
        writeAddress := 0.U
      }.otherwise {
        writeAddress := writeAddress + 1.U
      }
    }
    
    // FIFO occupancy tracking
    // Maintains count, empty, and full status for flow control
    val countIncr = (io.input.valid && io.input.ready)
    val countDecr = (io.output.valid && io.output.ready)
    when (countIncr && countDecr) {
      // Both increment and decrement - no change
    }.elsewhen (countIncr) {
      count := count + 1.U
      when (count === (depth-1).U) {
        full := true.B
      }
      empty := false.B
    }.elsewhen (countDecr) {
      count := count - 1.U
      when (count === 1.U) {
        empty := true.B
      }
      full := false.B
    }
  }
}


object FifoOrDelayGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 2) {
      println("Usage: <command> <outputDir> FifoOrDelay <width> <depth>")
      null
    } else {
      val width = args(0).toInt
      val depth = args(1).toInt
      new FifoOrDelay(UInt(width.W), depth)
    }
  }
}
