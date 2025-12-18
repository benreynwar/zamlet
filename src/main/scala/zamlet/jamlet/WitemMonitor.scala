package zamlet.jamlet

import chisel3._
import chisel3.util._

class WitemMonitor(params: JamletParams) extends Module {
  val io = IO(new Bundle {
    // Position
    val thisX = Input(params.xPos())
    val thisY = Input(params.yPos())

    // From Kamlet (witem lifecycle)
    val witemCreate = Flipped(Valid(new WitemCreate(params)))
    val witemCacheAvail = Flipped(Valid(params.ident()))
    val witemRemove = Flipped(Valid(params.ident()))
    val witemComplete = Valid(params.ident())

    // Witem info lookup (to KamletWitemTable)
    val witemInfoReq = Valid(new WitemInfoReq(params))
    val witemInfoResp = Flipped(Valid(new WitemInfoResp(params)))

    // State updates from RX handlers
    val witemSrcUpdate = Flipped(Valid(new WitemSrcUpdate(params)))
    val witemDstUpdate = Flipped(Valid(new WitemDstUpdate(params)))

    // Sync interface to KamletWitemTable
    val witemFaultReady = Valid(new WitemFaultReady(params))
    val witemCompleteReady = Valid(params.ident())
    val witemFaultSync = Flipped(Valid(new WitemFaultSync(params)))
    val witemCompletionSync = Flipped(Valid(new WitemCompletionSync(params)))

    // TLB interface
    val tlbReq = Valid(new TlbReq(params))
    val tlbResp = Flipped(Valid(new TlbResp(params)))

    // SRAM interface
    val sramReq = Decoupled(new SramReq(params))
    val sramResp = Flipped(Valid(new SramResp(params)))

    // RF interface
    val rfReq = Decoupled(new RfReq(params))
    val rfResp = Flipped(Valid(new RfResp(params)))

    // Packet output to arbiter
    val packetOut = Decoupled(new NetworkWord(params))
  })

  // Entry table
  val entries = Reg(Vec(params.witemTableDepth, new WitemEntry(params)))
  val nextPriority = RegInit(0.U(log2Ceil(params.witemTableDepth + 1).W))

  // TODO: Pipeline stages and logic

  // Temporary tie-offs
  io.witemComplete.valid := false.B
  io.witemComplete.bits := DontCare
  io.witemInfoReq.valid := false.B
  io.witemInfoReq.bits := DontCare
  io.witemFaultReady.valid := false.B
  io.witemFaultReady.bits := DontCare
  io.witemCompleteReady.valid := false.B
  io.witemCompleteReady.bits := DontCare
  io.tlbReq.valid := false.B
  io.tlbReq.bits := DontCare
  io.sramReq.valid := false.B
  io.sramReq.bits := DontCare
  io.rfReq.valid := false.B
  io.rfReq.bits := DontCare
  io.packetOut.valid := false.B
  io.packetOut.bits := DontCare
}
