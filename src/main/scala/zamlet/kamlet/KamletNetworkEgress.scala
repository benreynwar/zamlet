package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.network.NetworkWord

class KamletNetworkEgressIO(params: ZamletParams) extends Bundle {
  val memletPacketIn = Flipped(Decoupled(new NetworkWord(params)))
  val packetOut = Decoupled(new NetworkWord(params))
}

class KamletNetworkEgress(params: ZamletParams) extends Module {
  val io = IO(new KamletNetworkEgressIO(params))

  io.memletPacketIn.ready := false.B
  io.packetOut.valid := false.B
  io.packetOut.bits := DontCare
}
