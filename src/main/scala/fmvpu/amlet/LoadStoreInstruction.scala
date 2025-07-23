package fmvpu.amlet

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
  }
  
  class Resolving(params: AmletParams) extends Instr.Resolving(params) {
    val mode = Modes()
    val addr = new ATaggedSource(params)
    val src = new BTaggedSource(params)
    val mask = new MaskInfo(params)
    val dst = new BTaggedReg(params)

    def isResolved(): Bool = {
      addr.resolved && 
      src.resolved && 
      mask.resolved
    }

    def isMasked(): Bool = {
      mask.resolved && mask.getData
    }

    def resolve(): Resolved = {
      val resolved = Wire(new Resolved(params))
      resolved.mode := mode
      resolved.addr := addr.getData
      resolved.src := src.getData
      resolved.dst := dst
      resolved
    }

    def update(writes: ResultBus): Resolving = {
      val resolving = Wire(new Resolving(params))
      resolving.mode := mode
      resolving.addr := addr.update(writes)
      resolving.src := src.update(writes)
      resolving.mask := mask.update(writes)
      resolving.dst := dst
      resolving
    }
  }

  class Resolved(params: AmletParams) extends Instr.Resolved(params) {
    val mode = Modes()
    val addr = params.aWord()
    val src = params.bWord()
    val dst = new BTaggedReg(params)
  }

}
