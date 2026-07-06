package zamlet.jamlet

import chisel3._
import chisel3.experimental.ExtModule
import chisel3.util._
import zamlet.ZamletParams
import zamlet.utils.DoubleBuffer
import zamlet.utils.ValidBuffer
import zamlet.network.{CacheLineHeader, MessageType, NetworkWord, SendType}

class JceOp(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
}

class JceTxA(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
  val wordOffset = UInt(params.log2CacheSlotWordsPerJamlet.W)
}

class JceErrors extends Bundle {
  val badRxLength = Bool()
  val badRxMessageType = Bool()
}

class JceIO(params: ZamletParams) extends Bundle {
  val memletX = Input(params.xPos())
  val memletY = Input(params.yPos())
  val thisX = Input(params.xPos())
  val thisY = Input(params.yPos())

  val op = Flipped(Decoupled(new JceOp(params)))
  val rxDone = Valid(params.cacheSlot())

  val sramReadReq = Decoupled(UInt(params.sramAddrWidth.W))
  val sramReadResp = Flipped(Decoupled(params.word()))
  val sramWriteReq = Decoupled(new SramWriteRequest(params))
  val sramWriteResp = Flipped(Decoupled())

  val packetIn = Flipped(Decoupled(new NetworkWord(params)))
  val packetOut = Decoupled(new NetworkWord(params))
  val errors = Output(new JceErrors())
}

class JceTxC(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
  val wordOffset = UInt(params.log2CacheSlotWordsPerJamlet.W)
  val data = params.word()
}

class JceRxA(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
  val wordOffset = UInt(params.log2CacheSlotWordsPerJamlet.W)
  val last = Bool()
  val data = params.word()
}

class JceRxAState(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
  val remainingBodyWords = UInt(params.messageLengthWidth.W)
  val wordOffset = UInt(params.log2CacheSlotWordsPerJamlet.W)
  val isHeader = Bool()
}

object JcePacketState extends ChiselEnum {
  val Header, Data = Value
}

class SramWriteRequest(params: ZamletParams) extends Bundle {
  val address = UInt(params.sramAddrWidth.W)
  val data = params.word()
}

class Jce(params: ZamletParams) extends Module {
  val io = IO(new JceIO(params))
  val jp = params.jceParams

  val txAIn = DoubleBuffer(io.op, jp.opFB, jp.opBB)

  val txASramReq = Wire(Decoupled(UInt(params.sramAddrWidth.W)))
  
  val txAOut = Wire(Decoupled(new JceTxA(params)))
  val txAWordOffsetNext = Wire(UInt(params.log2CacheSlotWordsPerJamlet.W))
  val txAWordOffset = RegEnable(txAWordOffsetNext, 0.U, txASramReq.fire)
  val txALastWord = txAWordOffset === (params.cacheSlotWordsPerJamlet - 1).U

  txASramReq.valid := txAIn.valid && txAOut.ready
  txAOut.valid := txAIn.valid && txASramReq.ready
  txAIn.ready := txAOut.ready && txASramReq.ready && txALastWord

  txAWordOffsetNext := Mux(txALastWord, 0.U, txAWordOffset + 1.U)

  txASramReq.bits := Cat(txAIn.bits.slot, txAWordOffset)
  io.sramReadReq <> DoubleBuffer(txASramReq, jp.sramReadReqFB, jp.sramReadReqBB)

  txAOut.bits.slot := txAIn.bits.slot
  txAOut.bits.wordOffset := txAWordOffset

  val txBIn = DoubleBuffer(txAOut, jp.abFB, jp.abBB)

  val txCIn = DoubleBuffer(txBIn, jp.bcFB, jp.bcBB)
  val txCSramResp = DoubleBuffer(io.sramReadResp, jp.sramReadRespFB, jp.sramReadRespBB)

  val txCMerged = Wire(Decoupled(new JceTxC(params)))
  txCMerged.valid := txCIn.valid && txCSramResp.valid
  txCIn.ready := txCMerged.ready && txCSramResp.valid
  txCSramResp.ready := txCIn.valid && txCMerged.ready

  txCMerged.bits.slot := txCIn.bits.slot
  txCMerged.bits.wordOffset := txCIn.bits.wordOffset
  txCMerged.bits.data := txCSramResp.bits

  val txD = DoubleBuffer(txCMerged, jp.cdFB, jp.cdBB)
  
  val txDPacket = Wire(Decoupled(new NetworkWord(params)))

  val txDHeader = Wire(new CacheLineHeader(params))
  txDHeader := 0.U.asTypeOf(new CacheLineHeader(params))
  txDHeader.targetX := io.memletX
  txDHeader.targetY := io.memletY
  txDHeader.sourceX := io.thisX
  txDHeader.sourceY := io.thisY
  txDHeader.sendType := SendType.Single
  txDHeader.messageType := MessageType.WriteLineData
  txDHeader.length := params.cacheSlotWordsPerJamlet.U
  txDHeader.slot := txD.bits.slot

  // Data packets carry the header followed by the SRAM words.

  val stateNext = Wire(JcePacketState())
  val state = RegEnable(stateNext, JcePacketState.Header, txDPacket.fire)
  val txDLastWord = txD.bits.wordOffset === (params.cacheSlotWordsPerJamlet - 1).U

  txDPacket.valid := txD.valid
  txDPacket.bits := DontCare
  txD.ready := txDPacket.ready && (state === JcePacketState.Data)
  stateNext := state

  switch (state) {
    is (JcePacketState.Header) {
      stateNext := JcePacketState.Data
      txDPacket.bits.isHeader := true.B
      txDPacket.bits.data := txDHeader.asUInt
    }
    is (JcePacketState.Data) {
      stateNext := Mux(txDLastWord, JcePacketState.Header, JcePacketState.Data)
      txDPacket.bits.isHeader := false.B
      txDPacket.bits.data := txD.bits.data
    }
  }

  io.packetOut <> DoubleBuffer(txDPacket, jp.packetOutFB, jp.packetOutBB)

  val rxAPacket = DoubleBuffer(io.packetIn, jp.packetInFB, jp.packetInBB)
  val rxAFull = Wire(Decoupled(new JceRxA(params)))
  val rxAOut = Wire(Decoupled(new JceRxA(params)))

  val rxAStateNext = Wire(new JceRxAState(params))
  val rxAStateInitial = Wire(new JceRxAState(params))
  rxAStateInitial := 0.U.asTypeOf(new JceRxAState(params))
  rxAStateInitial.isHeader := true.B
  val rxAState = RegEnable(rxAStateNext, rxAStateInitial, rxAPacket.fire)

  val rxAHeader = rxAPacket.bits.data.asTypeOf(new CacheLineHeader(params))
  val errorsNext = Wire(new JceErrors())
  errorsNext.badRxLength := rxAPacket.valid && rxAState.isHeader &&
    rxAHeader.length =/= params.cacheSlotWordsPerJamlet.U
  errorsNext.badRxMessageType := rxAPacket.valid && rxAState.isHeader &&
    rxAHeader.messageType =/= MessageType.ReadLineResp &&
    rxAHeader.messageType =/= MessageType.WriteLineReadLineResp
  io.errors := RegNext(errorsNext)

  when(rxAState.isHeader) {
    rxAStateNext.slot := rxAHeader.slot
    rxAStateNext.remainingBodyWords := rxAHeader.length
    rxAStateNext.wordOffset := 0.U
    rxAStateNext.isHeader := rxAHeader.length === 0.U
  } .otherwise {
    rxAStateNext.slot := rxAState.slot
    rxAStateNext.remainingBodyWords := rxAState.remainingBodyWords - 1.U
    rxAStateNext.wordOffset := rxAState.wordOffset + 1.U
    rxAStateNext.isHeader := rxAState.remainingBodyWords === 1.U
  }

  rxAFull.valid := rxAPacket.valid && !rxAState.isHeader
  rxAFull.bits.slot := rxAState.slot
  rxAFull.bits.wordOffset := rxAState.wordOffset
  rxAFull.bits.last := rxAState.remainingBodyWords === 1.U
  rxAFull.bits.data := rxAPacket.bits.data
  rxAPacket.ready := Mux(rxAState.isHeader, true.B, rxAFull.ready)

  val rxASramReq = Wire(Decoupled(new SramWriteRequest(params)))

  rxASramReq.valid := rxAFull.valid && rxAOut.ready
  rxAFull.ready := rxASramReq.ready && rxAOut.ready
  rxASramReq.bits.address := Cat(rxAFull.bits.slot, rxAFull.bits.wordOffset)
  rxASramReq.bits.data := rxAFull.bits.data
  io.sramWriteReq <> DoubleBuffer(rxASramReq, jp.sramWriteReqFB, jp.sramWriteReqBB)

  rxAOut.valid := rxAFull.valid && rxASramReq.ready
  rxAOut.bits := rxAFull.bits

  val rxB = DoubleBuffer(rxAOut, jp.rxABFB, jp.rxABBB)

  val rxC = DoubleBuffer(rxB, jp.rxBCFB, jp.rxBCBB)
  val rxCSramResp = DoubleBuffer(io.sramWriteResp, jp.sramWriteRespFB, jp.sramWriteRespBB)

  rxC.ready := rxCSramResp.valid
  rxCSramResp.ready := rxC.valid

  val rxCOpDone = Wire(Valid(params.cacheSlot()))
  rxCOpDone.valid := rxC.fire && rxC.bits.last
  rxCOpDone.bits := rxC.bits.slot

  io.rxDone := ValidBuffer(rxCOpDone)
}

class JceHardMacro(params: ZamletParams) extends ExtModule {
  override val desiredName = "Jce"

  val clock = IO(Input(Clock()))
  val reset = IO(Input(Bool()))
  val io = IO(new JceIO(params))
}

object JceGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> Jce <zamletParamsFileName>")
      null
    } else {
      val params = ZamletParams.fromFile(args(0))
      new Jce(params)
    }
  }
}

object JceMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  JceGenerator.generate(outputDir, Seq(configFile))
}
