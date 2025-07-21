package fmvpu.amlet

import chisel3._
import chisel3.util._

object Instr {
  abstract class Base(params: AmletParams) extends Bundle
  abstract class Resolved(params: AmletParams) extends Bundle
  abstract class Resolving(params: AmletParams) extends Bundle {
    def isResolved(): Bool
    def resolve(): Resolved
    def isMasked(): Bool
    def update(writes: WriteBacks): Resolving
  }
}

class VLIWInstruction(params: AmletParams) extends Bundle {
  val alu = new ALUInstr.Base(params)
  val aluLite = new ALULiteInstr.Base(params)
  val loadStore = new LoadStoreInstr.Base(params)
  val packet = new PacketInstr.Base(params)
}

class VLIWResolving(params: AmletParams) extends Bundle {
  val alu = new ALUInstr.Resolving(params)
  val aluLite = new ALULiteInstr.Resolving(params)
  val loadStore = new LoadStoreInstr.Resolving(params)
  val packetSend = new PacketInstr.SendResolving(params)
  val packetReceive = new PacketInstr.ReceiveResolving(params)
}

