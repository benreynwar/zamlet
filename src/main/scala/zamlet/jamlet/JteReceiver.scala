package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.utils.DoubleBuffer

  // Receives packets on channel 0
  //
  // A) Receives a response or drop packet.
  // B) Sends a write to RF is needed.
  // C) Wait
  // D) Get response. send a message to the jte state machine.

class RFWriteReq(params: ZamletParams) extends Bundle {
  val address = params.rfAddr()
  val data = params.word()
  val byteMask = UInt(params.wordBytes.W)
}


class JteReceiverUpdateMsg(params: ZamletParams) extends Bundle {
  val slot = UInt(log2Ceil(params.witemTableDepth).W)
  val ident = params.ident()
  val msgType = UInt(params.messageTypeWidth.W)
  val offset = UInt(params.log2WordBytes.W)
  val drop = Bool()
}

class JteReceiverAB(params: ZamletParams) extends Bundle {
  val slot = UInt(log2Ceil(params.witemTableDepth).W)
  val ident = params.ident()
  val msgType = UInt(params.messageTypeWidth.W)
  val nBytes = UInt((params.log2WordWidth - 3).W)
  val dstOffset = UInt(params.log2WordBytes.W)
  val srcOffset = UInt(params.log2WordBytes.W)
  val data = params.word()
}

class JteReceiverBC(params: ZamletParams) extends Bundle {
  val slot = UInt(log2Ceil(params.witemTableDepth).W)
  val ident = params.ident()
  val msgType = UInt(params.messageTypeWidth.W)
  val nBytes = UInt((params.log2WordWidth - 3).W)
  val srcOffset = UInt(params.log2WordBytes.W)
  val wroteRf = Bool()
  val drop = Bool()
}

class JteReceiverAState(params: ZamletParams) extends Bundle {
  val msgType = UInt(params.messageTypeWidth.W)
  val nBytes = UInt((params.log2WordWidth - 3).W)
  val dstOffset = UInt(params.log2WordBytes.W)
  val srcOffset = UInt(params.log2WordBytes.W)
  val slot = UInt(log2Ceil(params.witemTableDepth).W)
  val ident = params.ident()
  val data = params.word()
  val remainingBodyWords = UInt(params.messageLengthWidth.W)
  val isHeader = Bool()
}

class JteReceiverAErrors extends Bundle {
  val unexpectedHeader = Bool()
}

class JteReceiverAIO(params: ZamletParams) extends Bundle {
  val packet = Flipped(Decoupled(new WithHeader(params)))
  val ab = Decoupled(new JteReceiverAB(params))
  val slotToRegReq = Decoupled(UInt(log2Ceil(params.witemTableDepth).W))
  val errors = new JteReceiverAErrors()
}

class JteReceiverA(params: ZamletParams) extends Module {

  val io = IO(new JteReceiverAIO(params))

  val fire = io.packet.valid && io.packet.ready

  val stateNext = Wire(new JteReceiverAState(params))
  val stateInitial = Wire(new JteReceiverAState(params))
  stateInitial := 0.U.asTypeOf(new JteReceiverAState(params))
  stateInitial.isHeader := true.B
  val state = RegEnable(stateNext, stateInitial, fire)
  stateNext := state

  val header = Wire(new Header(params))
  header := io.packet.bits.bits.asTypeOf(new Header(params))
  when (state.isHeader) {
    stateNext.remainingBodyWords := header.msgLength
  } .otherwise {
    stateNext.remainingBodyWords:= state.remainingBodyWords - 1.U
  }
  io.errors.unexpectedHeader := (state.isHeader =/= io.packet.bits.isHeader) && io.packet.valid
  stateNext.isHeader := stateNext.remainingBodyWords === 0.U

  when (state.isHeader) {
    stateNext.msgType := header.msgType
    stateNext.nBytes := header.nBytes
    stateNext.dstOffset := header.dstOffset
    stateNext.srcOffset := header.srcOffset
    stateNext.slot := header.slot
    stateNext.ident := header.ident
  } .otherwise {
    stateNext.data := io.packet.bits.bits
  }

  io.slotToRegReq.valid := stateNext.isHeader && io.packet.valid && io.ab.ready
  io.slotToRegReq.bits := stateNext.slot

  io.ab.valid := stateNext.isHeader && io.packet.valid && io.slotToRegReq.ready
  io.ab.bits.slot := stateNext.slot
  io.ab.bits.msgType := stateNext.msgType
  io.ab.bits.nBytes := stateNext.nBytes
  io.ab.bits.dstOffset := stateNext.dstOffset
  io.ab.bits.srcOffset := stateNext.srcOffset
  io.ab.bits.ident := stateNext.ident
  io.ab.bits.data := stateNext.data
  io.packet.ready := (io.ab.ready && io.slotToRegReq.ready) || !stateNext.isHeader
}

class JteReceiverBIO(params: ZamletParams) extends Bundle {
  val ab = Flipped(Decoupled(new JteReceiverAB(params)))
  val bc = Decoupled(new JteReceiverBC(params))
  val slotToRegResp = Flipped(Decoupled(params.rfAddr()))
  val rfWriteReq = Decoupled(new RFWriteReq(params))
}

class JteReceiverB(params: ZamletParams) extends Module {
  val io = IO(new JteReceiverBIO(params))

  val writeRf = io.ab.bits.msgType === MessageTypes.READ_RESPONSE.U
  val byteCount = Mux(io.ab.bits.nBytes === 0.U, params.wordBytes.U, io.ab.bits.nBytes)
  val srcAfterDst = io.ab.bits.srcOffset >= io.ab.bits.dstOffset
  val offsetDiff = Mux(srcAfterDst, io.ab.bits.srcOffset - io.ab.bits.dstOffset, io.ab.bits.dstOffset - io.ab.bits.srcOffset)
  val writeData = Mux(
    srcAfterDst,
    io.ab.bits.data << (offsetDiff << 3.U),
    io.ab.bits.data >> (offsetDiff << 3.U),
  )
  val writeMask = (((1.U((params.wordBytes + 1).W) << byteCount) - 1.U)(params.wordBytes - 1, 0) <<
    io.ab.bits.srcOffset)(params.wordBytes - 1, 0)

  io.rfWriteReq.valid := io.ab.valid && io.bc.ready && io.slotToRegResp.valid && writeRf
  io.rfWriteReq.bits.address := io.slotToRegResp.bits
  io.rfWriteReq.bits.data := writeData
  io.rfWriteReq.bits.byteMask := writeMask

  io.bc.valid := io.ab.valid && io.slotToRegResp.valid && (!writeRf || io.rfWriteReq.ready)
  io.bc.bits.slot := io.ab.bits.slot
  io.bc.bits.ident := io.ab.bits.ident
  io.bc.bits.msgType := io.ab.bits.msgType
  io.bc.bits.nBytes := io.ab.bits.nBytes
  io.bc.bits.srcOffset := io.ab.bits.srcOffset
  io.bc.bits.wroteRf := writeRf
  io.bc.bits.drop := io.ab.bits.msgType === MessageTypes.READ_DROP.U || io.ab.bits.msgType === MessageTypes.WRITE_DROP.U
  io.ab.ready := io.bc.ready && io.slotToRegResp.valid && (!writeRf || io.rfWriteReq.ready)
  io.slotToRegResp.ready := io.ab.valid && io.bc.ready && (!writeRf || io.rfWriteReq.ready)
}

class JteReceiverCIO(params: ZamletParams) extends Bundle {
  val bc = Flipped(Decoupled(new JteReceiverBC(params)))
  val cd = Decoupled(new JteReceiverBC(params))
  val rfWriteResp = Flipped(Decoupled(Bool()))
}

class JteReceiverC(params: ZamletParams) extends Module {
  val io = IO(new JteReceiverCIO(params))

  val waitForRfWrite = io.bc.bits.wroteRf
  io.cd.valid := io.bc.valid && (!waitForRfWrite || io.rfWriteResp.valid)
  io.cd.bits := io.bc.bits
  io.bc.ready := io.cd.ready && (!waitForRfWrite || io.rfWriteResp.valid)
  io.rfWriteResp.ready := io.bc.valid && waitForRfWrite && io.cd.ready
}

class JteReceiverDIO(params: ZamletParams) extends Bundle {
  val cd = Flipped(Decoupled(new JteReceiverBC(params)))
  val updateMsg = Decoupled(new JteReceiverUpdateMsg(params))
}

class JteReceiverD(params: ZamletParams) extends Module {
  val io = IO(new JteReceiverDIO(params))

  io.updateMsg.valid := io.cd.valid
  io.updateMsg.bits.slot := io.cd.bits.slot
  io.updateMsg.bits.ident := io.cd.bits.ident
  io.updateMsg.bits.msgType := io.cd.bits.msgType
  io.updateMsg.bits.offset := io.cd.bits.srcOffset
  io.updateMsg.bits.drop := io.cd.bits.drop
  io.cd.ready := io.updateMsg.ready
}

class JteReceiverIO(params: ZamletParams) extends Bundle {
  val packet = Flipped(Decoupled(new WithHeader(params)))
  val slotToRegReq = Decoupled(UInt(log2Ceil(params.witemTableDepth).W))
  val slotToRegResp = Flipped(Decoupled(params.rfAddr()))
  val rfWriteReq = Decoupled(new RFWriteReq(params))
  val rfWriteResp = Flipped(Decoupled(Bool()))
  val updateMsg = Decoupled(new JteReceiverUpdateMsg(params))
}

class JteReceiver(params: ZamletParams) extends Module {
  val io = IO(new JteReceiverIO(params))
  val rp = params.jteReceiverParams

  val aStage = Module(new JteReceiverA(params))
  aStage.io.packet <> DoubleBuffer(io.packet, rp.packetFB, rp.packetBB)
  io.slotToRegReq <> DoubleBuffer(aStage.io.slotToRegReq, rp.slotToRegReqFB, rp.slotToRegReqBB)

  val bStage = Module(new JteReceiverB(params))
  bStage.io.ab <> DoubleBuffer(aStage.io.ab, rp.abFB, rp.abBB)
  bStage.io.slotToRegResp <> DoubleBuffer(io.slotToRegResp, rp.slotToRegRespFB, rp.slotToRegRespBB)
  io.rfWriteReq <> DoubleBuffer(bStage.io.rfWriteReq, rp.rfWriteReqFB, rp.rfWriteReqBB)

  val cStage = Module(new JteReceiverC(params))
  cStage.io.bc <> DoubleBuffer(bStage.io.bc, rp.bcFB, rp.bcBB)
  cStage.io.rfWriteResp <> DoubleBuffer(io.rfWriteResp, rp.rfWriteRespFB, rp.rfWriteRespBB)

  val dStage = Module(new JteReceiverD(params))
  dStage.io.cd <> DoubleBuffer(cStage.io.cd, rp.cdFB, rp.cdBB)
  io.updateMsg <> DoubleBuffer(dStage.io.updateMsg, rp.updateMsgFB, rp.updateMsgBB)
}


object JteReceiverGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    val params = ZamletParams.fromFile(args(0))
    new JteReceiver(params)
  }
}

object JteReceiverMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  JteReceiverGenerator.generate(args(0), Seq(args(1)))
}

object JteReceiverStageMain extends App {
  if (args.length < 3) {
    println("Usage: <outputDir> <configFile> <stage>")
    System.exit(1)
  }

  val stage = args(2)
  val generator = new zamlet.ModuleGenerator {
    override def makeModule(args: Seq[String]): Module = {
      val params = ZamletParams.fromFile(args(0))
      stage match {
        case "A" => new JteReceiverA(params)
        case "B" => new JteReceiverB(params)
        case "C" => new JteReceiverC(params)
        case "D" => new JteReceiverD(params)
        case _ => throw new IllegalArgumentException(s"Unknown JTE receiver stage: $stage")
      }
    }
  }

  generator.generate(args(0), Seq(args(1)))
}
