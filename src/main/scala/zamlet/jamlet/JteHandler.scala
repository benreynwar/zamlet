package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.utils.DoubleBuffer
import zamlet.utils.ValidBuffer
import zamlet.Ordering
import zamlet.WidthFormat
import zamlet.ElementWidth
import zamlet.LaneOrder
import zamlet.WidthHelpers
import zamlet.Utils
import zamlet.network.{JteHeader, MessageType, NetworkWord, SendType}

  // Receives packets on channel 0 and channel 1
  // Sends packets on channel 0
  //
  // 1) Receives requests to read/write memory
  // 2) Sends response from reading/writing memory
  // 3) Receives the response and updates the register state and the jte state
  //
  // A)  Receive a request on channel 1
  // B)  Check that this identifier is active.  Check if the cache line is active.
  // C)  Wait
  // D)  Get the response back about the identifer. And with the cache location.
  //     If it is not in cache we either send drop response or we quit (the kamlet is tracking this now)
  // E)  Make the request to memory
  // F)  Wait
  // G)  Get the response back from memory.
  // H)  Send the packet response

// We want to find out
// 1) Is this ident active here?
// 2) Where is this cache line in the sram?
class CacheLineRequest(params: ZamletParams) extends Bundle {
  val address = UInt((params.memAddrWidth - params.log2CacheSlotWordsPerJamlet - params.log2JInL).W)
  val payload = new JteHandlerBC(params)
}

object CacheLineState extends ChiselEnum {
  val Dropped = Value
  val StoredInPendingTable = Value
  val Ready = Value
}

class CacheLineResponse(params: ZamletParams) extends Bundle {
  val state = CacheLineState()
  val slot = params.cacheSlot()
}

class SramRequest(params: ZamletParams) extends Bundle {
  val address = UInt(params.sramAddrWidth.W)
  val isWrite = Bool()
  val data = params.word()
  val writeMask = params.word()
}

class JteHandlerAB(params: ZamletParams) extends Bundle {
  val srcX = UInt(8.W)
  val srcY = UInt(8.W)
  val msgType = UInt(params.messageTypeWidth.W)
  val nBytes = UInt((params.log2WordWidth - 3).W)
  val dstOffset = UInt(params.log2WordBytes.W)
  val srcOffset = UInt(params.log2WordBytes.W)
  val ident = params.ident()
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val data = params.word()
  val stripeAddr = UInt((params.memAddrWidth - params.log2JInL).W)
}

class JteHandlerBC(params: ZamletParams) extends Bundle {
  val srcX = UInt(8.W)
  val srcY = UInt(8.W)
  val msgType = UInt(params.messageTypeWidth.W)
  val nBytes = UInt((params.log2WordWidth - 3).W)
  val dstOffset = UInt(params.log2WordBytes.W)
  val srcOffset = UInt(params.log2WordBytes.W)
  val ident = params.ident()
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val data = params.word()
  val cacheLineOffset = UInt(params.log2CacheSlotWordsPerJamlet.W)
}

class JteHandlerReplay(params: ZamletParams) extends Bundle {
  val payload = new JteHandlerBC(params)
  val slot = params.cacheSlot()
}

class JteHandlerAState(params: ZamletParams) extends Bundle {
  val srcX = UInt(8.W)
  val srcY = UInt(8.W)
  val msgType = UInt(params.messageTypeWidth.W)
  val nBytes = UInt((params.log2WordWidth - 3).W)
  val dstOffset = UInt(params.log2WordBytes.W)
  val srcOffset = UInt(params.log2WordBytes.W)
  val ident = params.ident()
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val data = params.word()
  val stripeAddr = UInt((params.memAddrWidth - params.log2JInL).W)
  val remainingBodyWords = UInt(params.messageLengthWidth.W)
  val isHeader = Bool()
}

class JteHandlerAErrors extends Bundle {
  val unexpectedHeader = Bool()
}

class JteHandlerAIO(params: ZamletParams) extends Bundle {
  val packet = Flipped(Decoupled(new NetworkWord(params)))
  val ab = Decoupled(new JteHandlerAB(params))
  val errors = new JteHandlerAErrors()
}

class JteHandlerA(params: ZamletParams) extends Module {

  val io = IO(new JteHandlerAIO(params))

  val fire = io.packet.valid && io.packet.ready

  val stateNext = Wire(new JteHandlerAState(params))
  val stateInitial = Wire(new JteHandlerAState(params))
  stateInitial := 0.U.asTypeOf(new JteHandlerAState(params))
  stateInitial.isHeader := true.B
  val state = RegEnable(stateNext, stateInitial, fire)
  stateNext := state

  val header = Wire(new JteHeader(params))
  header := io.packet.bits.data.asTypeOf(new JteHeader(params))
  when (state.isHeader) {
    stateNext.remainingBodyWords := header.length
  } .otherwise {
    stateNext.remainingBodyWords:= state.remainingBodyWords - 1.U
  }
  io.errors.unexpectedHeader := (state.isHeader =/= io.packet.bits.isHeader) && io.packet.valid
  stateNext.isHeader := stateNext.remainingBodyWords === 0.U

  when (state.isHeader) {
    stateNext.srcX := header.sourceX
    stateNext.srcY := header.sourceY
    stateNext.msgType := header.messageType.asUInt
    stateNext.nBytes := header.nBytes
    stateNext.dstOffset := header.dstOffset
    stateNext.srcOffset := header.srcOffset
    stateNext.ident := header.ident
    stateNext.teIndex := header.slot
  } .elsewhen(stateNext.msgType === MessageType.StoreWordReq.asUInt && stateNext.isHeader) {
    stateNext.data := io.packet.bits.data
  } .otherwise {
    stateNext.stripeAddr := io.packet.bits.data
  }

  io.ab.valid := stateNext.isHeader && io.packet.valid
  io.ab.bits.srcX := stateNext.srcX
  io.ab.bits.srcY := stateNext.srcY
  io.ab.bits.msgType := stateNext.msgType
  io.ab.bits.nBytes := stateNext.nBytes
  io.ab.bits.dstOffset := stateNext.dstOffset
  io.ab.bits.srcOffset := stateNext.srcOffset
  io.ab.bits.ident := stateNext.ident
  io.ab.bits.teIndex := stateNext.teIndex
  io.ab.bits.data := stateNext.data
  io.ab.bits.stripeAddr := stateNext.stripeAddr
  io.packet.ready := io.ab.ready || !stateNext.isHeader
}

class JteHandlerBIO(params: ZamletParams) extends Bundle {
  val ab = Flipped(Decoupled(new JteHandlerAB(params)))
  val bc = Decoupled(new JteHandlerBC(params))
  val cacheLineReq = Decoupled(new CacheLineRequest(params))
}

class JteHandlerB(params: ZamletParams) extends Module {
  val io = IO(new JteHandlerBIO(params))

  val payload = Wire(new JteHandlerBC(params))
  payload.srcX := io.ab.bits.srcX
  payload.srcY := io.ab.bits.srcY
  payload.msgType := io.ab.bits.msgType
  payload.nBytes := io.ab.bits.nBytes
  payload.dstOffset := io.ab.bits.dstOffset
  payload.srcOffset := io.ab.bits.srcOffset
  payload.ident := io.ab.bits.ident
  payload.teIndex := io.ab.bits.teIndex
  payload.data := io.ab.bits.data
  payload.cacheLineOffset := io.ab.bits.stripeAddr(params.log2CacheSlotWordsPerJamlet - 1, 0)

  io.cacheLineReq.valid := io.ab.valid && io.bc.ready
  io.cacheLineReq.bits.address := io.ab.bits.stripeAddr >> params.log2PageWordsPerJamlet
  io.cacheLineReq.bits.payload := payload

  io.bc.valid := io.ab.valid && io.cacheLineReq.ready
  io.bc.bits := payload
  io.ab.ready := io.bc.ready && io.cacheLineReq.ready

}

class JteHandlerCIO(params: ZamletParams) extends Bundle {
  val bc = Flipped(Decoupled(new JteHandlerBC(params)))
  val cd = Decoupled(new JteHandlerBC(params))
}

class JteHandlerC(params: ZamletParams) extends Module {
  val io = IO(new JteHandlerCIO(params))
  io.cd <> io.bc
}

class JteHandlerDE(params: ZamletParams) extends Bundle {
  val srcX = UInt(8.W)
  val srcY = UInt(8.W)
  val msgType = UInt(params.messageTypeWidth.W)
  val nBytes = UInt((params.log2WordWidth - 3).W)
  val dstOffset = UInt(params.log2WordBytes.W)
  val srcOffset = UInt(params.log2WordBytes.W)
  val ident = params.ident()
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val data = params.word()
  val drop = Bool()
  val sramAddr = UInt(params.sramAddrWidth.W)
}

class JteHandlerDIO(params: ZamletParams) extends Bundle {
  val cd = Flipped(Decoupled(new JteHandlerBC(params)))
  val de = Decoupled(new JteHandlerDE(params))
  val cacheLineResp = Flipped(Decoupled(new CacheLineResponse(params)))
  val replay = Flipped(Decoupled(new JteHandlerReplay(params)))
}

class JteHandlerD(params: ZamletParams) extends Module {
  val io = IO(new JteHandlerDIO(params))

  val stateIsStored = io.cacheLineResp.bits.state === CacheLineState.StoredInPendingTable
  val d0UseReplay = io.replay.valid
  val d0ResponseCanProduce = io.cd.valid && io.cacheLineResp.valid && !stateIsStored
  val d0Payload = Mux(d0UseReplay, io.replay.bits.payload, io.cd.bits)
  val d0Slot = Mux(d0UseReplay, io.replay.bits.slot, io.cacheLineResp.bits.slot)

  io.de.valid := d0UseReplay || d0ResponseCanProduce
  io.de.bits.srcX := d0Payload.srcX
  io.de.bits.srcY := d0Payload.srcY
  io.de.bits.msgType := d0Payload.msgType
  io.de.bits.nBytes := d0Payload.nBytes
  io.de.bits.dstOffset := d0Payload.dstOffset
  io.de.bits.srcOffset := d0Payload.srcOffset
  io.de.bits.ident := d0Payload.ident
  io.de.bits.teIndex := d0Payload.teIndex
  io.de.bits.data := d0Payload.data
  io.de.bits.drop := !d0UseReplay && (io.cacheLineResp.bits.state === CacheLineState.Dropped)
  io.de.bits.sramAddr := Cat(d0Slot, d0Payload.cacheLineOffset)

  io.replay.ready := io.de.ready
  io.cd.ready := !d0UseReplay && io.cacheLineResp.valid && (io.de.ready || stateIsStored)
  io.cacheLineResp.ready := !d0UseReplay && io.cd.valid && (io.de.ready || stateIsStored)
}

class JteHandlerEF(params: ZamletParams) extends Bundle {
  val srcX = UInt(8.W)
  val srcY = UInt(8.W)
  val msgType = UInt(params.messageTypeWidth.W)
  val nBytes = UInt((params.log2WordWidth - 3).W)
  val dstOffset = UInt(params.log2WordBytes.W)
  val srcOffset = UInt(params.log2WordBytes.W)
  val ident = params.ident()
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val drop = Bool()
}

class JteHandlerEIO(params: ZamletParams) extends Bundle {
  val de = Flipped(Decoupled(new JteHandlerDE(params)))
  val ef = Decoupled(new JteHandlerEF(params))
  val sramReq = Decoupled(new SramRequest(params))
  val cacheLineRelease = Valid(params.cacheSlot())
}

class JteHandlerE(params: ZamletParams) extends Module {
  val io = IO(new JteHandlerEIO(params))

  val useSram = !io.de.bits.drop

  io.sramReq.valid := io.de.valid && io.ef.ready && useSram
  io.sramReq.bits.address := io.de.bits.sramAddr
  io.sramReq.bits.isWrite := io.de.bits.msgType === MessageType.StoreWordReq.asUInt
  io.sramReq.bits.data := io.de.bits.data
  io.sramReq.bits.writeMask := Fill(params.wordWidth, true.B)

  io.ef.valid := io.de.valid && (!useSram || io.sramReq.ready)
  io.ef.bits.srcX := io.de.bits.srcX
  io.ef.bits.srcY := io.de.bits.srcY
  io.ef.bits.msgType := io.de.bits.msgType
  io.ef.bits.nBytes := io.de.bits.nBytes
  io.ef.bits.dstOffset := io.de.bits.dstOffset
  io.ef.bits.srcOffset := io.de.bits.srcOffset
  io.ef.bits.ident := io.de.bits.ident
  io.ef.bits.teIndex := io.de.bits.teIndex
  io.ef.bits.drop := io.de.bits.drop

  io.de.ready := io.ef.ready && (!useSram || io.sramReq.ready)

  io.cacheLineRelease.valid := io.de.fire && useSram
  io.cacheLineRelease.bits := io.de.bits.sramAddr(params.sramAddrWidth - 1, params.log2CacheSlotWordsPerJamlet)
}

class JteHandlerFIO(params: ZamletParams) extends Bundle {
  val ef = Flipped(Decoupled(new JteHandlerEF(params)))
  val fg = Decoupled(new JteHandlerEF(params))
}

class JteHandlerF(params: ZamletParams) extends Module {
  val io = IO(new JteHandlerFIO(params))
  io.fg <> io.ef
}

class JteHandlerGH(params: ZamletParams) extends Bundle {
  val srcX = UInt(8.W)
  val srcY = UInt(8.W)
  val msgType = UInt(params.messageTypeWidth.W)
  val nBytes = UInt((params.log2WordWidth - 3).W)
  val dstOffset = UInt(params.log2WordBytes.W)
  val srcOffset = UInt(params.log2WordBytes.W)
  val ident = params.ident()
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val drop = Bool()
  val data = params.word()
}

class JteHandlerGIO(params: ZamletParams) extends Bundle {
  val fg = Flipped(Decoupled(new JteHandlerEF(params)))
  val gh = Decoupled(new JteHandlerGH(params))
  val sramResp = Flipped(Decoupled(params.word()))
}

class JteHandlerG(params: ZamletParams) extends Module {
  val io = IO(new JteHandlerGIO(params))

  val needsSramResp = !io.fg.bits.drop

  io.gh.valid := io.fg.valid && (!needsSramResp || io.sramResp.valid)
  io.gh.bits.srcX := io.fg.bits.srcX
  io.gh.bits.srcY := io.fg.bits.srcY
  io.gh.bits.msgType := io.fg.bits.msgType
  io.gh.bits.nBytes := io.fg.bits.nBytes
  io.gh.bits.dstOffset := io.fg.bits.dstOffset
  io.gh.bits.srcOffset := io.fg.bits.srcOffset
  io.gh.bits.ident := io.fg.bits.ident
  io.gh.bits.teIndex := io.fg.bits.teIndex
  io.gh.bits.drop := io.fg.bits.drop
  io.gh.bits.data := io.sramResp.bits

  io.fg.ready := io.gh.ready && (!needsSramResp || io.sramResp.valid)
  io.sramResp.ready := io.fg.valid && needsSramResp && io.gh.ready
}

class JteHandlerHIO(params: ZamletParams) extends Bundle {
  val gh = Flipped(Decoupled(new JteHandlerGH(params)))
  val packet = Decoupled(new NetworkWord(params))
  val x = Input(UInt(params.xPosWidth.W))
  val y = Input(UInt(params.yPosWidth.W))
}

class JteHandlerH(params: ZamletParams) extends Module {
  val io = IO(new JteHandlerHIO(params))

  val sendData = !io.gh.bits.drop && io.gh.bits.msgType === MessageType.LoadWordReq.asUInt
  val msgIndex = RegInit(0.U(1.W))
  val completeMessage = !sendData || msgIndex === 1.U

  val header = Wire(new JteHeader(params))
  header := 0.U.asTypeOf(new JteHeader(params))
  header.targetX := io.gh.bits.srcX
  header.targetY := io.gh.bits.srcY
  header.sourceX := io.x
  header.sourceY := io.y
  header.sendType := SendType.Single
  when (io.gh.bits.msgType === MessageType.LoadWordReq.asUInt) {
    header.messageType := Mux(io.gh.bits.drop, MessageType.LoadWordDrop, MessageType.LoadWordResp)
  } .otherwise {
    header.messageType := Mux(io.gh.bits.drop, MessageType.StoreWordDrop, MessageType.StoreWordResp)
  }
  header.length := Mux(sendData, 1.U, 0.U)
  header.nBytes := io.gh.bits.nBytes
  header.dstOffset := io.gh.bits.dstOffset
  header.srcOffset := io.gh.bits.srcOffset
  header.ident := io.gh.bits.ident
  header.slot := io.gh.bits.teIndex

  io.packet.valid := io.gh.valid
  io.packet.bits.isHeader := msgIndex === 0.U
  io.packet.bits.data := Mux(msgIndex === 0.U, header.asUInt, io.gh.bits.data)
  io.gh.ready := io.packet.ready && completeMessage

  when (io.packet.fire) {
    msgIndex := Mux(completeMessage, 0.U, msgIndex + 1.U)
  }
}

class JteHandlerIO(params: ZamletParams) extends Bundle {
  val packetIn = Flipped(Decoupled(new NetworkWord(params)))
  val packetOut = Decoupled(new NetworkWord(params))
  val x = Input(UInt(params.xPosWidth.W))
  val y = Input(UInt(params.yPosWidth.W))
  val cacheLineReq = Decoupled(new CacheLineRequest(params))
  val cacheLineResp = Flipped(Decoupled(new CacheLineResponse(params)))
  val cacheLineReplay = Flipped(Decoupled(new JteHandlerReplay(params)))
  val cacheLineRelease = Valid(params.cacheSlot())
  val sramReq = Decoupled(new SramRequest(params))
  val sramResp = Flipped(Decoupled(params.word()))
}

class JteHandler(params: ZamletParams) extends Module {
  val io = IO(new JteHandlerIO(params))
  val hp = params.jteHandlerParams

  val aStage = Module(new JteHandlerA(params))
  aStage.io.packet <> DoubleBuffer(io.packetIn, hp.packetInFB, hp.packetInBB)

  val bStage = Module(new JteHandlerB(params))
  bStage.io.ab <> DoubleBuffer(aStage.io.ab, hp.abFB, hp.abBB)
  io.cacheLineReq <> DoubleBuffer(bStage.io.cacheLineReq, hp.cacheLineReqFB, hp.cacheLineReqBB)

  val cStage = Module(new JteHandlerC(params))
  cStage.io.bc <> DoubleBuffer(bStage.io.bc, hp.bcFB, hp.bcBB)

  val dStage = Module(new JteHandlerD(params))
  dStage.io.cd <> DoubleBuffer(cStage.io.cd, hp.cdFB, hp.cdBB)
  dStage.io.cacheLineResp <> DoubleBuffer(io.cacheLineResp, hp.cacheLineRespFB, hp.cacheLineRespBB)
  dStage.io.replay <> io.cacheLineReplay

  val eStage = Module(new JteHandlerE(params))
  eStage.io.de <> DoubleBuffer(dStage.io.de, hp.deFB, hp.deBB)
  io.sramReq <> DoubleBuffer(eStage.io.sramReq, hp.sramReqFB, hp.sramReqBB)
  io.cacheLineRelease := eStage.io.cacheLineRelease

  val fStage = Module(new JteHandlerF(params))
  fStage.io.ef <> DoubleBuffer(eStage.io.ef, hp.efFB, hp.efBB)

  val gStage = Module(new JteHandlerG(params))
  gStage.io.fg <> DoubleBuffer(fStage.io.fg, hp.fgFB, hp.fgBB)
  gStage.io.sramResp <> DoubleBuffer(io.sramResp, hp.sramRespFB, hp.sramRespBB)

  val hStage = Module(new JteHandlerH(params))
  hStage.io.gh <> DoubleBuffer(gStage.io.gh, hp.ghFB, hp.ghBB)
  hStage.io.x := RegNext(io.x)
  hStage.io.y := RegNext(io.y)
  io.packetOut <> DoubleBuffer(hStage.io.packet, hp.packetOutFB, hp.packetOutBB)
}


object JteHandlerGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    val params = ZamletParams.fromFile(args(0))
    new JteHandler(params)
  }
}

object JteHandlerMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  JteHandlerGenerator.generate(args(0), Seq(args(1)))
}

object JteHandlerStageMain extends App {
  if (args.length < 3) {
    println("Usage: <outputDir> <configFile> <stage>")
    System.exit(1)
  }

  val stage = args(2)
  val generator = new zamlet.ModuleGenerator {
    override def makeModule(args: Seq[String]): Module = {
      val params = ZamletParams.fromFile(args(0))
      stage match {
        case "A" => new JteHandlerA(params)
        case "B" => new JteHandlerB(params)
        case "C" => new JteHandlerC(params)
        case "D" => new JteHandlerD(params)
        case "E" => new JteHandlerE(params)
        case "F" => new JteHandlerF(params)
        case "G" => new JteHandlerG(params)
        case "H" => new JteHandlerH(params)
        case _ => throw new IllegalArgumentException(s"Unknown JTE handler stage: $stage")
      }
    }
  }

  generator.generate(args(0), Seq(args(1)))
}
