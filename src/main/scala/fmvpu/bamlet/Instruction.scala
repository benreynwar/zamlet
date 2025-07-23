package fmvpu.bamlet

import chisel3._
import chisel3.util._
import fmvpu.amlet.{AmletParams, ALUInstr, ALULiteInstr, LoadStoreInstr, PacketInstr, ControlInstr}

object VLIWInstr {

  class Base(params: AmletParams) extends Bundle {
    val control = new ControlInstr.Base(params)
    val alu = new ALUInstr.Base(params)
    val aluLite = new ALULiteInstr.Base(params)
    val loadStore = new LoadStoreInstr.Base(params)
    val packet = new PacketInstr.Base(params)
  }

  class Resolving(params: AmletParams) extends Bundle {
    val control = new ControlInstr.Base(params)
    val alu = new ALUInstr.Resolving(params)
    val aluLite = new ALULiteInstr.Resolving(params)
    val loadStore = new LoadStoreInstr.Resolving(params)
    val packetSend = new PacketInstr.SendResolving(params)
    val packetReceive = new PacketInstr.ReceiveResolving(params)
  }

}

