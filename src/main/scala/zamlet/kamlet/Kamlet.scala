package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.SynchronizerParams
import zamlet.jamlet.{Jamlet, NetworkWord}

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

    // Sync network ports
    val syncPortOut = Output(Vec(SyncDirection.count, new SyncPort))
    val syncPortIn = Input(Vec(SyncDirection.count, new SyncPort))


    // Error signals
    val instrQueueErrors = Output(new InstrQueueErrors)
  })

  // ============================================================
  // Instantiate jamlets in a grid
  // ============================================================

  val jamlets = Seq.tabulate(params.jRows, params.jCols) { (jY, jX) =>
    val j = Module(new Jamlet(params))
    // Set position: absolute position = kamlet position * jamlets per kamlet + local position
    j.io.thisX := io.kX * params.jCols.U + jX.U
    j.io.thisY := io.kY * params.jRows.U + jY.U
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

      // Tie off kamlet-facing ports for now (except jamlet 0,0 which forwards to InstrQueue)
      j.io.witemCreate.valid := false.B
      j.io.witemCreate.bits := DontCare
      j.io.witemCacheAvail.valid := false.B
      j.io.witemCacheAvail.bits := DontCare
      j.io.witemRemove.valid := false.B
      j.io.witemRemove.bits := DontCare
      j.io.cacheSlotResp.valid := false.B
      j.io.cacheSlotResp.bits := DontCare
      j.io.sendCacheLine.valid := false.B
      j.io.sendCacheLine.bits := DontCare
      j.io.kamletInjectPacket.valid := false.B
      j.io.kamletInjectPacket.bits := DontCare
    }
  }

  // ============================================================
  // Kamlet submodules
  // ============================================================

  val instrQueue = Module(new InstrQueue(params))
  val instrExecutor = Module(new InstrExecutor(params))
  val synchronizer = Module(new Synchronizer(neighbors, params.synchronizerParams))

  // ============================================================
  // Wiring: Jamlet(0,0).kamletReceivePacket → InstrQueue → InstrExecutor → Synchronizer
  // ============================================================

  // Connect jamlet 0,0's kamletReceivePacket to InstrQueue
  instrQueue.io.packetIn <> jamlets(0)(0).io.kamletReceivePacket

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

  io.instrQueueErrors := instrQueue.io.errors
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
