package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.network.{INetworkWord, NetworkWord}

class JteIO(params: ZamletParams) extends Bundle {
  val laneIndex = Input(UInt(params.log2JInL.W))
  val x = Input(UInt(8.W))
  val y = Input(UInt(8.W))

  val create = Flipped(Valid(new JteCreate(params)))
  val clear = Flipped(Valid(UInt(log2Ceil(params.witemTableDepth).W)))
  val inputReq = Decoupled(UInt(log2Ceil(params.witemTableDepth).W))
  val inputResp = Flipped(Decoupled(new JteInitiatorInput(params)))
  val transferComplete = Output(Vec(params.witemTableDepth, Bool()))
  val errors = Output(new JteStateErrors())

  val channel0In = Flipped(Decoupled(new NetworkWord(params)))
  val channel1In = Flipped(Decoupled(new NetworkWord(params)))
  val channel0Out = Decoupled(new NetworkWord(params))
  val channel1Out = Decoupled(new INetworkWord(params))

  val rfMaskReq = Decoupled(params.rfAddr())
  val rfMaskResp = Flipped(Decoupled(params.word()))
  val rfIndexReq = Decoupled(params.rfAddr())
  val rfIndexResp = Flipped(Decoupled(params.word()))
  val rfDataReq = Decoupled(params.rfAddr())
  val rfDataResp = Flipped(Decoupled(params.word()))
  val rfWriteReq = Decoupled(new RFWriteReq(params))
  val rfWriteResp = Flipped(Decoupled(Bool()))

  val tlbReq = Decoupled(new JamletTlbReq(params))
  val tlbResp = Flipped(Decoupled(new JamletTlbResp(params)))
  val tlbAvailable = Flipped(Valid(new JamletTlbAvailable(params)))

  val cacheLineReq = Decoupled(new CacheLineRequest(params))
  val cacheLineResp = Flipped(Decoupled(new CacheLineResponse(params)))
  val cacheLineReplay = Flipped(Decoupled(new JteHandlerReplay(params)))
  val cacheLineRelease = Valid(params.cacheSlot())
  val sramReq = Decoupled(new SramRequest(params))
  val sramResp = Flipped(Decoupled(params.word()))
}

class Jte(params: ZamletParams) extends Module {
  val io = IO(new JteIO(params))

  val state = Module(new JteState(params))
  val initiator = Module(new JteInitiator(params))
  val receiver = Module(new JteReceiver(params))
  val handler = Module(new JteHandler(params))

  state.io.create <> io.create
  state.io.clear <> io.clear
  io.inputReq <> state.io.inputReq
  state.io.inputResp <> io.inputResp
  io.transferComplete := state.io.transferComplete
  io.errors := state.io.errors

  initiator.io.laneIndex := io.laneIndex
  initiator.io.x := io.x
  initiator.io.y := io.y
  initiator.io.input <> state.io.initiatorDispatch
  state.io.initiatorCommit <> initiator.io.commit
  io.channel1Out <> initiator.io.packet
  io.rfMaskReq <> initiator.io.rfMaskReq
  initiator.io.rfMaskResp <> io.rfMaskResp
  io.rfIndexReq <> initiator.io.rfIndexReq
  initiator.io.rfIndexResp <> io.rfIndexResp
  io.rfDataReq <> initiator.io.rfDataReq
  initiator.io.rfDataResp <> io.rfDataResp
  io.tlbReq <> initiator.io.tlbReq
  initiator.io.tlbResp <> io.tlbResp
  state.io.tlbAvailable <> io.tlbAvailable

  receiver.io.packet <> io.channel0In
  private val slotToRegLookupHasBuffer =
    params.jteReceiverParams.slotToRegReqFB ||
      params.jteReceiverParams.slotToRegReqBB ||
      params.jteReceiverParams.slotToRegRespFB ||
      params.jteReceiverParams.slotToRegRespBB ||
      params.jteStateParams.slotToRegReqFB ||
      params.jteStateParams.slotToRegReqBB ||
      params.jteStateParams.slotToRegRespFB ||
      params.jteStateParams.slotToRegRespBB
  require(
    slotToRegLookupHasBuffer,
    "JTE receiver/state slot-to-reg lookup requires a buffer on the request/response cycle")
  receiver.io.teIndexToRegReq <> state.io.teIndexToRegReq
  state.io.teIndexToRegResp <> receiver.io.teIndexToRegResp
  io.rfWriteReq <> receiver.io.rfWriteReq
  receiver.io.rfWriteResp <> io.rfWriteResp
  state.io.receiverUpdate <> receiver.io.updateMsg

  handler.io.packetIn <> io.channel1In
  handler.io.x := io.x
  handler.io.y := io.y
  io.channel0Out <> handler.io.packetOut
  io.cacheLineReq <> handler.io.cacheLineReq
  handler.io.cacheLineResp <> io.cacheLineResp
  handler.io.cacheLineReplay <> io.cacheLineReplay
  io.cacheLineRelease := handler.io.cacheLineRelease
  io.sramReq <> handler.io.sramReq
  handler.io.sramResp <> io.sramResp
}

object JteGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    val params = ZamletParams.fromFile(args(0))
    new Jte(params)
  }
}

object JteMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  JteGenerator.generate(args(0), Seq(args(1)))
}
