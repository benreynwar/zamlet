package fmvpu.amlet

import chisel3._
import chisel3.util._


object PredicateInstr {

  object Modes extends ChiselEnum {
    val None = Value(0.U)
    val Eq = Value(1.U)
    val NEq = Value(2.U)
    val Gte = Value(3.U)
    val Gt = Value(4.U)
    val Lte = Value(5.U)
    val Lt = Value(6.U)
    val Unused7 = Value(7.U)
  }

  class Src1Mode extends ChiselEnum {
    val Immediate = Value(0.U)
    val LoopIndex = Value(1.U)
    val Global = Value(2.U)
    val Unused3 = Value(3.U)
  }

  def src1Width(params: AmletParams): Int = {
    log2Ceil(scala.math.max(params.nLoopLevels, params.nGRegs))
  }

  class Src1Type(params: AmletParams) extends Bundle {
    val mode = new Src1Mode()
    val value = UInt(src1Width(params).W)
  }

  class Base(params: AmletParams) extends Instr.Base(params) {
    // The condition 'src1 mode src2' as well as 'base and not notBase' or 'not base and notBase'
    val mode = Modes()
    val src1 = new Src1Type(params)
    val src2 = params.aReg()
    val base = params.pReg()
    val notBase = Bool()
    val dst = params.pReg()
  }
  
  class Expanded(params: AmletParams) extends Instr.Expanded(params) {
    // The condition 'src1 mode src2' as well as 'base and not notBase' or 'not base and notBase'
    val mode = Modes()
    val src1 = UInt(params.aWidth.W)
    val src2 = params.aReg()
    val base = params.pReg()
    val notBase = Bool()
    val dst = params.pReg()
  }
  
  class Resolving(params: AmletParams) extends Instr.Resolving(params) {
    val mode = Modes()
    val src1 = UInt(params.aWidth.W)
    val src2 = new ATaggedSource(params) 
    val base = new PTaggedSource(params)
    val notBase = Bool()
    val dst = new PTaggedReg(params)

    def baseIsFalse: Bool = {
      base.resolved && (base.value ^ notBase)
    }

    def isResolved(): Bool = {
      baseIsFalse() ||
      (src2.resolved && base.resolved)
    }

    def isMasked(): Bool = {
      false.B
    }

    def resolve(): Resolved = {
      val resolved = Wire(new Resolved(params))
      when (baseIsFalse()) {
        resolved.mode := mode
        resolved.src1 := src1
        resolved.src2 := DontCare
        resolved.base := false.B
        resolved.dst := dst
      } .otherwise {
        resolved.mode := mode
        resolved.src1 := src1
        resolved.src2 := src2.getData
        resolved.base := base.getData
        resolved.dst := dst
      }
      resolved
    }

    def update(writes: ResultBus): Resolving = {
      val resolving = Wire(new Resolving(params))
      resolving.mode := mode
      resolving.src1 := src1
      resolving.src2 := src2.update(writes)
      resolving.base := base.update(writes)
      resolving.notBase := notBase
      resolving.dst := dst
      resolving
    }
  }

  class Resolved(params: AmletParams) extends Instr.Resolved(params) {
    val mode = Modes()
    val src1 = params.aWord()
    val src2 = params.aWord()
    val base = Bool()
    val dst = new PTaggedReg(params)
  }

}
