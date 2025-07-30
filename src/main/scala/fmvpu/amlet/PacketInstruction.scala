package fmvpu.amlet

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
    val GetPacketWord = Value(6.U)
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
  
  class Base(params: AmletParams) extends Instr.Base(params) {
    val mode = Modes()
    val result = params.bReg()
    val length = params.aReg()
    val target = params.aReg()
    val predicate = params.pReg()
    val channel = UInt(log2Ceil(params.nChannels).W)
  }

  class Expanded(params: AmletParams) extends Instr.Expanded(params) {
    val mode = Modes()
    val result = params.bReg()
    val length = params.aReg()
    val target = params.aReg()
    val predicate = params.pReg()
    val channel = UInt(log2Ceil(params.nChannels).W)
  }
  
  class SendResolving(params: AmletParams) extends Instr.Resolving(params) {
    val mode = Modes()
    val result = new BTaggedReg(params)
    val length = new ATaggedSource(params)
    val target = new ATaggedSource(params)
    val channel = UInt(log2Ceil(params.nChannels).W)
    val predicate = new PTaggedSource(params)

    def isResolved(): Bool = {
      length.resolved && 
      target.resolved && 
      predicate.resolved
    }

    def isMasked(): Bool = {
      predicate.resolved && !predicate.getData
    }

    def resolve(): SendResolved = {
      val resolved = Wire(new SendResolved(params))
      resolved.mode := mode
      resolved.result := result
      resolved.length := length.getData
      resolved.target := target.getData
      resolved.channel := channel
      resolved
    }

    def update(writes: ResultBus): SendResolving = {
      val resolving = Wire(new SendResolving(params))
      resolving.mode := mode
      resolving.result := result
      resolving.length := length.update(writes)
      resolving.target := target.update(writes)
      resolving.channel := channel
      resolving.predicate := predicate.update(writes)
      resolving
    }
  }

  class SendResolved(params: AmletParams) extends Instr.Resolved(params) {
    val mode = Modes()
    val result = new BTaggedReg(params)
    val length = params.aWord()
    val target = params.aWord()
    val channel = UInt(log2Ceil(params.nChannels).W)
    
    // Helper methods to extract X and Y coordinates from packed target
    def xTarget: UInt = target(params.xPosWidth - 1, 0)
    def yTarget: UInt = target(params.xPosWidth + params.yPosWidth - 1, params.xPosWidth)
  }

  class ReceiveResolving(params: AmletParams) extends Instr.Resolving(params) {
    val mode = Modes()
    val result = new BTaggedReg(params)
    val target = new ATaggedSource(params)
    val predicate = new PTaggedSource(params)

    def isResolved(): Bool = {
      target.resolved && 
      predicate.resolved
    }

    def isMasked(): Bool = {
      predicate.resolved && !predicate.getData
    }

    def resolve(): ReceiveResolved = {
      val resolved = Wire(new ReceiveResolved(params))
      resolved.mode := mode
      resolved.result := result
      resolved.target := target.getData
      resolved
    }

    def update(writes: ResultBus): ReceiveResolving = {
      val resolving = Wire(new ReceiveResolving(params))
      resolving.mode := mode
      resolving.result := result
      resolving.target := target.update(writes)
      resolving.predicate := predicate.update(writes)
      resolving
    }
  }

  class ReceiveResolved(params: AmletParams) extends Instr.Resolved(params) {
    val mode = Modes()
    val result = new BTaggedReg(params)
    val target = params.aWord()
    
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
