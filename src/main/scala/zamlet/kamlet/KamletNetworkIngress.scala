package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.network.NetworkWord

class KamletNetworkIngressIO(params: ZamletParams) extends Bundle {
  val packetIn = Flipped(Decoupled(new NetworkWord(params)))
  val memletPacketOut = Decoupled(new NetworkWord(params))
}

class KamletNetworkIngress(params: ZamletParams) extends Module {
  val io = IO(new KamletNetworkIngressIO(params))

  io.packetIn.ready := false.B
  io.memletPacketOut.valid := false.B
  io.memletPacketOut.bits := DontCare
}
