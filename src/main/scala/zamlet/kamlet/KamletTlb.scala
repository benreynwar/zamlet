package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.JamletTlbResp
import zamlet.network.NetworkWord

class KamletTlbIO(params: ZamletParams) extends Bundle {
  val tlbReq = Vec(params.jInK, Flipped(Decoupled(UInt(params.memStripeAddrWidth.W))))
  val tlbResp = Vec(params.jInK, Decoupled(new JamletTlbResp(params)))

  val packetOut = Decoupled(new NetworkWord(params))
  val packetIn = Flipped(Decoupled(new NetworkWord(params)))
}

class KamletTlb(params: ZamletParams) extends Module {
  val io = IO(new KamletTlbIO(params))

  for (jInK <- 0 until params.jInK) {
    io.tlbReq(jInK).ready := false.B
    io.tlbResp(jInK).valid := false.B
    io.tlbResp(jInK).bits := DontCare
  }

  io.packetOut.valid := false.B
  io.packetOut.bits := DontCare
  io.packetIn.ready := false.B
}
