package zamlet.famlet

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

  class Base(params: FamletParams) extends Instr.Base(params) {
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
  
  class Expanded(params: FamletParams) extends Instr.Expanded(params) {
    val mode = Modes()
    val src1 = params.dReg()
    val src2 = params.dReg()
    val predicate = params.pReg()
    val dst = params.bReg()

    def src1ReadEnable(): Bool = {
      mode =/= Modes.None
    }
    
    def src2ReadEnable(): Bool = {
      mode =/= Modes.None && mode =/= Modes.Addi && mode =/= Modes.Subi
    }
    
    def oldReadEnable(): Bool = {
      mode =/= Modes.None && predicate =/= 0.U
    }
    
    def writeEnable(): Bool = {
      mode =/= Modes.None
    }
    
    def rename(newSrc1: UInt, newSrc2: UInt, newOld: UInt, newDst: UInt): Renamed = {
      val renamed = Wire(new Renamed(params))
      renamed.mode := mode
      renamed.src1 := newSrc1
      renamed.src2 := newSrc2
      renamed.old := newOld
      renamed.dst := newDst
      renamed.predicate := predicate
      renamed
    }
  }
  
  class Renamed(params: FamletParams) extends Instr.Renamed(params) {
    val mode = Modes()
    val src1 = params.dPhysReg()
    val src2 = params.dPhysReg()
    val old = params.bPhysReg()
    val dst = params.bPhysReg()
    val predicate = params.pReg()
  }
  
  class Resolving(params: FamletParams) extends Instr.Resolving(params) {
    val mode = Modes()
    val src1 = new DSource(params)
    val src2 = new DSource(params) 
    val predicate = new PTaggedSource(params)
    val old = new BSource(params)
    val dst = params.bPhysReg()

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

  class Resolved(params: FamletParams) extends Instr.Resolved(params) {
    val mode = Modes()
    val src1 = params.dWord()
    val src2 = params.dWord()
    val dst = params.bPhysReg()
    val predicate = Bool()
  }

}
