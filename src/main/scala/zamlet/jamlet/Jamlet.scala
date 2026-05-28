package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.Ordering
import zamlet.ZamletParams
import zamlet.network.{CombinedNetworkNode, NetworkWord, PacketArbiter, PacketHeader, MessageType}

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


/** Cache slot request from jamlet (for RX-initiated witems) */
class CacheSlotReq(params: ZamletParams) extends Bundle {
  val kMAddr = UInt(32.W)  // TODO: proper width
  val isWrite = Bool()
  val instrIdent = params.ident()
  val sourceX = params.xPos()
  val sourceY = params.yPos()
}

/** Cache slot response from kamlet */
class CacheSlotResp(params: ZamletParams) extends Bundle {
  val instrIdent = params.ident()
  val sourceX = params.xPos()
  val sourceY = params.yPos()
  val slot = params.cacheSlot()
  val cacheIsAvail = Bool()
}

/** Command to send cache line data */
class SendCacheLineCmd(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
  val ident = params.ident()
  val isWriteRead = Bool()
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
    val laneIndex = Input(UInt(params.log2JInL.W))

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
    val jteErrors = Output(new JteStateErrors())
    val tlbReq = Decoupled(UInt(params.pageAddrWidth.W))
    val tlbResp = Flipped(Decoupled(UInt(params.pageAddrWidth.W)))
    val orderingReq = Decoupled(UInt(params.memStripeAddrWidth.W))
    val orderingResp = Flipped(Decoupled(new Ordering))
    val cacheLineReq = Decoupled(new CacheLineRequest(params))
    val cacheLineResp = Flipped(Decoupled(new CacheLineResponse(params)))

    // Immediate kinstr execution (from kamlet) - for LoadImm, ALU ops, etc.
    val immediateKinstr = Flipped(Valid(new KinstrWithParams(params)))

    // Cache slot interface (to/from kamlet)
    val cacheSlotReq = Valid(new CacheSlotReq(params))
    val cacheSlotResp = Flipped(Valid(new CacheSlotResp(params)))
    val cacheStateUpdate = Valid(params.cacheSlot())

    // Cache line interface (from kamlet)
    val sendCacheLine = Flipped(Valid(new SendCacheLineCmd(params)))
    val cacheResponse = Valid(params.ident())

    // Kamlet packet interface
    val kamletInjectPacket = Flipped(Decoupled(new NetworkWord(params)))
    val kamletReceivePacket = Decoupled(new NetworkWord(params))
  })

  // ============================================================
  // Submodules
  // ============================================================

  val combinedNetworkNode = Module(new CombinedNetworkNode(params))

  val sram = Module(new Sram(params))
  val rfSlice = Module(new RfSlice(params))
  val jte = Module(new Jte(params))
  val localExec = Module(new LocalExec(params))
  val bArbiter = Module(new PacketArbiter(params, 2))  // LocalExec + JTE Ch1
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
  // Local port handling (simplified for Test 0)
  // Forward instruction packets to kamlet
  // ============================================================

  // A channel local output: forward instruction packets to kamlet
  val aHoHeader = combinedNetworkNode.io.aHo.bits.data.asTypeOf(new PacketHeader(params))
  val aHoIsInstruction = combinedNetworkNode.io.aHo.bits.isHeader &&
                         aHoHeader.messageType === MessageType.Instructions

  val jteChannel0In = Wire(Decoupled(new WithHeader(params)))
  jte.io.channel0In <> jteChannel0In
  jteChannel0In.valid := combinedNetworkNode.io.aHo.valid && !aHoIsInstruction
  jteChannel0In.bits.isHeader := combinedNetworkNode.io.aHo.bits.isHeader
  jteChannel0In.bits.bits := combinedNetworkNode.io.aHo.bits.data

  // When we see an instruction packet, forward to kamlet.
  io.kamletReceivePacket.valid := combinedNetworkNode.io.aHo.valid && aHoIsInstruction
  io.kamletReceivePacket.bits := combinedNetworkNode.io.aHo.bits
  combinedNetworkNode.io.aHo.ready := Mux(aHoIsInstruction, io.kamletReceivePacket.ready, jteChannel0In.ready)

  // Ch0 local input: JTE responses/acks.
  combinedNetworkNode.io.aHi.valid := jte.io.channel0Out.valid
  combinedNetworkNode.io.aHi.bits.isHeader := jte.io.channel0Out.bits.isHeader
  combinedNetworkNode.io.aHi.bits.data := jte.io.channel0Out.bits.bits
  jte.io.channel0Out.ready := combinedNetworkNode.io.aHi.ready

  // B channel local ports
  // hi: arbiter output -> network (for outgoing packets like WriteMemWord)
  combinedNetworkNode.io.bHi <> bArbiter.io.out
  // ho: network -> JTE request handler.
  jte.io.channel1In.valid := combinedNetworkNode.io.bHo.valid
  jte.io.channel1In.bits.isHeader := combinedNetworkNode.io.bHo.bits.isHeader
  jte.io.channel1In.bits.bits := combinedNetworkNode.io.bHo.bits.data
  combinedNetworkNode.io.bHo.ready := jte.io.channel1In.ready

  // --- SRAM connections ---
  sram.io.jteReq <> jte.io.sramReq
  jte.io.sramResp <> sram.io.jteResp
  sram.io.localReq.valid := false.B
  sram.io.localReq.bits := DontCare

  // --- RfSlice connections ---
  rfSlice.io.maskReq.valid := jte.io.rfMaskReq.valid
  rfSlice.io.maskReq.bits.addr := jte.io.rfMaskReq.bits
  rfSlice.io.maskReq.bits.isWrite := false.B
  rfSlice.io.maskReq.bits.writeData := DontCare
  jte.io.rfMaskReq.ready := rfSlice.io.maskReq.ready
  jte.io.rfMaskResp.valid := rfSlice.io.maskResp.valid
  jte.io.rfMaskResp.bits := rfSlice.io.maskResp.bits.readData
  rfSlice.io.maskResp.ready := jte.io.rfMaskResp.ready

  rfSlice.io.indexReq.valid := jte.io.rfIndexReq.valid
  rfSlice.io.indexReq.bits.addr := jte.io.rfIndexReq.bits
  rfSlice.io.indexReq.bits.isWrite := false.B
  rfSlice.io.indexReq.bits.writeData := DontCare
  jte.io.rfIndexReq.ready := rfSlice.io.indexReq.ready
  jte.io.rfIndexResp.valid := rfSlice.io.indexResp.valid
  jte.io.rfIndexResp.bits := rfSlice.io.indexResp.bits.readData
  rfSlice.io.indexResp.ready := jte.io.rfIndexResp.ready

  rfSlice.io.dataReq.valid := jte.io.rfDataReq.valid
  rfSlice.io.dataReq.bits.addr := jte.io.rfDataReq.bits
  rfSlice.io.dataReq.bits.isWrite := false.B
  rfSlice.io.dataReq.bits.writeData := DontCare
  jte.io.rfDataReq.ready := rfSlice.io.dataReq.ready
  jte.io.rfDataResp.valid := rfSlice.io.dataResp.valid
  jte.io.rfDataResp.bits := rfSlice.io.dataResp.bits.readData
  rfSlice.io.dataResp.ready := jte.io.rfDataResp.ready

  // LocalExec connections
  localExec.io.thisX := io.thisX
  localExec.io.thisY := io.thisY
  localExec.io.kinstrIn := io.immediateKinstr
  rfSlice.io.localExecReq <> localExec.io.rfReq
  rfSlice.io.localExecResp <> localExec.io.rfResp

  // B channel arbiter inputs: LocalExec (0) + JTE Ch1 requests (1)
  bArbiter.io.in(0) <> localExec.io.packetOut
  bArbiter.io.in(1).valid := jte.io.channel1Out.valid
  bArbiter.io.in(1).bits.isHeader := jte.io.channel1Out.bits.isHeader
  bArbiter.io.in(1).bits.data := jte.io.channel1Out.bits.bits
  jte.io.channel1Out.ready := bArbiter.io.in(1).ready

  // --- ALU connections ---
  // alu.io.dispatch := io.dispatch  // for immediate ALU ops

  // --- Cache state update (after SRAM write) ---
  // io.cacheStateUpdate := sram.io.slotModified

  // --- Cache line interface ---
  // io.cacheResponse := sram.io.cacheLineReceived

  // ============================================================
  // JTE connections
  // ============================================================

  jte.io.laneIndex := io.laneIndex
  jte.io.x := io.thisX
  jte.io.y := io.thisY
  jte.io.create := io.jteCreate
  jte.io.clear := io.jteClear
  io.jteInputReq <> jte.io.inputReq
  jte.io.inputResp <> io.jteInputResp
  io.transferComplete := jte.io.transferComplete
  io.jteErrors := jte.io.errors
  io.tlbReq <> jte.io.tlbReq
  jte.io.tlbResp <> io.tlbResp
  io.orderingReq <> jte.io.orderingReq
  jte.io.orderingResp <> io.orderingResp
  io.cacheLineReq <> jte.io.cacheLineReq
  jte.io.cacheLineResp <> io.cacheLineResp

  // Resource interfaces still need top-level arbiters.
  rfSlice.io.jteWriteReq <> jte.io.rfWriteReq
  jte.io.rfWriteResp <> rfSlice.io.jteWriteResp

  // ============================================================
  // Temporary: tie off non-network outputs
  // ============================================================

  io.cacheSlotReq.valid := false.B
  io.cacheSlotReq.bits := DontCare

  io.cacheStateUpdate.valid := false.B
  io.cacheStateUpdate.bits := DontCare

  io.cacheResponse.valid := false.B
  io.cacheResponse.bits := DontCare

  io.kamletInjectPacket.ready := false.B
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
