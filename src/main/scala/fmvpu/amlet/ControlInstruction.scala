package fmvpu.amlet

import chisel3._
import chisel3.util._


object ControlInstr {

  object Modes extends ChiselEnum {
    val None = Value(0.U)
    val If = Value(1.U)       
    val Loop = Value(2.U)
    val Reserved3 = Value(3.U)
    // Increments the index of the current loop
    // Only really used in the resolvoing version we pass to amlet.
    val Incr = Value(4.U)
    val Reserved5 = Value(5.U)       
    val Reserved6 = Value(6.U)
    val Halt = Value(7.U)
  }
  
  class Base(params: AmletParams) extends Instr.Base(params) {
    val mode = Modes()
    val src = params.aReg()
    val dst = params.aReg()
    val length = UInt(params.instrAddrWidth.W)
  }

}
