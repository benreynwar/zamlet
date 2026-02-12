package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams

class CombinedNetworkNodeIO(params: ZamletParams) extends Bundle {
  val thisX = Input(UInt(params.xPosWidth.W))
  val thisY = Input(UInt(params.yPosWidth.W))

  // A channel network interfaces
  val aNi = Vec(params.nAChannels, Flipped(Decoupled(new NetworkWord(params))))
  val aSi = Vec(params.nAChannels, Flipped(Decoupled(new NetworkWord(params))))
  val aEi = Vec(params.nAChannels, Flipped(Decoupled(new NetworkWord(params))))
  val aWi = Vec(params.nAChannels, Flipped(Decoupled(new NetworkWord(params))))
  val aNo = Vec(params.nAChannels, Decoupled(new NetworkWord(params)))
  val aSo = Vec(params.nAChannels, Decoupled(new NetworkWord(params)))
  val aEo = Vec(params.nAChannels, Decoupled(new NetworkWord(params)))
  val aWo = Vec(params.nAChannels, Decoupled(new NetworkWord(params)))
  val aHi = Flipped(Decoupled(new NetworkWord(params)))
  val aHo = Decoupled(new NetworkWord(params))

  // B channel network interfaces
  val bNi = Vec(params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))
  val bSi = Vec(params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))
  val bEi = Vec(params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))
  val bWi = Vec(params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))
  val bNo = Vec(params.nBChannels, Decoupled(new NetworkWord(params)))
  val bSo = Vec(params.nBChannels, Decoupled(new NetworkWord(params)))
  val bEo = Vec(params.nBChannels, Decoupled(new NetworkWord(params)))
  val bWo = Vec(params.nBChannels, Decoupled(new NetworkWord(params)))
  val bHi = Flipped(Decoupled(new NetworkWord(params)))
  val bHo = Decoupled(new NetworkWord(params))
}

class CombinedNetworkNode(params: ZamletParams) extends Module {
  val io = IO(new CombinedNetworkNodeIO(params))

  val aNetworkNode = Module(new NetworkNode(params, params.nAChannels))
  val bNetworkNode = Module(new NetworkNode(params, params.nBChannels))

  aNetworkNode.io.thisX := io.thisX
  aNetworkNode.io.thisY := io.thisY
  aNetworkNode.io.ni <> io.aNi
  aNetworkNode.io.no <> io.aNo
  aNetworkNode.io.si <> io.aSi
  aNetworkNode.io.so <> io.aSo
  aNetworkNode.io.ei <> io.aEi
  aNetworkNode.io.eo <> io.aEo
  aNetworkNode.io.wi <> io.aWi
  aNetworkNode.io.wo <> io.aWo
  aNetworkNode.io.hi <> io.aHi
  io.aHo <> aNetworkNode.io.ho

  bNetworkNode.io.thisX := io.thisX
  bNetworkNode.io.thisY := io.thisY
  bNetworkNode.io.ni <> io.bNi
  bNetworkNode.io.no <> io.bNo
  bNetworkNode.io.si <> io.bSi
  bNetworkNode.io.so <> io.bSo
  bNetworkNode.io.ei <> io.bEi
  bNetworkNode.io.eo <> io.bEo
  bNetworkNode.io.wi <> io.bWi
  bNetworkNode.io.wo <> io.bWo
  bNetworkNode.io.hi <> io.bHi
  io.bHo <> bNetworkNode.io.ho
}

object CombinedNetworkNodeGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> CombinedNetworkNode <configFile>")
      null
    } else {
      val params = ZamletParams.fromFile(args(0))
      new CombinedNetworkNode(params)
    }
  }
}

object CombinedNetworkNodeMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  CombinedNetworkNodeGenerator.generate(args(0), Seq(args(1)))
}
