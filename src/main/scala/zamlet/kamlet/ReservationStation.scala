package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.{KInstr, KInstrBase, KInstrOpcode,
                       KinstrWithParams, LoadImmInstr, StoreScalarInstr,
                       WriteParamInstr}

class ReservationStationIO(params: ZamletParams) extends Bundle {
  val renamedIn = Flipped(Decoupled(UInt(KInstr.width.W)))

  // Ready local/immediate operations. Kamlet top-level merges this with KTE
  // localReplay before driving Jamlet immediateKinstr.
  val immediateKinstr = Vec(params.jInK, Valid(new KinstrWithParams(params)))

  // Ready long-latency operations handed to KTE.
  val kteIssue = Decoupled(new KteIssueReq(params))

  // Combinational conflict check against active KTE-owned work.
  val kteConflictCacheLineAddr = Output(params.cacheLineAddr())
  val kteConflict = Input(Bool())

  // Deterministic-latency cache lookup path for local memory operations.
  val kceClaimSlotReq = Valid(new KceClaimSlotReq(params))
  val kceClaimSlotResp = Flipped(Valid(new KceClaimSlotResp(params)))

  // Physical registers whose local/immediate lifetimes have ended.
  val rfRelease = Decoupled(params.rfAddr())
}

class ReservationStation(params: ZamletParams) extends Module {
  val io = IO(new ReservationStationIO(params))

  // Stores addresses, strides, and counts referenced by param indices in
  // kinstrs. This is first-pass decode behavior until the real RS table exists.
  val paramMemNumEntries = 1 << params.log2NParams
  val paramMemNext = Wire(Vec(paramMemNumEntries, UInt(params.memAddrWidth.W)))
  val paramMem = RegEnable(paramMemNext, VecInit(Seq.fill(paramMemNumEntries)(0.U(params.memAddrWidth.W))), true.B)
  paramMemNext := paramMem

  for (jInK <- 0 until params.jInK) {
    io.immediateKinstr(jInK).valid := false.B
    io.immediateKinstr(jInK).bits := DontCare
  }

  io.kteIssue.valid := false.B
  io.kteIssue.bits := DontCare
  io.kteConflictCacheLineAddr := 0.U

  io.kceClaimSlotReq.valid := false.B
  io.kceClaimSlotReq.bits := DontCare

  io.rfRelease.valid := false.B
  io.rfRelease.bits := DontCare

  val base = io.renamedIn.bits.asTypeOf(new KInstrBase(params))
  val loadImmInstr = io.renamedIn.bits.asTypeOf(new LoadImmInstr(params))
  val writeParamInstr = io.renamedIn.bits.asTypeOf(new WriteParamInstr(params))
  val storeScalarInstr = io.renamedIn.bits.asTypeOf(new StoreScalarInstr(params))

  val isSyncTrigger = base.opcode === KInstrOpcode.SyncTrigger
  val isIdentQuery = base.opcode === KInstrOpcode.IdentQuery
  val isLoadImm = base.opcode === KInstrOpcode.LoadImm
  val isWriteParam = base.opcode === KInstrOpcode.WriteParam
  val isStoreScalar = base.opcode === KInstrOpcode.StoreScalar
  val goesToKte = isSyncTrigger || isIdentQuery

  io.renamedIn.ready := !goesToKte || io.kteIssue.ready
  io.kteIssue.valid := io.renamedIn.valid && goesToKte
  io.kteIssue.bits.opType := KteOpType.Sync
  io.kteIssue.bits.kinstr.kinstr := io.renamedIn.bits
  io.kteIssue.bits.kinstr.ordering := DontCare
  io.kteIssue.bits.kinstr.cacheSlot := 0.U
  io.kteIssue.bits.kinstr.sramWordOffset := 0.U
  io.kteIssue.bits.kinstr.param0 := 0.U
  io.kteIssue.bits.kinstr.param1 := 0.U
  io.kteIssue.bits.kinstr.param2 := 0.U
  io.kteIssue.bits.cacheLineAddr := 0.U
  io.kteIssue.bits.willWrite := false.B

  // IdentQuery convention: param0 carries the RS snapshot of the oldest
  // active normal instr-ident distance from the query baseline. The first-pass
  // RS has no real table yet, so it contributes the no-active sentinel.
  when (isIdentQuery) {
    io.kteIssue.bits.kinstr.param0 := params.maxResponseTags.U
  }

  when (io.renamedIn.fire) {
    when (isLoadImm) {
      for (jInK <- 0 until params.jInK) {
        when (loadImmInstr.jInKIndex === jInK.U) {
          io.immediateKinstr(jInK).valid := true.B
          io.immediateKinstr(jInK).bits.kinstr := io.renamedIn.bits
          io.immediateKinstr(jInK).bits.cacheSlot := 0.U
          io.immediateKinstr(jInK).bits.sramWordOffset := 0.U
          io.immediateKinstr(jInK).bits.param0 := 0.U
          io.immediateKinstr(jInK).bits.param1 := 0.U
          io.immediateKinstr(jInK).bits.param2 := 0.U
        }
      }
    } .elsewhen (isWriteParam) {
      paramMemNext(writeParamInstr.paramIdx) := writeParamInstr.data
    } .elsewhen (isStoreScalar) {
      val scalarPaddr = paramMem(KInstr.baseAddrParamIdx(params, storeScalarInstr.scalarAddrParamIdx))
      for (jInK <- 0 until params.jInK) {
        io.immediateKinstr(jInK).valid := true.B
        io.immediateKinstr(jInK).bits.kinstr := io.renamedIn.bits
        io.immediateKinstr(jInK).bits.cacheSlot := 0.U
        io.immediateKinstr(jInK).bits.sramWordOffset := 0.U
        io.immediateKinstr(jInK).bits.param0 := scalarPaddr
        io.immediateKinstr(jInK).bits.param1 := 0.U
        io.immediateKinstr(jInK).bits.param2 := 0.U
      }
    }
  }
}
