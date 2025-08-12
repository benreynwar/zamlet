package zamlet.amlet

import chisel3._
import chisel3.util._


object ALUInstr {

  object Modes extends ChiselEnum {
    val None = Value(0.U)
    val Add = Value(1.U)       
    val Addi = Value(2.U)
    val Sub = Value(3.U)
    val Subi = Value(4.U)
    val Mult = Value(5.U)
    val MultAcc = Value(6.U)
    val MultAccInit = Value(7.U)
  
    val Eq = Value(8.U)
    val Gte = Value(9.U)
    val Lte = Value(10.U)
    val Not = Value(11.U)
    val And = Value(12.U)
    val Or = Value(13.U)
    val Reserved14 = Value(14.U)
    val Reserved15 = Value(15.U)
  
    val ShiftL = Value(16.U)
    val ShiftR = Value(17.U)
    val Reserved18 = Value(18.U)
    val Reserved19 = Value(19.U)
    val Reserved20 = Value(20.U)
    val Reserved21 = Value(21.U)
    val Reserved22 = Value(22.U)
    val Reserved23 = Value(23.U)
    val Reserved24 = Value(24.U)
    val Reserved25 = Value(25.U)
    val Reserved26 = Value(26.U)
    val Reserved27 = Value(27.U)
    val Reserved28 = Value(28.U)
    val Reserved29 = Value(29.U)
    val Reserved30 = Value(30.U)
    val Reserved31 = Value(31.U)
  }

  def modeIsImmediate(mode: Modes.Type): Bool = {
    (mode === Modes.Subi) ||
    (mode === Modes.Addi) ||
    false.B
  }

  class Base(params: AmletParams) extends Instr.Base(params) {
    val mode = Modes()
    val src1 = params.dReg()
    val src2 = params.dReg()
    val predicate = params.pReg()
    val dst = params.bReg()

    def expand(): Expanded = {
      val expanded = Wire(new Expanded(params))
      expanded.mode := mode
      expanded.src1 := src1
      expanded.src2 := src2
      expanded.predicate := predicate
      expanded.dst := dst
      expanded
    }
  }
  
  class Expanded(params: AmletParams) extends Instr.Expanded(params) {
    val mode = Modes()
    val src1 = params.dReg()
    val src2 = params.dReg()
    val predicate = params.pReg()
    val dst = params.bReg()
    
    private val regUtils = new RegUtils(params)

    def getTReads(): Seq[Valid[UInt]] = {
      val src1Read = Wire(Valid(params.tReg()))
      src1Read.valid := true.B
      src1Read.bits := regUtils.dRegToTReg(src1)
      
      val src2Read = Wire(Valid(params.tReg()))
      src2Read.valid := true.B
      src2Read.bits := regUtils.dRegToTReg(src2)
      
      val predicateRead = Wire(Valid(params.tReg()))
      predicateRead.valid := true.B
      predicateRead.bits := regUtils.pRegToTReg(predicate)
      
      Seq(src1Read, src2Read, predicateRead)
    }

    def getTWrites(): Seq[Valid[UInt]] = {
      val dstWrite = Wire(Valid(params.tReg()))
      dstWrite.valid := true.B
      dstWrite.bits := regUtils.bRegToTReg(dst)
      Seq(dstWrite)
    }
  }
  
  class Resolving(params: AmletParams) extends Instr.Resolving(params) {
    val mode = Modes()
    val src1 = new DTaggedSource(params)
    val src2 = new DTaggedSource(params) 
    val predicate = new PTaggedSource(params)
    val old = new BTaggedSource(params)
    val dst = new BTaggedReg(params)

    def isResolved(): Bool = {
      (src1.resolved && src2.resolved && predicate.resolved && predicate.getData) ||
      (old.resolved && predicate.resolved && !predicate.getData)
    }

    def resolve(): Resolved = {
      val resolved = Wire(new Resolved(params))
      resolved.mode := mode
      when (predicate.getData) {
        resolved.src1 := src1.getData
      } .otherwise {
        resolved.src1 := old.getData
      }
      resolved.src2 := src2.getData
      resolved.dst := dst
      resolved.predicate := predicate.getData
      resolved
    }

    def update(writes: ResultBus): Resolving = {
      val resolving = Wire(new Resolving(params))
      resolving.mode := mode
      resolving.src1 := src1.update(writes)
      resolving.src2 := src2.update(writes)
      resolving.old := old.update(writes)
      resolving.predicate := predicate.update(writes)
      resolving.dst := dst
      resolving
    }
  }

  class Resolved(params: AmletParams) extends Instr.Resolved(params) {
    val mode = Modes()
    val src1 = params.dWord()
    val src2 = params.dWord()
    val dst = new BTaggedReg(params)
    val predicate = Bool()
  }

}
