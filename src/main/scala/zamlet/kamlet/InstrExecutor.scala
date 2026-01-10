package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.LamletParams
import zamlet.jamlet.{KInstr, KInstrOpcode, KInstrBase, KInstrParamIdx, SyncTriggerInstr,
                       IdentQueryInstr, LoadImmInstr, WriteParamInstr, KinstrWithParams,
                       StoreScalarInstr}

/**
 * InstrExecutor decodes kinstrs and executes them.
 *
 * For Test 0 (minimal): Only handles SyncTrigger instruction.
 * Later phases add: IdentQuery, LoadSimple, StoreSimple, dispatch to jamlets, etc.
 */
class InstrExecutor(params: LamletParams) extends Module {
  val io = IO(new Bundle {
    // Kinstr input (from InstrQueue)
    val kinstrIn = Flipped(Decoupled(UInt(64.W)))

    // Sync trigger output (to Synchronizer)
    val syncLocalEvent = Valid(new SyncEvent)

    // Immediate kinstr dispatch to jamlets (one per jamlet in kamlet)
    val immediateKinstr = Vec(params.jInK, Valid(new KinstrWithParams(params)))
  })

  // Parameter memory: 16 entries x memAddrWidth bits
  // Stores addresses, strides, nElements referenced by 4-bit indices in kinstrs
  val paramMemNumEntries = 1 << KInstrParamIdx.width  // 16
  val paramMem = RegInit(VecInit(Seq.fill(paramMemNumEntries)(0.U(params.memAddrWidth.W))))

  // Default outputs
  io.kinstrIn.ready := true.B
  io.syncLocalEvent.valid := false.B
  io.syncLocalEvent.bits.syncIdent := 0.U
  io.syncLocalEvent.bits.value := 0.U
  for (j <- 0 until params.jInK) {
    io.immediateKinstr(j).valid := false.B
    io.immediateKinstr(j).bits := DontCare
  }

  when (io.kinstrIn.fire) {
    val base = io.kinstrIn.bits.asTypeOf(new KInstrBase)

    switch (base.opcode) {
      is (KInstrOpcode.SyncTrigger) {
        val instr = io.kinstrIn.bits.asTypeOf(new SyncTriggerInstr)
        io.syncLocalEvent.valid := true.B
        io.syncLocalEvent.bits.syncIdent := instr.syncIdent
        io.syncLocalEvent.bits.value := instr.value
      }
      is (KInstrOpcode.IdentQuery) {
        val instr = io.kinstrIn.bits.asTypeOf(new IdentQueryInstr)
        // Kamlet reports distance from baseline to oldest active ident.
        // For now (no waiting item tracking), report all idents free.
        // TODO: Compute real distance when waiting item table is implemented.
        io.syncLocalEvent.valid := true.B
        io.syncLocalEvent.bits.syncIdent := instr.syncIdent
        io.syncLocalEvent.bits.value := params.maxResponseTags.U
      }
      is (KInstrOpcode.LoadImm) {
        val instr = io.kinstrIn.bits.asTypeOf(new LoadImmInstr(params))
        // Dispatch to the target jamlet
        for (j <- 0 until params.jInK) {
          when (instr.jInKIndex === j.U) {
            io.immediateKinstr(j).valid := true.B
            io.immediateKinstr(j).bits.kinstr := io.kinstrIn.bits
            io.immediateKinstr(j).bits.param0 := 0.U
            io.immediateKinstr(j).bits.param1 := 0.U
            io.immediateKinstr(j).bits.param2 := 0.U
          }
        }
      }
      is (KInstrOpcode.WriteParam) {
        val instr = io.kinstrIn.bits.asTypeOf(new WriteParamInstr)
        paramMem(instr.paramIdx) := instr.data
      }
      is (KInstrOpcode.StoreScalar) {
        val instr = io.kinstrIn.bits.asTypeOf(new StoreScalarInstr(params))
        val basePaddr = paramMem(instr.baseAddrIdx)

        // Broadcast to all jamlets - each jamlet determines if it has an active element
        // and computes its own paddr from basePaddr + element_index * 8
        for (j <- 0 until params.jInK) {
          io.immediateKinstr(j).valid := true.B
          io.immediateKinstr(j).bits.kinstr := io.kinstrIn.bits
          io.immediateKinstr(j).bits.param0 := basePaddr
          io.immediateKinstr(j).bits.param1 := 0.U
          io.immediateKinstr(j).bits.param2 := 0.U
        }
      }
    }
  }
}
