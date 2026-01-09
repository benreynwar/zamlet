package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.LamletParams
import zamlet.jamlet.{KInstrOpcode, KInstrBase, SyncTriggerInstr}

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
  })

  // Default outputs
  io.kinstrIn.ready := true.B
  io.syncLocalEvent.valid := false.B
  io.syncLocalEvent.bits.syncIdent := 0.U
  io.syncLocalEvent.bits.value := 0.U

  when (io.kinstrIn.fire) {
    val base = io.kinstrIn.bits.asTypeOf(new KInstrBase)

    switch (base.opcode) {
      is (KInstrOpcode.SyncTrigger) {
        val instr = io.kinstrIn.bits.asTypeOf(new SyncTriggerInstr)
        io.syncLocalEvent.valid := true.B
        io.syncLocalEvent.bits.syncIdent := instr.syncIdent
        io.syncLocalEvent.bits.value := instr.value
      }
    }
  }
}
