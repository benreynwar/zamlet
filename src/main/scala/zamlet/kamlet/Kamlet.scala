package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.SynchronizerParams
import zamlet.LaneOrderMapping
import zamlet.jamlet.{ChannelsIO, Jamlet}
import zamlet.network.{CombinedNetworkNode, MessageType, MessageTypePacketRouter,
                       MessageTypePacketRouterErrors, NetworkWord, PacketMerge,
                       PacketMergeErrors}
import zamlet.utils.{ResetPipeline, ResetPipelineBudget}

class KamletErrors extends Bundle {
  val instrQueue = new InstrQueueErrors
  val reservationStation = new ReservationStationErrors
  val cacheEngine = new KceCacheEngineErrors
  val tlb = new KamletTlbErrors
  val packetMerge = new PacketMergeErrors
  val aPacketRouter = new MessageTypePacketRouterErrors
  val bPacketRouter = new MessageTypePacketRouterErrors
}

/**
 * Kamlet is a cluster of jamlets that share an instruction queue, cache tracking,
 * and register file coordination.
 *
 * Current skeleton: InstrQueue feeds a pass-through Renamer and first-pass
 * ReservationStation, which handles the first-pass simple decode behavior.
 */
class Kamlet(
  params: ZamletParams,
  neighbors: SyncNeighbors,
  resetBudget: ResetPipelineBudget
) extends Module {
  val io = IO(new Bundle {
    // Position of this kamlet in the compute grid.
    val kX = Input(UInt(log2Ceil(params.kCols).W))
    val kY = Input(UInt(log2Ceil(params.kRows).W))

    // Position of this kamlet on the kamlet-level packet network.
    val knetX = Input(params.xPos())
    val knetY = Input(params.yPos())
    val lamletKnetX = Input(params.xPos())
    val lamletKnetY = Input(params.yPos())
    val memletKnetX = Input(params.xPos())
    val memletKnetY = Input(params.yPos())
    val jnetBaseX = Input(params.xPos())
    val jnetBaseY = Input(params.yPos())
    val memletJnetCoords = Input(Vec(params.jInK, new Bundle {
      val x = params.xPos()
      val y = params.yPos()
    }))

    // Network ports (exposed from edge jamlets)
    // North edge
    val nChannelsIn = Vec(params.jCols, Vec(params.nAChannels + params.nBChannels,
                          Flipped(Decoupled(new NetworkWord(params)))))
    val nChannelsOut = Vec(params.jCols, Vec(params.nAChannels + params.nBChannels,
                           Decoupled(new NetworkWord(params))))
    // South edge
    val sChannelsIn = Vec(params.jCols, Vec(params.nAChannels + params.nBChannels,
                          Flipped(Decoupled(new NetworkWord(params)))))
    val sChannelsOut = Vec(params.jCols, Vec(params.nAChannels + params.nBChannels,
                           Decoupled(new NetworkWord(params))))
    // East edge
    val eChannelsIn = Vec(params.jRows, Vec(params.nAChannels + params.nBChannels,
                          Flipped(Decoupled(new NetworkWord(params)))))
    val eChannelsOut = Vec(params.jRows, Vec(params.nAChannels + params.nBChannels,
                           Decoupled(new NetworkWord(params))))
    // West edge
    val wChannelsIn = Vec(params.jRows, Vec(params.nAChannels + params.nBChannels,
                          Flipped(Decoupled(new NetworkWord(params)))))
    val wChannelsOut = Vec(params.jRows, Vec(params.nAChannels + params.nBChannels,
                           Decoupled(new NetworkWord(params))))

    // Kamlet-level packet network ports.
    val kamletAChannels = new ChannelsIO(params, params.nAChannels)
    val kamletBChannels = new ChannelsIO(params, params.nBChannels)

    // Sync network ports
    val syncPortOut = Output(Vec(SyncDirection.count, new SyncPort))
    val syncPortIn = Input(Vec(SyncDirection.count, new SyncPort))


    // Error signals
    val errors = Output(new KamletErrors)
  })

  val resetPipeline =
    ResetPipeline(clock, reset.asBool, 1, resetBudget, "Kamlet")
  val childResetBudget = resetPipeline.childBudget

  withReset(resetPipeline.localReset) {

  // ============================================================
  // Instantiate jamlets in a grid
  // ============================================================

  val jamlets = Seq.tabulate(params.jRows, params.jCols) { (localJY, localJX) =>
    val j: Jamlet = withReset(resetPipeline.childReset) {
      Module(new Jamlet(params, childResetBudget))
    }
    val jInKIndex = localJY * params.jCols + localJX
    val jX = io.kX * params.jCols.U + localJX.U
    val jY = io.kY * params.jRows.U + localJY.U
    j.io.thisX := io.jnetBaseX + localJX.U
    j.io.thisY := io.jnetBaseY + localJY.U
    j.io.memletX := io.memletJnetCoords(jInKIndex).x
    j.io.memletY := io.memletJnetCoords(jInKIndex).y
    j.io.laneIndices := LaneOrderMapping.indices(params, jX, jY)
    j
  }

  // ============================================================
  // Connect jamlet network ports (internal mesh)
  // ============================================================

  for (jY <- 0 until params.jRows) {
    for (jX <- 0 until params.jCols) {
      val j = jamlets(jY)(jX)

      // North connections
      if (jY == 0) {
        // Edge: connect to external north ports
        for (ch <- 0 until params.nAChannels) {
          j.io.aChannels.ni(ch) <> io.nChannelsIn(jX)(ch)
          j.io.aChannels.no(ch) <> io.nChannelsOut(jX)(ch)
        }
        for (ch <- 0 until params.nBChannels) {
          j.io.bChannels.ni(ch) <> io.nChannelsIn(jX)(params.nAChannels + ch)
          j.io.bChannels.no(ch) <> io.nChannelsOut(jX)(params.nAChannels + ch)
        }
      } else {
        // Internal: connect to southern neighbor
        val neighbor = jamlets(jY - 1)(jX)
        for (ch <- 0 until params.nAChannels) {
          j.io.aChannels.ni(ch) <> neighbor.io.aChannels.so(ch)
          j.io.aChannels.no(ch) <> neighbor.io.aChannels.si(ch)
        }
        for (ch <- 0 until params.nBChannels) {
          j.io.bChannels.ni(ch) <> neighbor.io.bChannels.so(ch)
          j.io.bChannels.no(ch) <> neighbor.io.bChannels.si(ch)
        }
      }

      // South connections
      if (jY == params.jRows - 1) {
        // Edge: connect to external south ports
        for (ch <- 0 until params.nAChannels) {
          j.io.aChannels.si(ch) <> io.sChannelsIn(jX)(ch)
          j.io.aChannels.so(ch) <> io.sChannelsOut(jX)(ch)
        }
        for (ch <- 0 until params.nBChannels) {
          j.io.bChannels.si(ch) <> io.sChannelsIn(jX)(params.nAChannels + ch)
          j.io.bChannels.so(ch) <> io.sChannelsOut(jX)(params.nAChannels + ch)
        }
      }
      // Internal south connections handled by north connections of neighbor

      // East connections
      if (jX == params.jCols - 1) {
        // Edge: connect to external east ports
        for (ch <- 0 until params.nAChannels) {
          j.io.aChannels.ei(ch) <> io.eChannelsIn(jY)(ch)
          j.io.aChannels.eo(ch) <> io.eChannelsOut(jY)(ch)
        }
        for (ch <- 0 until params.nBChannels) {
          j.io.bChannels.ei(ch) <> io.eChannelsIn(jY)(params.nAChannels + ch)
          j.io.bChannels.eo(ch) <> io.eChannelsOut(jY)(params.nAChannels + ch)
        }
      } else {
        // Internal: connect to eastern neighbor
        val neighbor = jamlets(jY)(jX + 1)
        for (ch <- 0 until params.nAChannels) {
          j.io.aChannels.ei(ch) <> neighbor.io.aChannels.wo(ch)
          j.io.aChannels.eo(ch) <> neighbor.io.aChannels.wi(ch)
        }
        for (ch <- 0 until params.nBChannels) {
          j.io.bChannels.ei(ch) <> neighbor.io.bChannels.wo(ch)
          j.io.bChannels.eo(ch) <> neighbor.io.bChannels.wi(ch)
        }
      }

      // West connections
      if (jX == 0) {
        // Edge: connect to external west ports
        for (ch <- 0 until params.nAChannels) {
          j.io.aChannels.wi(ch) <> io.wChannelsIn(jY)(ch)
          j.io.aChannels.wo(ch) <> io.wChannelsOut(jY)(ch)
        }
        for (ch <- 0 until params.nBChannels) {
          j.io.bChannels.wi(ch) <> io.wChannelsIn(jY)(params.nAChannels + ch)
          j.io.bChannels.wo(ch) <> io.wChannelsOut(jY)(params.nAChannels + ch)
        }
      }
      // Internal west connections handled by east connections of neighbor

    }
  }

  // ============================================================
  // Kamlet submodules
  // ============================================================

  val instrQueue = Module(new InstrQueue(params))
  val renamer = Module(new Renamer(params))
  val reservationStation = Module(new ReservationStation(params))
  val synchronizer = Module(new Synchronizer(neighbors, params))
  val cacheEngine = Module(new KamletCacheEngine(params))
  val transferEngine = Module(new KamletTransferEngine(params))
  val kamletTlb = Module(new KamletTlb(params))
  val aPacketRouter = Module(new MessageTypePacketRouter(
    params,
    Seq(
      Seq(
        MessageType.ReadLineAddrDrop,
        MessageType.WriteLineAddrDrop,
        MessageType.WriteLineReadLineAddrDrop,
        MessageType.WriteLineDataDrop,
        MessageType.WriteLineResp),
      Seq(MessageType.TlbResp)),
    params.kamletAIngressPacketRouterParams))
  val bPacketRouter = Module(new MessageTypePacketRouter(
    params,
    Seq(Seq(MessageType.Instructions)),
    params.kamletBIngressPacketRouterParams))
  val packetMerge = Module(new PacketMerge(params, 2, params.kamletPacketMergeParams))
  val kamletNetworkNode: CombinedNetworkNode = withReset(resetPipeline.childReset) {
    Module(new CombinedNetworkNode(params, childResetBudget))
  }

  cacheEngine.io.knetX := io.knetX
  cacheEngine.io.knetY := io.knetY
  cacheEngine.io.memletKnetX := io.memletKnetX
  cacheEngine.io.memletKnetY := io.memletKnetY
  kamletTlb.io.knetX := io.knetX
  kamletTlb.io.knetY := io.knetY
  kamletTlb.io.lamletKnetX := io.lamletKnetX
  kamletTlb.io.lamletKnetY := io.lamletKnetY

  renamer.io.kinstrIn <> instrQueue.io.kinstrOut
  reservationStation.io.renamedIn <> renamer.io.renamedOut

  reservationStation.io.kteRfRelease <> transferEngine.io.rfRelease

  transferEngine.io.rsIssue <> reservationStation.io.kteIssue
  transferEngine.io.conflictMem := reservationStation.io.kteConflictMem
  reservationStation.io.kteConflict := transferEngine.io.conflict

  cacheEngine.io.rsAllocSlotReq <> reservationStation.io.kceAllocSlotReq
  reservationStation.io.kceAllocSlotResp <> cacheEngine.io.rsAllocSlotResp

  cacheEngine.io.kteReleaseSlot := transferEngine.io.kceReleaseSlot
  transferEngine.io.kceSlotIsAvailable := cacheEngine.io.kteSlotIsAvailable
  cacheEngine.io.kteSlotStatusReq := transferEngine.io.kceSlotStatusReq
  transferEngine.io.kceSlotStatusResp := cacheEngine.io.kteSlotStatusResp
  cacheEngine.io.kteInstrStartedResp := transferEngine.io.kceInstrStartedResp
  transferEngine.io.kceInstrStartedReq := cacheEngine.io.kteInstrStartedReq
  cacheEngine.io.kteInstrStartedNotify := transferEngine.io.kceInstrStartedNotify

  kamletNetworkNode.io.thisX := io.knetX
  kamletNetworkNode.io.thisY := io.knetY

  kamletNetworkNode.io.aNi <> io.kamletAChannels.ni
  kamletNetworkNode.io.aNo <> io.kamletAChannels.no
  kamletNetworkNode.io.aSi <> io.kamletAChannels.si
  kamletNetworkNode.io.aSo <> io.kamletAChannels.so
  kamletNetworkNode.io.aEi <> io.kamletAChannels.ei
  kamletNetworkNode.io.aEo <> io.kamletAChannels.eo
  kamletNetworkNode.io.aWi <> io.kamletAChannels.wi
  kamletNetworkNode.io.aWo <> io.kamletAChannels.wo

  kamletNetworkNode.io.bNi <> io.kamletBChannels.ni
  kamletNetworkNode.io.bNo <> io.kamletBChannels.no
  kamletNetworkNode.io.bSi <> io.kamletBChannels.si
  kamletNetworkNode.io.bSo <> io.kamletBChannels.so
  kamletNetworkNode.io.bEi <> io.kamletBChannels.ei
  kamletNetworkNode.io.bEo <> io.kamletBChannels.eo
  kamletNetworkNode.io.bWi <> io.kamletBChannels.wi
  kamletNetworkNode.io.bWo <> io.kamletBChannels.wo

  // ============================================================
  // Wiring: Kamlet network → InstrQueue → Renamer → ReservationStation
  // ============================================================

  aPacketRouter.io.in <> kamletNetworkNode.io.aHo
  kamletNetworkNode.io.aHi.valid := false.B
  kamletNetworkNode.io.aHi.bits := DontCare
  cacheEngine.io.packetIn <> aPacketRouter.io.out(0)
  kamletTlb.io.packetIn <> aPacketRouter.io.out(1)
  packetMerge.io.in(0) <> cacheEngine.io.packetOut
  packetMerge.io.in(1) <> kamletTlb.io.packetOut
  kamletNetworkNode.io.bHi <> packetMerge.io.out
  bPacketRouter.io.in <> kamletNetworkNode.io.bHo
  instrQueue.io.packetIn <> bPacketRouter.io.out(0)

  // KTE owns synchronizer use for explicit sync instructions and transfer
  // completion barriers.
  synchronizer.io.localEvent := transferEngine.io.syncLocalEvent
  transferEngine.io.syncResult := synchronizer.io.result

  // ReservationStation / KTE replay → Jamlets (immediate kinstrs)
  // Flatten jamlets to 1D index: jInKIndex = jY * jCols + jX
  val kteLocalReplayReady = Wire(Vec(params.jInK, Bool()))
  val kteLocalReplayCanBroadcast = kteLocalReplayReady.asUInt.andR
  transferEngine.io.localReplay.ready := kteLocalReplayCanBroadcast

  for (jY <- 0 until params.jRows; jX <- 0 until params.jCols) {
    val jInKIndex = jY * params.jCols + jX
    val rsImmediate = reservationStation.io.immediateKinstr(jInKIndex)

    kteLocalReplayReady(jInKIndex) := !rsImmediate.valid
    jamlets(jY)(jX).io.immediateKinstr.valid :=
      rsImmediate.valid || (transferEngine.io.localReplay.valid && kteLocalReplayCanBroadcast)
    jamlets(jY)(jX).io.immediateKinstr.bits :=
      Mux(rsImmediate.valid, rsImmediate.bits, transferEngine.io.localReplay.bits)

    jamlets(jY)(jX).io.jteCreate := transferEngine.io.jteCreate(jInKIndex)
    jamlets(jY)(jX).io.jteClear := transferEngine.io.jteClear(jInKIndex)
    transferEngine.io.jteInputReq(jInKIndex) <> jamlets(jY)(jX).io.jteInputReq
    jamlets(jY)(jX).io.jteInputResp <> transferEngine.io.jteInputResp(jInKIndex)
    transferEngine.io.transferComplete(jInKIndex) := jamlets(jY)(jX).io.transferComplete
    kamletTlb.io.tlbReq(jInKIndex) <> jamlets(jY)(jX).io.tlbReq
    jamlets(jY)(jX).io.tlbResp <> kamletTlb.io.tlbResp(jInKIndex)
    jamlets(jY)(jX).io.tlbAvailable <> kamletTlb.io.tlbAvailable(jInKIndex)
    cacheEngine.io.jteCacheLineReq(jInKIndex) <> jamlets(jY)(jX).io.cacheLineReq
    jamlets(jY)(jX).io.cacheLineResp <> cacheEngine.io.jteCacheLineResp(jInKIndex)
    jamlets(jY)(jX).io.cacheLineReplay <> cacheEngine.io.jteReplay(jInKIndex)
    cacheEngine.io.jteCacheLineRelease(jInKIndex).valid := jamlets(jY)(jX).io.cacheLineRelease.valid
    cacheEngine.io.jteCacheLineRelease(jInKIndex).bits.slot := jamlets(jY)(jX).io.cacheLineRelease.bits
    jamlets(jY)(jX).io.sendCacheLine := cacheEngine.io.jceWritebackReq(jInKIndex)
    cacheEngine.io.jceFetchDone(jInKIndex) := jamlets(jY)(jX).io.cacheResponse
  }

  kamletTlb.io.localOrderingUpdate.valid := false.B
  kamletTlb.io.localOrderingUpdate.bits := DontCare

  // ============================================================
  // Sync network
  // ============================================================

  io.syncPortOut := synchronizer.io.portOut
  synchronizer.io.portIn := io.syncPortIn

  // ============================================================
  // Outputs
  // ============================================================

  io.errors.instrQueue := instrQueue.io.errors
  io.errors.reservationStation := reservationStation.io.errors
  io.errors.cacheEngine := cacheEngine.io.errors
  io.errors.tlb := kamletTlb.io.errors
  io.errors.packetMerge := packetMerge.io.errors
  io.errors.aPacketRouter := aPacketRouter.io.errors
  io.errors.bPacketRouter := bPacketRouter.io.errors
  }
}

object KamletGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <configFile>")
      System.exit(1)
    }
    val params = ZamletParams.fromFile(args(0))
    // For standalone test, assume all neighbors present
    val neighbors = SyncNeighbors()
    new Kamlet(params, neighbors, ResetPipelineBudget(params.resetPipelineDepth))
  }
}

object KamletMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  KamletGenerator.generate(outputDir, Seq(configFile))
}
