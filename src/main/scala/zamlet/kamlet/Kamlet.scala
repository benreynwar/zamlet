package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.SynchronizerParams
import zamlet.LaneOrderMapping
import zamlet.jamlet.{ChannelsIO, Jamlet}
import zamlet.network.{CombinedNetworkNode, NetworkWord}

/**
 * Kamlet is a cluster of jamlets that share an instruction queue, cache tracking,
 * and register file coordination.
 *
 * For Test 0 (minimal): Only InstrQueue + InstrExecutor + Synchronizer.
 * Later phases add: CacheTable, WitemController, dispatch to jamlets, etc.
 */
class Kamlet(
  params: ZamletParams,
  neighbors: SyncNeighbors
) extends Module {
  val io = IO(new Bundle {
    // Position of this kamlet in the zamlet
    val kX = Input(UInt(log2Ceil(params.kCols).W))
    val kY = Input(UInt(log2Ceil(params.kRows).W))

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

  // ============================================================
  // Instantiate jamlets in a grid
  // ============================================================

  val jamlets = Seq.tabulate(params.jRows, params.jCols) { (jY, jX) =>
    val j = Module(new Jamlet(params))
    // Set position: absolute position = kamlet position * jamlets per kamlet + local position
    val absoluteX = io.kX * params.jCols.U + jX.U
    val absoluteY = io.kY * params.jRows.U + jY.U
    j.io.thisX := absoluteX
    j.io.thisY := absoluteY
    j.io.memletX := 0.U
    j.io.memletY := 0.U
    j.io.laneIndices := LaneOrderMapping.indices(params, absoluteX, absoluteY)
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

      // Tie off kamlet-facing ports for now.
      j.io.jteCreate.valid := false.B
      j.io.jteCreate.bits := DontCare
      j.io.jteClear.valid := false.B
      j.io.jteClear.bits := DontCare
      j.io.jteInputReq.ready := false.B
      j.io.jteInputResp.valid := false.B
      j.io.jteInputResp.bits := DontCare
      j.io.tlbReq.ready := false.B
      j.io.tlbResp.valid := false.B
      j.io.tlbResp.bits := DontCare
      j.io.orderingReq.ready := false.B
      j.io.orderingResp.valid := false.B
      j.io.orderingResp.bits := DontCare
      j.io.cacheLineReq.ready := false.B
      j.io.cacheLineResp.valid := false.B
      j.io.cacheLineResp.bits := DontCare
      j.io.sendCacheLine.valid := false.B
      j.io.sendCacheLine.bits := DontCare
    }
  }

  // ============================================================
  // Kamlet submodules
  // ============================================================

  val instrQueue = Module(new InstrQueue(params))
  val instrExecutor = Module(new InstrExecutor(params))
  val synchronizer = Module(new Synchronizer(neighbors, params.synchronizerParams))
  val kamletNetworkNode = Module(new CombinedNetworkNode(params))

  kamletNetworkNode.io.thisX := io.kX
  kamletNetworkNode.io.thisY := io.kY

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
  // Wiring: Kamlet network → InstrQueue → InstrExecutor → Synchronizer
  // ============================================================

  instrQueue.io.packetIn <> kamletNetworkNode.io.aHo
  kamletNetworkNode.io.aHi.valid := false.B
  kamletNetworkNode.io.aHi.bits := DontCare
  kamletNetworkNode.io.bHi.valid := false.B
  kamletNetworkNode.io.bHi.bits := DontCare
  kamletNetworkNode.io.bHo.ready := false.B

  // InstrQueue → InstrExecutor
  instrExecutor.io.kinstrIn <> instrQueue.io.kinstrOut

  // InstrExecutor → Synchronizer
  synchronizer.io.localEvent := instrExecutor.io.syncLocalEvent

  // InstrExecutor → Jamlets (immediate kinstrs)
  // Flatten jamlets to 1D index: jInKIndex = jY * jCols + jX
  for (jY <- 0 until params.jRows; jX <- 0 until params.jCols) {
    val jInKIndex = jY * params.jCols + jX
    jamlets(jY)(jX).io.immediateKinstr := instrExecutor.io.immediateKinstr(jInKIndex)
  }

  // ============================================================
  // Sync network
  // ============================================================

  io.syncPortOut := synchronizer.io.portOut
  synchronizer.io.portIn := io.syncPortIn

  // ============================================================
  // Outputs
  // ============================================================

  io.errors.instrQueue := instrQueue.io.errors
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
    new Kamlet(params, neighbors)
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
