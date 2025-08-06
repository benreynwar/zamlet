package zamlet.amlet

import chisel3._
import chisel3.util._


object LoadStoreInstr {

  object Modes extends ChiselEnum {
    val None = Value(0.U)
    val Load = Value(1.U)
    val Store = Value(2.U)
    val Reserved3 = Value(3.U)
  }
  
  class Base(params: AmletParams) extends Instr.Base(params) {
    val mode = Modes()
    val addr = params.aReg()
    val reg = params.bReg()
    val predicate = params.pReg()

    def expand(): Expanded = {
      val expanded = Wire(new Expanded(params))
      expanded.mode := mode
      expanded.addr := addr
      expanded.reg := reg
      expanded.predicate := predicate
      expanded
    }
  }

  class Expanded(params: AmletParams) extends Instr.Expanded(params) {
    val mode = Modes()
    val addr = params.aReg()
    val reg = params.bReg()
    val predicate = params.pReg()
    
    private val regUtils = new RegUtils(params)

    def getTReads(): Seq[Valid[UInt]] = {
      val addrRead = Wire(Valid(params.tReg()))
      addrRead.valid := true.B
      addrRead.bits := regUtils.aRegToTReg(addr)
      
      val regRead = Wire(Valid(params.tReg()))
      regRead.valid := mode === Modes.Store
      regRead.bits := regUtils.bRegToTReg(reg)
      
      val predicateRead = Wire(Valid(params.tReg()))
      predicateRead.valid := true.B
      predicateRead.bits := regUtils.pRegToTReg(predicate)
      
      Seq(addrRead, regRead, predicateRead)
    }

    def getTWrites(): Seq[Valid[UInt]] = {
      val regWrite = Wire(Valid(params.tReg()))
      regWrite.valid := mode === Modes.Load
      regWrite.bits := regUtils.bRegToTReg(reg)
      Seq(regWrite)
    }
  }
  
  class Resolving(params: AmletParams) extends Instr.Resolving(params) {
    val mode = Modes()
    val addr = new ATaggedSource(params)
    val src = new BTaggedSource(params)
    val predicate = new PTaggedSource(params)
    val dst = new BTaggedReg(params)

    def isResolved(): Bool = {
      (mode === Modes.Store && addr.resolved && src.resolved && predicate.resolved && predicate.getData) ||   // Store
      (mode === Modes.Load && addr.resolved && predicate.resolved && predicate.getData) ||   // Load
      (src.resolved && predicate.resolved && !predicate.getData)                   // !Predicate
    }

    def resolve(): Resolved = {
      val resolved = Wire(new Resolved(params))
      resolved.mode := mode
      resolved.addr := addr.getData
      resolved.src := src.getData
      resolved.dst := dst
      resolved.predicate := predicate.getData
      resolved
    }

    def update(writes: ResultBus): Resolving = {
      val resolving = Wire(new Resolving(params))
      resolving.mode := mode
      resolving.addr := addr.update(writes)
      resolving.src := src.update(writes)
      resolving.predicate := predicate.update(writes)
      resolving.dst := dst
      resolving
    }
  }

  class Resolved(params: AmletParams) extends Instr.Resolved(params) {
    val mode = Modes()
    val addr = params.aWord()
    val src = params.bWord()
    val dst = new BTaggedReg(params)
    val predicate = Bool()
  }

}
