package fmvpu.amlet

import chisel3._
import chisel3.util._

object Instr {
  // The instruction stored in the instruction memory.
  abstract class Base(params: AmletParams) extends Bundle
  // The instruction after processing by the Control (Bamlet level)
  abstract class Expanded(params: AmletParams) extends Bundle {
    def getTReads(): Seq[Valid[UInt]]
    def getTWrites(): Seq[Valid[UInt]]
    }
  // The instruction after processing by RegisterAndRename (Amlet Level)
  abstract class Resolving(params: AmletParams) extends Bundle {
    def isResolved(): Bool
    def resolve(): Resolved
    def update(writes: ResultBus): Resolving
  }
  // The instruction after processing by a ReservationState
  abstract class Resolved(params: AmletParams) extends Bundle
}

object VLIWInstr {

  class Base(params: AmletParams) extends Bundle {
    val control = new ControlInstr.Base(params)
    val predicate = new PredicateInstr.Base(params)
    val alu = new ALUInstr.Base(params)
    val aluLite = new ALULiteInstr.Base(params)
    val loadStore = new LoadStoreInstr.Base(params)
    val packet = new PacketInstr.Base(params)

    def expand(): Expanded = {
      val expanded = Wire(new Expanded(params))
      expanded.control := control.expand()
      expanded.predicate := predicate.expand()
      expanded.alu := alu.expand()
      expanded.aluLite := aluLite.expand()
      expanded.loadStore := loadStore.expand()
      expanded.packet := packet.expand()
      expanded
    }
  }

  class Expanded(params: AmletParams) extends Bundle {
    val control = new ControlInstr.Expanded(params)
    val predicate = new PredicateInstr.Expanded(params)
    val alu = new ALUInstr.Expanded(params)
    val aluLite = new ALULiteInstr.Expanded(params)
    val loadStore = new LoadStoreInstr.Expanded(params)
    val packet = new PacketInstr.Expanded(params)
  }

  class Resolving(params: AmletParams) extends Bundle {
    val predicate = new PredicateInstr.Resolving(params)
    val alu = new ALUInstr.Resolving(params)
    val aluLite = new ALULiteInstr.Resolving(params)
    val loadStore = new LoadStoreInstr.Resolving(params)
    val packetSend = new PacketInstr.SendResolving(params)
    val packetReceive = new PacketInstr.ReceiveResolving(params)
  }

}
