package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.LamletParams

/** Network channels IO - Vec of channels for each direction */
class ChannelsIO(params: LamletParams, nChannels: Int) extends Bundle {
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
class CacheSlotReq(params: LamletParams) extends Bundle {
  val kMAddr = UInt(32.W)  // TODO: proper width
  val isWrite = Bool()
  val instrIdent = params.ident()
  val sourceX = params.xPos()
  val sourceY = params.yPos()
}

/** Cache slot response from kamlet */
class CacheSlotResp(params: LamletParams) extends Bundle {
  val instrIdent = params.ident()
  val sourceX = params.xPos()
  val sourceY = params.yPos()
  val slot = params.cacheSlot()
  val cacheIsAvail = Bool()
}

/** Command to send cache line data */
class SendCacheLineCmd(params: LamletParams) extends Bundle {
  val slot = params.cacheSlot()
  val ident = params.ident()
  val isWriteRead = Bool()
}

/**
 * Jamlet - Single lane of the VPU
 *
 * Contains routers, SRAM, register file slice, and witem processing logic.
 */
class Jamlet(params: LamletParams) extends Module {
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

  val aNetworkNode = Module(new NetworkNode(params, params.nAChannels))
  val bNetworkNode = Module(new NetworkNode(params, params.nBChannels))

  // TODO: instantiate when ready
  // val sram = Module(new Sram(params))
  // val rfSlice = Module(new RfSlice(params))
  // val witemTable = Module(new WitemTable(params))
  // val rxA = Module(new RxA(params))
  // val rxB = Module(new RxB(params))
  val witemMonitor = Module(new WitemMonitor(params))
  // val aArbiter = Module(new ChArbiter(params))
  // val bArbiter = Module(new ChArbiter(params))
  // val alu = Module(new ALU(params))

  // ============================================================
  // Connections
  // ============================================================

  // --- A network node connections ---
  aNetworkNode.io.ni <> io.aChannels.ni
  aNetworkNode.io.no <> io.aChannels.no
  aNetworkNode.io.si <> io.aChannels.si
  aNetworkNode.io.so <> io.aChannels.so
  aNetworkNode.io.ei <> io.aChannels.ei
  aNetworkNode.io.eo <> io.aChannels.eo
  aNetworkNode.io.wi <> io.aChannels.wi
  aNetworkNode.io.wo <> io.aChannels.wo
  aNetworkNode.io.thisX := io.thisX
  aNetworkNode.io.thisY := io.thisY

  // --- B network node connections ---
  bNetworkNode.io.ni <> io.bChannels.ni
  bNetworkNode.io.no <> io.bChannels.no
  bNetworkNode.io.si <> io.bChannels.si
  bNetworkNode.io.so <> io.bChannels.so
  bNetworkNode.io.ei <> io.bChannels.ei
  bNetworkNode.io.eo <> io.bChannels.eo
  bNetworkNode.io.wi <> io.bChannels.wi
  bNetworkNode.io.wo <> io.bChannels.wo
  bNetworkNode.io.thisX := io.thisX
  bNetworkNode.io.thisY := io.thisY

  // Tie off local ports until RX handlers and arbiters exist
  aNetworkNode.io.hi.valid := false.B
  aNetworkNode.io.hi.bits := DontCare
  aNetworkNode.io.ho.ready := false.B
  bNetworkNode.io.hi.valid := false.B
  bNetworkNode.io.hi.bits := DontCare
  bNetworkNode.io.ho.ready := false.B

  // --- Network node local ports to RX handlers ---
  // rxA.io.packetIn <> aNetworkNode.io.ho
  // rxB.io.packetIn <> bNetworkNode.io.ho

  // --- Arbiters to network node local inputs ---
  // aNetworkNode.io.hi <> aArbiter.io.packetOut
  // bNetworkNode.io.hi <> bArbiter.io.packetOut

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
  // rfSlice.io.aluRead <> alu.io.rfRead
  // rfSlice.io.aluWrite <> alu.io.rfWrite
  // rfSlice.io.rxARead <> rxA.io.rfRead
  // rfSlice.io.rxAWrite <> rxA.io.rfWrite
  // rfSlice.io.rxBRead <> rxB.io.rfRead
  // rfSlice.io.rxBWrite <> rxB.io.rfWrite
  // rfSlice.io.witemMonitorRead <> witemMonitor.io.rfRead

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
  witemMonitor.io.maskRfReq.ready := true.B
  witemMonitor.io.maskRfResp.valid := false.B
  witemMonitor.io.maskRfResp.bits := DontCare
  witemMonitor.io.indexRfReq.ready := true.B
  witemMonitor.io.indexRfResp.valid := false.B
  witemMonitor.io.indexRfResp.bits := DontCare
  witemMonitor.io.dataRfReq.ready := true.B
  witemMonitor.io.dataRfResp.valid := false.B
  witemMonitor.io.dataRfResp.bits := DontCare
  witemMonitor.io.packetOut.ready := false.B

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

  io.kamletReceivePacket.valid := false.B
  io.kamletReceivePacket.bits := DontCare
}

/** Generator for Jamlet module */
object JamletGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> Jamlet <jamletParamsFileName>")
      null
    } else {
      val params = LamletParams.fromFile(args(0))
      new Jamlet(params)
    }
  }
}
