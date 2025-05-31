package fmpvu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid

import fmpvu.ModuleGenerator

/**
 * Error signals for the AdjustableDelay module
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class AdjustableDelayErrors extends Bundle {
  /** Asserted when new input would overwrite existing valid data
    * @group Signals
    */
  val dataOverwrite = Bool()
}

/**
 * A configurable delay line that can delay input data by 0 to maxDelay clock cycles.
 * 
 * This module implements a shift register where data flows from higher indices to lower indices.
 * The delay amount is configurable at runtime via the delay input port.
 * 
 * Operation:
 * - delay = 0: Input passes directly to output (zero delay passthrough)
 * - delay > 0: Input is stored at register stage (delay-1) and shifts through the register chain
 * - Output comes from register stage 0 (except in zero-delay mode)
 * 
 * @param maxDelay Maximum number of clock cycles that can be delayed (1 to maxDelay)
 * @param width Bit width of the data being delayed
 * @groupdesc Signals The actual hardware fields of the IO Bundle
 */
class AdjustableDelay(maxDelay: Int, width: Int) extends Module {
  val io = IO(new Bundle {
    /** Number of clock cycles to delay the input data (0 to maxDelay)
      * @group Signals
      */
    val delay = Input(UInt(log2Ceil(maxDelay + 1).W))
    
    /** Input data with valid signal to be delayed
      * @group Signals
      */
    val input = Input(Valid(UInt(width.W)))
    
    /** Delayed output data with valid signal
      * @group Signals
      */
    val output = Output(Valid(UInt(width.W)))
    
    /** Error status signals indicating potential data corruption
      * @group Signals
      */
    val errors = Output(new AdjustableDelayErrors)
  })

  val delayRegs = Reg(Vec(maxDelay, Valid(UInt(width.W))))

  // The next value of the delayRegs without any new writes
  val flowedDelayRegs = Wire(Vec(maxDelay, Valid(UInt(width.W))))
  flowedDelayRegs := delayRegs

  // Shift register implementation: data flows from higher to lower indices
  for (i <- 0 until maxDelay - 1) {
    flowedDelayRegs(i) := delayRegs(i + 1)
  }
  flowedDelayRegs(maxDelay-1).valid := false.B
  flowedDelayRegs(maxDelay-1).bits := DontCare

  delayRegs := flowedDelayRegs

  // Input handling: place new data at the appropriate delay stage
  io.errors.dataOverwrite := false.B
  when(io.input.valid) {
    when(io.delay === 0.U) {
      // Zero delay: output directly, don't store in registers
    }.otherwise {
      delayRegs(io.delay - 1.U) := io.input
      when (flowedDelayRegs(io.delay - 1.U).valid) {
        io.errors.dataOverwrite := true.B
      }
    }
  }

  // Output selection
  io.output := Mux(io.delay === 0.U, io.input, delayRegs(0))

}


object AdjustableDelayGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 2) {
      println("Usage: <command> <outputDir> AdjustableDelay <maxDelay> <width>")
      null
    } else {
      val maxDelay = args(0).toInt
      val width = args(1).toInt
      new AdjustableDelay(maxDelay, width)
    }
  }
}
