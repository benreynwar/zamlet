package fmvpu.famlet

import chisel3._
import chisel3.util._

object Instr {
  // The instruction stored in the instruction memory.
  abstract class Base(params: FamletParams) extends Bundle
  // The instruction after processing by the Control (Gamlet level)
  abstract class Expanded(params: FamletParams) extends Bundle
  // The instruction after processing by the Rename (Gamlet level)
  abstract class Renamed(params: FamletParams) extends Bundle
  // The instruction during processing by Scoreboard (Famlet Level)
  abstract class Resolving(params: FamletParams) extends Bundle {
    def isResolved(): Bool
    def resolve(): Resolved
    def update(writes: ResultBus): Resolving
  }
  // The instruction after processing by a Scoreboard
  abstract class AlmostResolved(params: FamletParams) extends Bundle
  // The instruction after processing by a RegisterFile
  abstract class Resolved(params: FamletParams) extends Bundle
}

object VLIWInstr {

  class Base(params: FamletParams) extends Bundle {
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

  class Expanded(params: FamletParams) extends Bundle {
    val control = new ControlInstr.Expanded(params)
    val predicate = new PredicateInstr.Expanded(params)
    val alu = new ALUInstr.Expanded(params)
    val aluLite = new ALULiteInstr.Expanded(params)
    val loadStore = new LoadStoreInstr.Expanded(params)
    val packet = new PacketInstr.Expanded(params)
  }

  class Renamed(params: FamletParams) extends Bundle {
    val control = new ControlInstr.Renamed(params)
    val predicate = new PredicateInstr.Renamed(params)
    val alu = new ALUInstr.Renamed(params)
    val aluLite = new ALULiteInstr.Renamed(params)
    val loadStore = new LoadStoreInstr.Renamed(params)
    val packet = new PacketInstr.Renamed(params)
  }

  class Resolving(params: FamletParams) extends Bundle {
    val predicate = new PredicateInstr.Resolving(params)
    val alu = new ALUInstr.Resolving(params)
    val aluLite = new ALULiteInstr.Resolving(params)
    val loadStore = new LoadStoreInstr.Resolving(params)
    val packetSend = new PacketInstr.SendResolving(params)
    val packetReceive = new PacketInstr.ReceiveResolving(params)
  }

}
