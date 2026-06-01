package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.network.{INetworkWord, NetworkWord, PacketIHeader}

class INetworkWordToNetworkWordIO(params: ZamletParams) extends Bundle {
  val in = Flipped(Decoupled(new INetworkWord(params)))
  val out = Decoupled(new NetworkWord(params))
}

class INetworkWordToNetworkWord(params: ZamletParams) extends Module {
  val io = IO(new INetworkWordToNetworkWordIO(params))

  val inputHeader = io.in.bits.data.asTypeOf(new PacketIHeader(params))
  val laneIndexToCoords = Module(new LaneIndexToCoords(params))
  laneIndexToCoords.io.laneIndex := inputHeader.dstIndex(params.log2JInL - 1, 0)
  laneIndexToCoords.io.laneOrder := io.in.bits.laneOrder

  val suffixWidth = params.wordWidth - (params.xPosWidth + params.yPosWidth)
  val suffix = io.in.bits.data(suffixWidth - 1, 0)
  val convertedHeader = Cat(laneIndexToCoords.io.x, laneIndexToCoords.io.y, suffix)

  io.out.valid := io.in.valid
  io.out.bits.isHeader := io.in.bits.isHeader
  io.out.bits.data := Mux(io.in.bits.isHeader, convertedHeader, io.in.bits.data)
  io.in.ready := io.out.ready
}
