package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.utils.DoubleBuffer
import zamlet.utils.ValidBuffer

class SramIO(params: ZamletParams) extends Bundle {
  val jteReq = Flipped(Decoupled(new SramRequest(params)))
  val jteResp = Decoupled(params.word())
  val localReq = Flipped(Valid(new SramRequest(params)))
  val localResp = Valid(params.word())
}

class Sram(params: ZamletParams) extends Module {
  val io = IO(new SramIO(params))
  val sp = params.sramParams

  val memNext = Wire(Vec(params.sramDepth, params.word()))
  val mem = RegNext(memNext)
  memNext := mem

  val localAReq = ValidBuffer(io.localReq, sp.localA)
  val localAResp = Wire(Valid(params.word()))
  val localBResp = ValidBuffer(localAResp, sp.localB)
  io.localResp := ValidBuffer(localBResp, sp.localC)

  val jteAReq = DoubleBuffer(io.jteReq, sp.jteAFB, sp.jteABB)
  val jteAResp = Wire(Decoupled(params.word()))
  val jteBResp = DoubleBuffer(jteAResp, sp.jteBFB, sp.jteBBB)
  io.jteResp <> DoubleBuffer(jteBResp, sp.jteCFB, sp.jteCBB)


  val portValid = localAReq.valid || jteAReq.fire
  val portReq = Mux(localAReq.valid, localAReq.bits, jteAReq.bits)
  val portReadData = Mux(portReq.isWrite, 0.U, mem(portReq.address))

  when(portValid && portReq.isWrite) {
    memNext(portReq.address) := portReq.data
  }

  localAResp.valid := localAReq.valid
  localAResp.bits := portReadData

  jteAResp.valid := jteAReq.valid && !localAReq.valid
  jteAResp.bits := portReadData
  jteAReq.ready := jteAResp.ready && !localAReq.valid

}

/** Generator for Sram module */
object SramGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> Sram <zamletParamsFileName>")
      null
    } else {
      val params = ZamletParams.fromFile(args(0))
      new Sram(params)
    }
  }
}

object SramMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  SramGenerator.generate(outputDir, Seq(configFile))
}
