package fmvpu.amlet

import chisel3._
import chisel3.util._


object ControlInstr {

  object Modes extends ChiselEnum {
    val None = Value(0.U)
    val LoopImmediate = Value(1.U)       
    val LoopLocal = Value(2.U)
    val LoopGlobal = Value(3.U)
    // Increments the index of the current loop
    // Only really used in the resolvoing version we pass to amlet.
    val Incr = Value(4.U)
    val Reserved5 = Value(5.U)       
    val Reserved6 = Value(6.U)
    val Halt = Value(7.U)
  }

  object SrcMode extends ChiselEnum {
    val Immediate = Value(0.U)
    val AReg = Value(1.U)
    val GReg = Value(2.U)
    val Unused3 = Value(3.U)
  }

  def srcWidth(params: AmletParams): Int = {
    log2Ceil(scala.math.max(params.nARegs, params.nGRegs))
  }

  class BaseSrcType(params: AmletParams) extends Bundle {
    val mode = SrcMode()
    val value = UInt(srcWidth(params).W)
  }

  class ExtendedSrcType(params: AmletParams) extends Bundle {
    val resolved = Bool()
    val addr = params.aReg()
    val value = UInt(params.aWidth.W)
  }
  
  // The number of iterations could come from an areg or a greg or a immediate
  class Base(params: AmletParams) extends Instr.Base(params) {
    val mode = Modes()
    val iterations = UInt(srcWidth(params).W)  // Value (immediate, A-reg index, or G-reg index)
    val dst = params.aReg()                    // Where the loop index goes.
    val predicate = params.pReg()              // loop_index < iterations put here.
    val length = UInt(params.instrAddrWidth.W) // Number of instructions in the loop body.

    def expand(): Expanded = {
      val expanded = Wire(new Expanded(params))
      expanded.mode := mode
      expanded.iterations.resolved := false.B  
      expanded.iterations.addr := iterations  
      expanded.iterations.value := DontCare
      expanded.dst := dst
      expanded.predicate := predicate
      expanded.level := 0.U
      expanded
    }
  }

  class Expanded(params: AmletParams) extends Instr.Expanded(params) {
    val mode = Modes()
    val iterations = new ExtendedSrcType(params) // Where the number of iterations comes from.
    val dst = params.aReg()                    // Where the loop index goes.
    val predicate = params.pReg()              // loop_index < iterations put here.
    val level = UInt(log2Ceil(params.nLoopLevels).W)
  }

}
