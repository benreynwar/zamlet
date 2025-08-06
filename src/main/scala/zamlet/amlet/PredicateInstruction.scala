package zamlet.amlet

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

  object Src1Mode extends ChiselEnum {
    val Immediate = Value(0.U)
    val LoopIndex = Value(1.U)
    val Global = Value(2.U)
    val Unused3 = Value(3.U)
  }

  def src1Width(params: AmletParams): Int = {
    log2Ceil(scala.math.max(params.nLoopLevels, params.nGRegs))
  }

  class Src1Type(params: AmletParams) extends Bundle {
    val mode = Src1Mode()
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

    def expand(): Expanded = {
      val expanded = Wire(new Expanded(params))
      expanded.mode := mode
      expanded.src1Mode := src1.mode
      expanded.src1 := src1.value
      expanded.src2 := src2
      expanded.base := base
      expanded.notBase := notBase
      expanded.dst := dst
      expanded
    }
  }
  
  class Expanded(params: AmletParams) extends Instr.Expanded(params) {
    // The condition 'src1 mode src2' as well as 'base and not notBase' or 'not base and notBase'
    val mode = Modes()
    val src1Mode = Src1Mode()
    val src1 = UInt(params.aWidth.W)
    val src2 = params.aReg()
    val base = params.pReg()
    val notBase = Bool()
    val dst = params.pReg()
    
    private val regUtils = new RegUtils(params)

    def getTReads(): Seq[Valid[UInt]] = {
      val src2Read = Wire(Valid(params.tReg()))
      src2Read.valid := true.B
      src2Read.bits := regUtils.aRegToTReg(src2)
      
      val baseRead = Wire(Valid(params.tReg()))
      baseRead.valid := true.B
      baseRead.bits := regUtils.pRegToTReg(base)
      
      // Add src1 read dependency when src1Mode is LoopIndex
      val src1Read = Wire(Valid(params.tReg()))
      src1Read.valid := src1Mode === Src1Mode.LoopIndex
      // When LoopIndex mode, src1 contains the loop level. We create a dependency
      // on a synthetic L-register representing that loop level, which control instructions
      // will write to when managing loop state
      src1Read.bits := regUtils.lRegToTReg(src1)
      
      Seq(src2Read, baseRead, src1Read)
    }

    def getTWrites(): Seq[Valid[UInt]] = {
      val dstWrite = Wire(Valid(params.tReg()))
      dstWrite.valid := true.B
      dstWrite.bits := regUtils.pRegToTReg(dst)
      Seq(dstWrite)
    }
  }
  
  class Resolving(params: AmletParams) extends Instr.Resolving(params) {
    val mode = Modes()
    val src1 = UInt(params.aWidth.W)
    val src2 = new ATaggedSource(params) 
    val base = new PTaggedSource(params)
    val notBase = Bool()
    val dst = new PTaggedReg(params)

    /** 
     * Determines if the base predicate evaluates to false after applying notBase.
     * The effective predicate is: (base XOR notBase)
     * - If notBase=false: effective = base (normal case)  
     * - If notBase=true:  effective = !base (inverted case)
     * When this returns true, the instruction can be resolved early without evaluating src1/src2.
     */
    def baseIsFalse: Bool = {
      base.resolved && !(base.value ^ notBase)
    }

    /**
     * An instruction is resolved when either:
     * 1. The base predicate evaluates to false (early termination), OR
     * 2. All operands (src2 and base) are resolved (normal evaluation)
     */
    def isResolved(): Bool = {
      baseIsFalse ||
      (src2.resolved && base.resolved)
    }

    /** Predicate instructions are never masked (they compute mask values) */
    def isMasked(): Bool = {
      false.B
    }

    def resolve(): Resolved = {
      val resolved = Wire(new Resolved(params))
      resolved.mode := mode
      resolved.src1 := src1
      resolved.src2 := src2.getData
      resolved.base := base.getData ^ notBase  // Apply notBase to get effective base
      resolved.dst := dst
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
