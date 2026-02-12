package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams

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

    // A channels (always-consumable responses)
    val aChannels = new ChannelsIO(params, params.nAChannels)

    // B channels (requests)
    val bChannels = new ChannelsIO(params, params.nBChannels)

    // Instruction interface (from kamlet)
    val witemCreate = Flipped(Valid(new WitemCreate(params)))
    val witemCacheAvail = Flipped(Valid(params.ident()))
    val witemRemove = Flipped(Valid(params.ident()))
    val witemComplete = Valid(params.ident())

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

  // TODO: instantiate when ready
  // val sram = Module(new Sram(params))
  val rfSlice = Module(new RfSlice(params))
  // val witemTable = Module(new WitemTable(params))
  // val rxA = Module(new RxA(params))
  // val rxB = Module(new RxB(params))
  val witemMonitor = Module(new WitemMonitor(params))
  val localExec = Module(new LocalExec(params))
  // val aArbiter = Module(new ChArbiter(params))
  val bArbiter = Module(new PacketArbiter(params, 2))  // LocalExec + WitemMonitor
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

  // When we see an instruction packet, forward to kamlet
  io.kamletReceivePacket.valid := combinedNetworkNode.io.aHo.valid
  io.kamletReceivePacket.bits := combinedNetworkNode.io.aHo.bits
  combinedNetworkNode.io.aHo.ready := io.kamletReceivePacket.ready

  // Tie off local input until TX arbiters exist
  combinedNetworkNode.io.aHi.valid := false.B
  combinedNetworkNode.io.aHi.bits := DontCare

  // B channel local ports
  // hi: arbiter output -> network (for outgoing packets like WriteMemWord)
  combinedNetworkNode.io.bHi <> bArbiter.io.out
  // ho: network -> local receivers (tie off until RxB exists)
  combinedNetworkNode.io.bHo.ready := false.B

  // --- Network node local ports to RX handlers ---
  // rxA.io.packetIn <> combinedNetworkNode.io.aHo
  // rxB.io.packetIn <> combinedNetworkNode.io.bHo

  // --- Arbiters to network node local inputs ---
  // combinedNetworkNode.io.aHi <> aArbiter.io.packetOut
  // combinedNetworkNode.io.bHi <> bArbiter.io.packetOut

  // --- A arbiter inputs (responses: RxA, RxB, WitemMonitor) ---
  // aArbiter.io.rxA <> rxA.io.respOut
  // aArbiter.io.rxB <> rxB.io.respOut
  // aArbiter.io.witemMonitor <> witemMonitor.io.aOut

  // --- B arbiter inputs (requests: RxB, WitemMonitor) ---
  // bArbiter.io.rxB <> rxB.io.reqOut
  // bArbiter.io.witemMonitor <> witemMonitor.io.bOut

  // --- WitemTable connections ---
  // witemTable.io.dispatch := io.dispatch
  // witemTable.io.cacheAvail := io.witemCacheAvail
  // witemTable.io.remove := io.witemRemove
  // io.witemComplete := witemTable.io.complete

  // --- WitemMonitor scans WitemTable ---
  // witemMonitor.io.witemRead <> witemTable.io.monitorPort
  // witemMonitor.io.witemUpdate <> witemTable.io.updatePort

  // --- SRAM connections ---
  // sram.io.rxARead <> rxA.io.sramRead
  // sram.io.rxAWrite <> rxA.io.sramWrite
  // sram.io.rxBRead <> rxB.io.sramRead
  // sram.io.rxBWrite <> rxB.io.sramWrite
  // sram.io.witemMonitorRead <> witemMonitor.io.sramRead
  // sram.io.sendCacheLine := io.sendCacheLine

  // --- RfSlice connections ---
  // WitemMonitor RF ports
  rfSlice.io.maskReq <> witemMonitor.io.maskRfReq
  rfSlice.io.maskResp <> witemMonitor.io.maskRfResp
  rfSlice.io.indexReq <> witemMonitor.io.indexRfReq
  rfSlice.io.indexResp <> witemMonitor.io.indexRfResp
  rfSlice.io.dataReq <> witemMonitor.io.dataRfReq
  rfSlice.io.dataResp <> witemMonitor.io.dataRfResp

  // LocalExec connections
  localExec.io.thisX := io.thisX
  localExec.io.thisY := io.thisY
  localExec.io.kinstrIn := io.immediateKinstr
  rfSlice.io.localExecReq <> localExec.io.rfReq
  rfSlice.io.localExecResp <> localExec.io.rfResp

  // B channel arbiter inputs: LocalExec (0) + WitemMonitor (1)
  bArbiter.io.in(0) <> localExec.io.packetOut
  bArbiter.io.in(1) <> witemMonitor.io.packetOut

  // --- ALU connections ---
  // alu.io.dispatch := io.dispatch  // for immediate ALU ops

  // --- Cache slot interface (RX-initiated witems) ---
  // io.cacheSlotReq <> rxB.io.cacheSlotReq
  // rxB.io.cacheSlotResp := io.cacheSlotResp

  // --- Cache state update (after SRAM write) ---
  // io.cacheStateUpdate := sram.io.slotModified

  // --- Cache line interface ---
  // io.cacheResponse := sram.io.cacheLineReceived

  // --- Kamlet packet interface ---
  // bArbiter.io.kamletInject <> io.kamletInjectPacket
  // io.kamletReceivePacket <> rxB.io.kamletForward  // instructions forwarded to kamlet

  // ============================================================
  // WitemMonitor connections
  // ============================================================

  witemMonitor.io.thisX := io.thisX
  witemMonitor.io.thisY := io.thisY
  witemMonitor.io.witemCreate := io.witemCreate
  witemMonitor.io.witemCacheAvail := io.witemCacheAvail
  witemMonitor.io.witemRemove := io.witemRemove
  io.witemComplete := witemMonitor.io.witemComplete

  // Tie off unconnected WitemMonitor ports
  witemMonitor.io.witemInfoReq.ready := true.B
  witemMonitor.io.witemInfoResp.valid := false.B
  witemMonitor.io.witemInfoResp.bits := DontCare
  witemMonitor.io.witemSrcUpdate.valid := false.B
  witemMonitor.io.witemSrcUpdate.bits := DontCare
  witemMonitor.io.witemDstUpdate.valid := false.B
  witemMonitor.io.witemDstUpdate.bits := DontCare
  witemMonitor.io.witemFaultSync.valid := false.B
  witemMonitor.io.witemFaultSync.bits := DontCare
  witemMonitor.io.witemCompletionSync.valid := false.B
  witemMonitor.io.witemCompletionSync.bits := DontCare
  witemMonitor.io.tlbReq.ready := true.B
  witemMonitor.io.tlbResp.valid := false.B
  witemMonitor.io.tlbResp.bits := DontCare
  witemMonitor.io.sramResp.valid := false.B
  witemMonitor.io.sramResp.bits := DontCare
  witemMonitor.io.sramReq.ready := false.B
  // RF ports connected to RfSlice above
  // packetOut connected to bArbiter above

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
