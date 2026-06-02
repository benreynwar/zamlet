package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.LaneOrder
import zamlet.ZamletParams
import zamlet.network.{CombinedNetworkNode, NetworkWord, PacketArbiter, MessageType}

/** Network channels IO - Vec of channels for each direction */
class ChannelsIO(params: ZamletParams, nChannels: Int) extends Bundle {
  val ni = Vec(nChannels, Flipped(Decoupled(new NetworkWord(params))))
  val no = Vec(nChannels, Decoupled(new NetworkWord(params)))
  val si = Vec(nChannels, Flipped(Decoupled(new NetworkWord(params))))
  val so = Vec(nChannels, Decoupled(new NetworkWord(params)))
  val ei = Vec(nChannels, Flipped(Decoupled(new NetworkWord(params))))
  val eo = Vec(nChannels, Decoupled(new NetworkWord(params)))
  val wi = Vec(nChannels, Flipped(Decoupled(new NetworkWord(params))))
  val wo = Vec(nChannels, Decoupled(new NetworkWord(params)))
}


/** Command to send cache line data */
class SendCacheLineCmd(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
}

class JamletErrors extends Bundle {
  val jte = new JteStateErrors()
  val jce = new JceErrors()
  val localExec = new LocalExecErrors()
  val aHoRouter = new PacketRouterErrors()
}

/**
 * Jamlet - Single lane of the VPU
 *
 * Contains routers, SRAM, register file slice, and witem processing logic.
 */
class Jamlet(params: ZamletParams) extends Module {
  val io = IO(new Bundle {
    // Position
    val thisX = Input(params.xPos())
    val thisY = Input(params.yPos())
    val memletX = Input(params.xPos())
    val memletY = Input(params.yPos())
    val laneIndices = Input(Vec(LaneOrder.count, UInt(params.log2JInL.W)))

    // A channels (always-consumable responses)
    val aChannels = new ChannelsIO(params, params.nAChannels)

    // B channels (requests)
    val bChannels = new ChannelsIO(params, params.nBChannels)

    // JTE interface (from/to KTE)
    val jteCreate = Flipped(Valid(new JteCreate(params)))
    val jteClear = Flipped(Valid(UInt(log2Ceil(params.witemTableDepth).W)))
    val jteInputReq = Decoupled(UInt(log2Ceil(params.witemTableDepth).W))
    val jteInputResp = Flipped(Decoupled(new JteInitiatorInput(params)))
    val transferComplete = Output(Vec(params.witemTableDepth, Bool()))
    val errors = Output(new JamletErrors())
    val tlbReq = Decoupled(UInt(params.memStripeAddrWidth.W))
    val tlbResp = Flipped(Decoupled(new JamletTlbResp(params)))
    val cacheLineReq = Decoupled(new CacheLineRequest(params))
    val cacheLineResp = Flipped(Decoupled(new CacheLineResponse(params)))

    // Immediate kinstr execution (from kamlet) - for LoadImm, ALU ops, etc.
    val immediateKinstr = Flipped(Valid(new KinstrWithParams(params)))

    // Cache line interface (from kamlet)
    val sendCacheLine = Flipped(Valid(new SendCacheLineCmd(params)))
    val cacheResponse = Valid(params.cacheSlot())

  })

  // ============================================================
  // Submodules
  // ============================================================

  val combinedNetworkNode = Module(new CombinedNetworkNode(params))

  val sram = Module(new Sram(params))
  val rfSlice = Module(new RfSlice(params))
  val jte = Module(new Jte(params))
  val jce = Module(new Jce(params))
  val localExec = Module(new LocalExec(params))
  val bArbiter = Module(new PacketArbiter(params, 2))  // JTE Ch1 + JCE
  // val alu = Module(new ALU(params))

  // ============================================================
  // Connections
  // ============================================================

  // --- Combined network node connections ---
  combinedNetworkNode.io.thisX := io.thisX
  combinedNetworkNode.io.thisY := io.thisY

  // A channel connections
  combinedNetworkNode.io.aNi <> io.aChannels.ni
  combinedNetworkNode.io.aNo <> io.aChannels.no
  combinedNetworkNode.io.aSi <> io.aChannels.si
  combinedNetworkNode.io.aSo <> io.aChannels.so
  combinedNetworkNode.io.aEi <> io.aChannels.ei
  combinedNetworkNode.io.aEo <> io.aChannels.eo
  combinedNetworkNode.io.aWi <> io.aChannels.wi
  combinedNetworkNode.io.aWo <> io.aChannels.wo

  // B channel connections
  combinedNetworkNode.io.bNi <> io.bChannels.ni
  combinedNetworkNode.io.bNo <> io.bChannels.no
  combinedNetworkNode.io.bSi <> io.bChannels.si
  combinedNetworkNode.io.bSo <> io.bChannels.so
  combinedNetworkNode.io.bEi <> io.bChannels.ei
  combinedNetworkNode.io.bEo <> io.bChannels.eo
  combinedNetworkNode.io.bWi <> io.bChannels.wi
  combinedNetworkNode.io.bWo <> io.bChannels.wo

  // ============================================================
  // Local port handling
  // ============================================================

  val aHoRouter = Module(new PacketRouter(params, Seq(
    Seq(MessageType.ReadLineResp, MessageType.WriteLineReadLineResp),
    Seq(
      MessageType.Send,
      MessageType.WriteLineResp,
      MessageType.LoadJ2JWordsResp,
      MessageType.LoadJ2JWordsDrop,
      MessageType.LoadJ2JWordsRetry,
      MessageType.StoreJ2JWordsResp,
      MessageType.StoreJ2JWordsDrop,
      MessageType.StoreJ2JWordsRetry,
      MessageType.LoadWordResp,
      MessageType.LoadWordDrop,
      MessageType.LoadWordRetry,
      MessageType.StoreWordResp,
      MessageType.StoreWordDrop,
      MessageType.StoreWordRetry,
      MessageType.ReadMemWordResp,
      MessageType.ReadMemWordDrop,
      MessageType.WriteMemWordResp,
      MessageType.WriteMemWordDrop,
      MessageType.WriteMemWordRetry,
      MessageType.IdentQueryResp,
      MessageType.LoadIndexedElementResp,
      MessageType.StoreIndexedElementResp),
  )))
  aHoRouter.io.in <> combinedNetworkNode.io.aHo

  val jteChannel0In = Wire(Decoupled(new NetworkWord(params)))
  jte.io.channel0In <> jteChannel0In
  jteChannel0In <> aHoRouter.io.out(1)

  jce.io.packetIn <> aHoRouter.io.out(0)

  // Ch0 local input: JTE responses/acks.
  combinedNetworkNode.io.aHi <> jte.io.channel0Out

  // B channel local ports
  // hi: arbiter output -> network
  combinedNetworkNode.io.bHi <> bArbiter.io.out
  // ho: network -> JTE request handler.
  jte.io.channel1In <> combinedNetworkNode.io.bHo

  // --- SRAM connections ---
  sram.io.jteReq <> jte.io.sramReq
  jte.io.sramResp <> sram.io.jteResp
  sram.io.jceReadReq <> jce.io.sramReadReq
  jce.io.sramReadResp <> sram.io.jceReadResp
  sram.io.jceWriteReq <> jce.io.sramWriteReq
  jce.io.sramWriteResp <> sram.io.jceWriteResp
  sram.io.localReq <> localExec.io.sramReq
  localExec.io.sramResp <> sram.io.localResp

  // --- RfSlice connections ---
  rfSlice.io.maskReq.valid := jte.io.rfMaskReq.valid
  rfSlice.io.maskReq.bits.addr := jte.io.rfMaskReq.bits
  rfSlice.io.maskReq.bits.isWrite := false.B
  rfSlice.io.maskReq.bits.writeData := DontCare
  rfSlice.io.maskReq.bits.writeMask := DontCare
  jte.io.rfMaskReq.ready := rfSlice.io.maskReq.ready
  jte.io.rfMaskResp.valid := rfSlice.io.maskResp.valid
  jte.io.rfMaskResp.bits := rfSlice.io.maskResp.bits.readData
  rfSlice.io.maskResp.ready := jte.io.rfMaskResp.ready

  rfSlice.io.indexReq.valid := jte.io.rfIndexReq.valid
  rfSlice.io.indexReq.bits.addr := jte.io.rfIndexReq.bits
  rfSlice.io.indexReq.bits.isWrite := false.B
  rfSlice.io.indexReq.bits.writeData := DontCare
  rfSlice.io.indexReq.bits.writeMask := DontCare
  jte.io.rfIndexReq.ready := rfSlice.io.indexReq.ready
  jte.io.rfIndexResp.valid := rfSlice.io.indexResp.valid
  jte.io.rfIndexResp.bits := rfSlice.io.indexResp.bits.readData
  rfSlice.io.indexResp.ready := jte.io.rfIndexResp.ready

  rfSlice.io.dataReq.valid := jte.io.rfDataReq.valid
  rfSlice.io.dataReq.bits.addr := jte.io.rfDataReq.bits
  rfSlice.io.dataReq.bits.isWrite := false.B
  rfSlice.io.dataReq.bits.writeData := DontCare
  rfSlice.io.dataReq.bits.writeMask := DontCare
  jte.io.rfDataReq.ready := rfSlice.io.dataReq.ready
  jte.io.rfDataResp.valid := rfSlice.io.dataResp.valid
  jte.io.rfDataResp.bits := rfSlice.io.dataResp.bits.readData
  rfSlice.io.dataResp.ready := jte.io.rfDataResp.ready

  // LocalExec connections
  localExec.io.laneIndex := io.laneIndices(io.immediateKinstr.bits.ordering.laneOrder.asUInt)
  localExec.io.kinstrIn := io.immediateKinstr
  rfSlice.io.localExecReadAReq <> localExec.io.rfReadAReq
  localExec.io.rfReadAResp <> rfSlice.io.localExecReadAResp
  rfSlice.io.localExecReadBReq <> localExec.io.rfReadBReq
  localExec.io.rfReadBResp <> rfSlice.io.localExecReadBResp
  rfSlice.io.localExecReadMaskReq <> localExec.io.rfReadMaskReq
  localExec.io.rfReadMaskResp <> rfSlice.io.localExecReadMaskResp
  rfSlice.io.localExecWriteReq <> localExec.io.rfWriteReq

  // B channel arbiter inputs: JTE Ch1 requests + JCE
  val jteChannel1Out = Module(new INetworkWordToNetworkWord(params))
  jteChannel1Out.io.in <> jte.io.channel1Out
  bArbiter.io.in(0) <> jteChannel1Out.io.out
  bArbiter.io.in(1) <> jce.io.packetOut

  // JCE connections
  jce.io.memletX := io.memletX
  jce.io.memletY := io.memletY
  jce.io.thisX := io.thisX
  jce.io.thisY := io.thisY
  jce.io.op.valid := io.sendCacheLine.valid
  jce.io.op.bits.slot := io.sendCacheLine.bits.slot

  // --- ALU connections ---
  // alu.io.dispatch := io.dispatch  // for immediate ALU ops

  // ============================================================
  // JTE connections
  // ============================================================

  jte.io.laneIndex := io.laneIndices(LaneOrder.ROW_MAJOR.asUInt)
  jte.io.x := io.thisX
  jte.io.y := io.thisY
  jte.io.create := io.jteCreate
  jte.io.clear := io.jteClear
  io.jteInputReq <> jte.io.inputReq
  jte.io.inputResp <> io.jteInputResp
  io.transferComplete := jte.io.transferComplete
  io.errors.jte := jte.io.errors
  io.errors.jce := jce.io.errors
  io.errors.localExec := localExec.io.errors
  io.errors.aHoRouter := aHoRouter.io.errors
  io.tlbReq <> jte.io.tlbReq
  jte.io.tlbResp <> io.tlbResp
  io.cacheLineReq <> jte.io.cacheLineReq
  jte.io.cacheLineResp <> io.cacheLineResp

  // Resource interfaces still need top-level arbiters.
  rfSlice.io.jteWriteReq <> jte.io.rfWriteReq
  jte.io.rfWriteResp <> rfSlice.io.jteWriteResp

  // ============================================================
  // Temporary: tie off non-network outputs
  // ============================================================

  io.cacheResponse := jce.io.rxDone
}

/** Generator for Jamlet module */
object JamletGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> Jamlet <jamletParamsFileName>")
      null
    } else {
      val params = ZamletParams.fromFile(args(0))
      new Jamlet(params)
    }
  }
}

object JamletMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  JamletGenerator.generate(outputDir, Seq(configFile))
}
