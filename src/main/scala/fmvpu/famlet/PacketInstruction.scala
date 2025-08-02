package fmvpu.famlet

import chisel3._
import chisel3.util._


object PacketInstr {

  object Modes extends ChiselEnum {
    val Null = Value(0.U)
    val Receive = Value(1.U)
    val ReceiveAndForward = Value(2.U)
    val ReceiveForwardAndAppend = Value(3.U)
    val ForwardAndAppend = Value(4.U)
    val Send = Value(5.U)
    val GetWord = Value(6.U)
    val Broadcast = Value(7.U)
    val Unused8 = Value(8.U)
    val Unused9 = Value(9.U)
    val ReceiveAndForwardContinuously = Value(10.U)
    val ReceiveForwardAndAppendContinuously = Value(11.U)
    val ForwardAndAppendContinuously = Value(12.U)
    val SendAndForwardAgain = Value(13.U)
    val Unused14 = Value(14.U)
    val Unused15 = Value(15.U)
  }

  def modeUsesLength(mode: Modes.Type): Bool = {
    (mode === Modes.Send) ||
    (mode === Modes.SendAndForwardAgain) ||
    (mode === Modes.Broadcast)
  }

  def modeUsesTarget(mode: Modes.Type): Bool = {
    (mode === Modes.ReceiveAndForward) ||
    (mode === Modes.ReceiveForwardAndAppend) ||
    (mode === Modes.ForwardAndAppend) ||
    (mode === Modes.ReceiveAndForwardContinuously) ||
    (mode === Modes.ReceiveForwardAndAppendContinuously) ||
    (mode === Modes.ForwardAndAppendContinuously) ||
    (mode === Modes.Send) ||
    (mode === Modes.SendAndForwardAgain) ||
    (mode === Modes.Broadcast)
  }
  
  class Base(params: FamletParams) extends Instr.Base(params) {
    val mode = Modes()
    val result = params.bReg()
    val length = params.aReg()
    val target = params.aReg()
    val predicate = params.pReg()
    val channel = UInt(log2Ceil(params.nChannels).W)

    def expand(): Expanded = {
      val expanded = Wire(new Expanded(params))
      expanded.mode := mode
      expanded.result := result
      expanded.length := length
      expanded.target := target
      expanded.predicate := predicate
      expanded.channel := channel
      expanded
    }
  }

  class Expanded(params: FamletParams) extends Instr.Expanded(params) {
    val mode = Modes()
    val result = params.bReg()
    val length = params.aReg()
    val target = params.aReg()
    val predicate = params.pReg()
    val channel = UInt(log2Ceil(params.nChannels).W)

    def lengthReadEnable(): Bool = {
      modeUsesLength(mode)
    }
    
    def targetReadEnable(): Bool = {
      modeUsesTarget(mode)
    }
    
    def resultReadEnable(): Bool = {
      // For operations that read the current value (like forward operations)
      mode === Modes.ForwardAndAppend ||
      mode === Modes.ForwardAndAppendContinuously
    }
    
    def oldReadEnable(): Bool = {
      // Need old value when predicated and writing to result
      (mode === Modes.Receive ||
       mode === Modes.ReceiveAndForward ||
       mode === Modes.ReceiveForwardAndAppend ||
       mode === Modes.GetWord ||
       mode === Modes.ReceiveAndForwardContinuously ||
       mode === Modes.ReceiveForwardAndAppendContinuously) && predicate =/= 0.U
    }
    
    def writeEnable(): Bool = {
      // Operations that write to the result register
      mode === Modes.Receive ||
      mode === Modes.ReceiveAndForward ||
      mode === Modes.ReceiveForwardAndAppend ||
      mode === Modes.GetWord ||
      mode === Modes.ReceiveAndForwardContinuously ||
      mode === Modes.ReceiveForwardAndAppendContinuously
    }
    
    def rename(newLength: UInt, newTarget: UInt, newResult: UInt, newOld: UInt, newDst: UInt): Renamed = {
      val renamed = Wire(new Renamed(params))
      renamed.mode := mode
      renamed.length := newLength
      renamed.target := newTarget
      renamed.result := newResult
      renamed.old := newOld
      renamed.dst := newDst
      renamed.predicate := predicate
      renamed.channel := channel
      renamed
    }
  }
  
  class Renamed(params: FamletParams) extends Instr.Renamed(params) {
    val mode = Modes()
    val length = params.aPhysReg()
    val target = params.aPhysReg()
    val result = params.bPhysReg()
    val old = params.bPhysReg()
    val dst = params.bPhysReg()
    val predicate = params.pReg()
    val channel = UInt(log2Ceil(params.nChannels).W)
  }
  
  class SendResolving(params: FamletParams) extends Instr.Resolving(params) {
    val mode = Modes()
    val length = new ASource(params)
    val target = new ASource(params)
    val channel = UInt(log2Ceil(params.nChannels).W)
    val predicate = new PTaggedSource(params)
    val appendLength = UInt(params.aRegWidth.W)

    def isResolved(): Bool = {
      ((length.resolved || !modeUsesLength(mode)) && (target.resolved || !modeUsesTarget(mode)) && predicate.resolved)
    }

    def resolve(): SendResolved = {
      val resolved = Wire(new SendResolved(params))
      resolved.mode := mode
      resolved.length := length.getData
      resolved.target := target.getData
      resolved.channel := channel
      resolved.predicate := predicate.getData
      resolved.appendLength := appendLength
      resolved
    }

    def update(writes: ResultBus): SendResolving = {
      val resolving = Wire(new SendResolving(params))
      resolving.mode := mode
      resolving.length := length.update(writes)
      resolving.target := target.update(writes)
      resolving.channel := channel
      resolving.predicate := predicate.update(writes)
      resolving.appendLength := appendLength
      resolving
    }
  }

  class SendResolved(params: FamletParams) extends Instr.Resolved(params) {
    val mode = Modes()
    val length = params.aWord()
    val target = params.aWord()
    val channel = UInt(log2Ceil(params.nChannels).W)
    val predicate = Bool()
    val appendLength = UInt(params.aRegWidth.W)
    
    // Helper methods to extract X and Y coordinates from packed target
    def xTarget: UInt = target(params.xPosWidth - 1, 0)
    def yTarget: UInt = target(params.xPosWidth + params.yPosWidth - 1, params.xPosWidth)
  }

  class ReceiveResolving(params: FamletParams) extends Instr.Resolving(params) {
    val mode = Modes()
    val result = params.bPhysReg()
    val old = new BSource(params)
    val target = new ASource(params)
    val predicate = new PTaggedSource(params)

    def isResolved(): Bool = {
      ((target.resolved || !modeUsesTarget(mode)) && predicate.resolved && predicate.getData) ||
      (old.resolved && predicate.resolved && !predicate.getData)
    }

    def resolve(): ReceiveResolved = {
      val resolved = Wire(new ReceiveResolved(params))
      resolved.mode := mode
      resolved.result := result
      resolved.target := target.getData
      resolved.predicate := predicate.getData
      resolved.old := old.getData
      resolved
    }

    def update(writes: ResultBus): ReceiveResolving = {
      val resolving = Wire(new ReceiveResolving(params))
      resolving.mode := mode
      resolving.result := result
      resolving.old := old.update(writes)
      resolving.target := target.update(writes)
      resolving.predicate := predicate.update(writes)
      resolving
    }
  }

  class ReceiveResolved(params: FamletParams) extends Instr.Resolved(params) {
    val mode = Modes()
    val result = params.bPhysReg()
    val target = params.aWord()
    val predicate = Bool()
    // TODO: This is wasterful.  'old' and 'target' are never used at the same time.
    val old = params.bWord()
    
    // Helper methods to extract X and Y coordinates from packed target
    def xTarget: UInt = target(params.xPosWidth - 1, 0)
    def yTarget: UInt = target(params.xPosWidth + params.yPosWidth - 1, params.xPosWidth)
    
    // Helper methods for forwarding behavior
    def shouldForward: Bool = {
      mode === Modes.ReceiveAndForward ||
      mode === Modes.ReceiveForwardAndAppend ||
      mode === Modes.ReceiveAndForwardContinuously ||
      mode === Modes.ReceiveForwardAndAppendContinuously ||
      mode === Modes.ForwardAndAppend ||
      mode === Modes.ForwardAndAppendContinuously
    }
    
    def shouldAppend: Bool = {
      mode === Modes.ReceiveForwardAndAppend ||
      mode === Modes.ReceiveForwardAndAppendContinuously ||
      mode === Modes.ForwardAndAppend ||
      mode === Modes.ForwardAndAppendContinuously
    }
    
    def forwardContinuously: Bool = {
      mode === Modes.ReceiveAndForwardContinuously ||
      mode === Modes.ReceiveForwardAndAppendContinuously ||
      mode === Modes.ForwardAndAppendContinuously
    }
  }

}