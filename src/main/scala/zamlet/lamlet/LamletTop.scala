package zamlet.lamlet

import chisel3._
import chisel3.util._
import zamlet.LamletParams
import zamlet.kamlet.{KamletMesh, MeshEdgeNeighbors, SyncPort, SyncDirection, SyncIO}
import zamlet.jamlet.NetworkWord

/**
 * LamletTop - top-level module containing Lamlet and KamletMesh.
 *
 * This integrates:
 * - Lamlet: instruction decode, dispatch, and sync coordination
 * - KamletMesh: grid of kamlets for compute
 *
 * External interfaces:
 * - Scalar core interface (ex, tlb, com, kill)
 * - VPU memory interface (east/west edges of mesh)
 * - Status signals
 */
class LamletTop(params: LamletParams) extends Module {
  val io = IO(new Bundle {
    // Scalar core interface
    val ex = Flipped(Decoupled(new IssueUnitExData))
    val tlbReq = Decoupled(new IssueUnitTlbReq)
    val tlbResp = Input(new IssueUnitTlbResp)
    val com = Output(new IssueUnitCom)
    val kill = Input(Bool())

    // Status
    val backendBusy = Output(Bool())

    // East edge network ports (to VPU memory)
    val eChannelsIn = Vec(params.kRows, Vec(params.jRows,
      Vec(params.nAChannels + params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))))
    val eChannelsOut = Vec(params.kRows, Vec(params.jRows,
      Vec(params.nAChannels + params.nBChannels, Decoupled(new NetworkWord(params)))))

    // West edge network ports (to VPU memory)
    val wChannelsIn = Vec(params.kRows, Vec(params.jRows,
      Vec(params.nAChannels + params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))))
    val wChannelsOut = Vec(params.kRows, Vec(params.jRows,
      Vec(params.nAChannels + params.nBChannels, Decoupled(new NetworkWord(params)))))
  })

  // Submodules
  val lamlet = Module(new Lamlet(params))
  val mesh = Module(new KamletMesh(params, MeshEdgeNeighbors.isolated(params.kCols, params.kRows)))

  // ============================================================
  // Scalar core interface → Lamlet
  // ============================================================
  lamlet.io.ex <> io.ex
  lamlet.io.tlbReq <> io.tlbReq
  lamlet.io.tlbResp := io.tlbResp
  io.com := lamlet.io.com
  lamlet.io.kill := io.kill
  io.backendBusy := lamlet.io.backendBusy

  // ============================================================
  // Lamlet mesh output → KamletMesh north edge
  // ============================================================
  // Lamlet dispatches packets to kamlet (0,0) jamlet (0,0) channel 0
  mesh.io.nChannelsIn(0)(0)(0) <> lamlet.io.mesh

  // Tie off other north edge inputs (no external source)
  for (kX <- 0 until params.kCols) {
    for (jX <- 0 until params.jCols) {
      for (ch <- 0 until params.nAChannels + params.nBChannels) {
        if (!(kX == 0 && jX == 0 && ch == 0)) {
          mesh.io.nChannelsIn(kX)(jX)(ch).valid := false.B
          mesh.io.nChannelsIn(kX)(jX)(ch).bits := DontCare
        }
      }
    }
  }

  // North edge outputs not used (lamlet doesn't receive from mesh via this path)
  for (kX <- 0 until params.kCols) {
    for (jX <- 0 until params.jCols) {
      for (ch <- 0 until params.nAChannels + params.nBChannels) {
        mesh.io.nChannelsOut(kX)(jX)(ch).ready := false.B
      }
    }
  }

  // ============================================================
  // Sync network: Lamlet ↔ KamletMesh
  // ============================================================
  // Lamlet connects to kamlet (0,0)'s north sync port
  mesh.io.nSyncN(0).in.valid := lamlet.io.syncPortSOut.valid
  mesh.io.nSyncN(0).in.bits := lamlet.io.syncPortSOut.bits
  lamlet.io.syncPortSIn.valid := mesh.io.nSyncN(0).out.valid
  lamlet.io.syncPortSIn.bits := mesh.io.nSyncN(0).out.bits

  // Tie off other north sync ports (no external neighbors for isolated mesh)
  for (kX <- 1 until params.kCols) {
    mesh.io.nSyncN(kX).in.valid := false.B
    mesh.io.nSyncN(kX).in.bits := 0.U
  }
  for (kX <- 0 until params.kCols) {
    mesh.io.nSyncNE(kX).in.valid := false.B
    mesh.io.nSyncNE(kX).in.bits := 0.U
    mesh.io.nSyncNW(kX).in.valid := false.B
    mesh.io.nSyncNW(kX).in.bits := 0.U
  }

  // Tie off south sync ports (no external neighbors)
  for (kX <- 0 until params.kCols) {
    mesh.io.sSyncS(kX).in.valid := false.B
    mesh.io.sSyncS(kX).in.bits := 0.U
    mesh.io.sSyncSE(kX).in.valid := false.B
    mesh.io.sSyncSE(kX).in.bits := 0.U
    mesh.io.sSyncSW(kX).in.valid := false.B
    mesh.io.sSyncSW(kX).in.bits := 0.U
  }

  // Tie off east sync ports (no external neighbors)
  for (kY <- 0 until params.kRows) {
    mesh.io.eSyncE(kY).in.valid := false.B
    mesh.io.eSyncE(kY).in.bits := 0.U
  }
  for (kY <- 0 until params.kRows - 1) {
    mesh.io.eSyncNE(kY).in.valid := false.B
    mesh.io.eSyncNE(kY).in.bits := 0.U
    mesh.io.eSyncSE(kY).in.valid := false.B
    mesh.io.eSyncSE(kY).in.bits := 0.U
  }

  // Tie off west sync ports (no external neighbors)
  for (kY <- 0 until params.kRows) {
    mesh.io.wSyncW(kY).in.valid := false.B
    mesh.io.wSyncW(kY).in.bits := 0.U
  }
  for (kY <- 0 until params.kRows - 1) {
    mesh.io.wSyncNW(kY).in.valid := false.B
    mesh.io.wSyncNW(kY).in.bits := 0.U
    mesh.io.wSyncSW(kY).in.valid := false.B
    mesh.io.wSyncSW(kY).in.bits := 0.U
  }

  // ============================================================
  // South edge (closed - no external connections)
  // ============================================================
  for (kX <- 0 until params.kCols) {
    for (jX <- 0 until params.jCols) {
      for (ch <- 0 until params.nAChannels + params.nBChannels) {
        mesh.io.sChannelsIn(kX)(jX)(ch).valid := false.B
        mesh.io.sChannelsIn(kX)(jX)(ch).bits := DontCare
        mesh.io.sChannelsOut(kX)(jX)(ch).ready := false.B
      }
    }
  }

  // ============================================================
  // East/West edges → VPU memory
  // ============================================================
  for (kY <- 0 until params.kRows) {
    for (jY <- 0 until params.jRows) {
      for (ch <- 0 until params.nAChannels + params.nBChannels) {
        mesh.io.eChannelsIn(kY)(jY)(ch) <> io.eChannelsIn(kY)(jY)(ch)
        io.eChannelsOut(kY)(jY)(ch) <> mesh.io.eChannelsOut(kY)(jY)(ch)
        mesh.io.wChannelsIn(kY)(jY)(ch) <> io.wChannelsIn(kY)(jY)(ch)
        io.wChannelsOut(kY)(jY)(ch) <> mesh.io.wChannelsOut(kY)(jY)(ch)
      }
    }
  }
}

object LamletTopGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <configFile>")
      System.exit(1)
    }
    val params = LamletParams.fromFile(args(0))
    new LamletTop(params)
  }
}

object LamletTopMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  LamletTopGenerator.generate(outputDir, Seq(configFile))
}
