package fmvpu.famlet

import chisel3._
import chisel3.util._


object LoadStoreInstr {

  object Modes extends ChiselEnum {
    val None = Value(0.U)
    val Load = Value(1.U)
    val Store = Value(2.U)
    val Reserved3 = Value(3.U)
  }
  
  class Base(params: FamletParams) extends Instr.Base(params) {
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

  class Expanded(params: FamletParams) extends Instr.Expanded(params) {
    val mode = Modes()
    val addr = params.aReg()
    val reg = params.bReg()
    val predicate = params.pReg()

    def addrReadEnable(): Bool = {
      mode =/= Modes.None
    }
    
    def srcReadEnable(): Bool = {
      mode === Modes.Store
    }
    
    def oldReadEnable(): Bool = {
      mode === Modes.Load && predicate =/= 0.U
    }
    
    def writeEnable(): Bool = {
      mode === Modes.Load
    }
    
    def rename(newAddr: UInt, newSrc: UInt, newOld: UInt, newDst: UInt): Renamed = {
      val renamed = Wire(new Renamed(params))
      renamed.mode := mode
      renamed.addr := newAddr
      renamed.src := newSrc
      renamed.old := newOld
      renamed.dst := newDst
      renamed.predicate := predicate
      renamed
    }
  }
  
  class Renamed(params: FamletParams) extends Instr.Renamed(params) {
    val mode = Modes()
    val addr = params.aPhysReg()
    val src = params.bPhysReg()
    val old = params.bPhysReg()
    val dst = params.bPhysReg()
    val predicate = params.pReg()
  }
  
  class Resolving(params: FamletParams) extends Instr.Resolving(params) {
    val mode = Modes()
    val addr = new ASource(params)
    val src = new BSource(params)
    val predicate = new PTaggedSource(params)
    val dst = params.bPhysReg()

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

  class Resolved(params: FamletParams) extends Instr.Resolved(params) {
    val mode = Modes()
    val addr = params.aWord()
    val src = params.bWord()
    val dst = params.bPhysReg()
    val predicate = Bool()
  }

}