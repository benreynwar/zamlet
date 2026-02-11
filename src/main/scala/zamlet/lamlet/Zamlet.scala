package zamlet.lamlet

import chisel3._
import chisel3.util._
import org.chipsalliance.cde.config._
import freechips.rocketchip.rocket._
import freechips.rocketchip.tile._
import freechips.rocketchip.tilelink._
import freechips.rocketchip.diplomacy._

import shuttle.common._
import zamlet.LamletParams
import zamlet.kamlet.{KamletMesh, MeshEdgeNeighbors}
import zamlet.jamlet.NetworkWord
import zamlet.oamlet.VPUMemParamsKey

/** Config key for Zamlet parameters */
case object ZamletParamsKey extends Field[LamletParams]

/**
 * Zamlet - top-level vector unit containing Lamlet and KamletMesh.
 *
 * Extends ShuttleVectorUnit for integration with Shuttle scalar core.
 * Contains:
 * - Lamlet: instruction decode, dispatch, and sync coordination
 * - KamletMesh: grid of kamlets for compute
 */
class Zamlet(implicit p: Parameters) extends ShuttleVectorUnit()(p) with HasCoreParameters {

  val zParams = p(ZamletParamsKey)

  // TileLink client node for scalar memory access
  // This connects to the memory system for vector loads/stores
  val tlClient = TLClientNode(Seq(TLMasterPortParameters.v1(
    clients = Seq(TLMasterParameters.v1(
      name = "zamlet-scalar-mem",
      sourceId = IdRange(0, 4)
    ))
  )))

  // Connect our TL client to the atlNode (attached TL node from ShuttleVectorUnit)
  atlNode := tlClient

  val vpuMemParams = p(VPUMemParamsKey)
  val vpuTLNode: TLNode = TLManagerNode(Seq(TLSlavePortParameters.v1(
    Seq(TLSlaveParameters.v1(
      address = Seq(AddressSet(vpuMemParams.base, vpuMemParams.size - 1)),
      supportsGet = TransferSizes(1, 8),
      supportsPutFull = TransferSizes(1, 8),
      supportsPutPartial = TransferSizes(1, 8)
      )),
    beatBytes = 8
  )))

  override lazy val module = new ZamletImpl(this)
}

class ZamletImpl(outer: Zamlet)
    extends ShuttleVectorUnitModuleImp(outer)
    with HasCoreParameters {

  val zParams = outer.zParams

  // Get TileLink edge for building requests
  val (tlOut, tlEdge) = outer.tlClient.out.head

  // Submodules
  val lamlet = Module(new Lamlet(zParams))
  val mesh = Module(new KamletMesh(zParams, MeshEdgeNeighbors.isolated(zParams.kCols, zParams.kRows)))

  // ============================================================
  // Bridge ShuttleVectorCoreIO (io) to IssueUnit interface
  // ============================================================

  // Execute stage: Shuttle -> Lamlet
  lamlet.io.ex.valid := io.ex.valid
  lamlet.io.ex.bits.inst := io.ex.uop.inst
  lamlet.io.ex.bits.rs1Data := io.ex.uop.rs1_data
  lamlet.io.ex.bits.vl := io.ex.vconfig.vl
  lamlet.io.ex.bits.vstart := io.ex.vstart
  lamlet.io.ex.bits.vsew := io.ex.vconfig.vtype.vsew
  io.ex.ready := lamlet.io.ex.ready

  // TLB interface: Lamlet -> Shuttle
  io.mem.tlb_req.valid := lamlet.io.tlbReq.valid
  io.mem.tlb_req.bits.vaddr := lamlet.io.tlbReq.bits.vaddr
  io.mem.tlb_req.bits.size := log2Ceil(8).U
  io.mem.tlb_req.bits.cmd := lamlet.io.tlbReq.bits.cmd
  io.mem.tlb_req.bits.prv := io.status.prv
  lamlet.io.tlbReq.ready := io.mem.tlb_req.ready

  // TLB response: Shuttle -> Lamlet
  lamlet.io.tlbResp.paddr := io.mem.tlb_resp.paddr
  lamlet.io.tlbResp.miss := io.mem.tlb_resp.miss
  lamlet.io.tlbResp.pfLd := io.mem.tlb_resp.pf.ld
  lamlet.io.tlbResp.pfSt := io.mem.tlb_resp.pf.st
  lamlet.io.tlbResp.aeLd := io.mem.tlb_resp.ae.ld
  lamlet.io.tlbResp.aeSt := io.mem.tlb_resp.ae.st

  // Completion signals: Lamlet -> Shuttle
  io.com.retire_late := lamlet.io.com.retireLate
  io.com.inst := lamlet.io.com.inst
  io.com.pc := 0.U  // TODO: track PC
  io.com.xcpt := lamlet.io.com.xcpt
  io.com.cause := lamlet.io.com.cause
  io.com.tval := lamlet.io.com.tval
  io.com.rob_should_wb := false.B
  io.com.rob_should_wb_fp := false.B
  io.com.internal_replay := lamlet.io.com.internalReplay
  io.com.block_all := false.B
  io.com.scalar_check.ready := true.B

  // Kill signal
  lamlet.io.kill := io.mem.kill

  // Status signals
  io.trap_check_busy := !lamlet.io.ex.ready
  io.backend_busy := lamlet.io.backendBusy

  // CSR updates - not used yet
  io.set_vstart.valid := false.B
  io.set_vstart.bits := 0.U
  io.set_vxsat := false.B
  io.set_vconfig.valid := false.B
  io.set_vconfig.bits := DontCare
  io.set_fflags.valid := false.B
  io.set_fflags.bits := 0.U

  // Scalar response - not used yet
  io.resp.valid := false.B
  io.resp.bits := DontCare

  // ============================================================
  // TileLink interface for scalar memory
  // ============================================================

  // Convert our simple TileLink interface to diplomacy TileLink
  val tlGetReqQ = Module(new Queue(new TileLinkGetReq(zParams.memAddrWidth), 2))
  val tlPutReqQ = Module(new Queue(new TileLinkPutReq(zParams.memAddrWidth, zParams.wordWidth), 2))

  tlGetReqQ.io.enq <> lamlet.io.tlGetReq
  tlPutReqQ.io.enq <> lamlet.io.tlPutReq

  // Arbitrate between Get and Put
  val doGet = tlGetReqQ.io.deq.valid
  val doPut = tlPutReqQ.io.deq.valid && !doGet

  tlOut.a.valid := doGet || doPut
  tlOut.a.bits := Mux(doGet,
    tlEdge.Get(
      fromSource = 0.U,
      toAddress = tlGetReqQ.io.deq.bits.address,
      lgSize = tlGetReqQ.io.deq.bits.size
    )._2,
    tlEdge.Put(
      fromSource = 1.U,
      toAddress = tlPutReqQ.io.deq.bits.address,
      lgSize = tlPutReqQ.io.deq.bits.size,
      data = tlPutReqQ.io.deq.bits.data
    )._2
  )

  tlGetReqQ.io.deq.ready := tlOut.a.ready && doGet
  tlPutReqQ.io.deq.ready := tlOut.a.ready && doPut

  // Handle responses
  tlOut.d.ready := true.B

  // Route Get response to lamlet
  lamlet.io.tlGetResp.valid := tlOut.d.valid && tlOut.d.bits.source === 0.U
  lamlet.io.tlGetResp.bits.data := tlOut.d.bits.data
  lamlet.io.tlGetResp.bits.source := tlOut.d.bits.source
  lamlet.io.tlGetResp.bits.error := tlOut.d.bits.denied || tlOut.d.bits.corrupt

  // Route Put response to lamlet
  lamlet.io.tlPutResp.valid := tlOut.d.valid && tlOut.d.bits.source === 1.U
  lamlet.io.tlPutResp.bits := DontCare

  // ============================================================
  // Lamlet mesh output → KamletMesh north edge
  // ============================================================
  mesh.io.nChannelsIn(0)(0)(0) <> lamlet.io.mesh

  // Tie off other north edge inputs
  for (kX <- 0 until zParams.kCols) {
    for (jX <- 0 until zParams.jCols) {
      for (ch <- 0 until zParams.nAChannels + zParams.nBChannels) {
        if (!(kX == 0 && jX == 0 && ch == 0)) {
          mesh.io.nChannelsIn(kX)(jX)(ch).valid := false.B
          mesh.io.nChannelsIn(kX)(jX)(ch).bits := DontCare
        }
      }
    }
  }

  // North edge outputs: B channel at (0,0) → Lamlet.meshIn
  val bChannelIdx = zParams.nAChannels
  lamlet.io.meshIn <> mesh.io.nChannelsOut(0)(0)(bChannelIdx)

  // Tie off other north edge outputs
  for (kX <- 0 until zParams.kCols) {
    for (jX <- 0 until zParams.jCols) {
      for (ch <- 0 until zParams.nAChannels + zParams.nBChannels) {
        if (!(kX == 0 && jX == 0 && ch == bChannelIdx)) {
          mesh.io.nChannelsOut(kX)(jX)(ch).ready := false.B
        }
      }
    }
  }

  // ============================================================
  // Sync network: Lamlet ↔ KamletMesh
  // ============================================================
  mesh.io.nSyncN(0).in.valid := lamlet.io.syncPortSOut.valid
  mesh.io.nSyncN(0).in.bits := lamlet.io.syncPortSOut.bits
  lamlet.io.syncPortSIn.valid := mesh.io.nSyncN(0).out.valid
  lamlet.io.syncPortSIn.bits := mesh.io.nSyncN(0).out.bits

  // Tie off other sync ports
  for (kX <- 1 until zParams.kCols) {
    mesh.io.nSyncN(kX).in.valid := false.B
    mesh.io.nSyncN(kX).in.bits := 0.U
  }
  for (kX <- 0 until zParams.kCols) {
    mesh.io.nSyncNE(kX).in.valid := false.B
    mesh.io.nSyncNE(kX).in.bits := 0.U
    mesh.io.nSyncNW(kX).in.valid := false.B
    mesh.io.nSyncNW(kX).in.bits := 0.U
  }
  for (kX <- 0 until zParams.kCols) {
    mesh.io.sSyncS(kX).in.valid := false.B
    mesh.io.sSyncS(kX).in.bits := 0.U
    mesh.io.sSyncSE(kX).in.valid := false.B
    mesh.io.sSyncSE(kX).in.bits := 0.U
    mesh.io.sSyncSW(kX).in.valid := false.B
    mesh.io.sSyncSW(kX).in.bits := 0.U
  }
  for (kY <- 0 until zParams.kRows) {
    mesh.io.eSyncE(kY).in.valid := false.B
    mesh.io.eSyncE(kY).in.bits := 0.U
  }
  for (kY <- 0 until zParams.kRows - 1) {
    mesh.io.eSyncNE(kY).in.valid := false.B
    mesh.io.eSyncNE(kY).in.bits := 0.U
    mesh.io.eSyncSE(kY).in.valid := false.B
    mesh.io.eSyncSE(kY).in.bits := 0.U
  }
  for (kY <- 0 until zParams.kRows) {
    mesh.io.wSyncW(kY).in.valid := false.B
    mesh.io.wSyncW(kY).in.bits := 0.U
  }
  for (kY <- 0 until zParams.kRows - 1) {
    mesh.io.wSyncNW(kY).in.valid := false.B
    mesh.io.wSyncNW(kY).in.bits := 0.U
    mesh.io.wSyncSW(kY).in.valid := false.B
    mesh.io.wSyncSW(kY).in.bits := 0.U
  }

  // ============================================================
  // South edge (closed)
  // ============================================================
  for (kX <- 0 until zParams.kCols) {
    for (jX <- 0 until zParams.jCols) {
      for (ch <- 0 until zParams.nAChannels + zParams.nBChannels) {
        mesh.io.sChannelsIn(kX)(jX)(ch).valid := false.B
        mesh.io.sChannelsIn(kX)(jX)(ch).bits := DontCare
        mesh.io.sChannelsOut(kX)(jX)(ch).ready := false.B
      }
    }
  }

  // ============================================================
  // East/West edges - tie off for now (no memlet connection yet)
  // ============================================================
  for (kY <- 0 until zParams.kRows) {
    for (jY <- 0 until zParams.jRows) {
      for (ch <- 0 until zParams.nAChannels + zParams.nBChannels) {
        mesh.io.eChannelsIn(kY)(jY)(ch).valid := false.B
        mesh.io.eChannelsIn(kY)(jY)(ch).bits := DontCare
        mesh.io.eChannelsOut(kY)(jY)(ch).ready := false.B
        mesh.io.wChannelsIn(kY)(jY)(ch).valid := false.B
        mesh.io.wChannelsIn(kY)(jY)(ch).bits := DontCare
        mesh.io.wChannelsOut(kY)(jY)(ch).ready := false.B
      }
    }
  }
}
