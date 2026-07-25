package zamlet.jamlet

import chisel3._
import chisel3.experimental.ExtModule
import chisel3.util._
import zamlet.ZamletParams
import zamlet.utils.DoubleBuffer
import zamlet.utils.ValidBuffer

class SramIO(params: ZamletParams) extends Bundle {
  val req = Flipped(Valid(new SramRequest(params)))
  val resp = Valid(params.word())
}

class SramWrapperIO(params: ZamletParams) extends Bundle {
  val jteReq = Flipped(Decoupled(new SramRequest(params)))
  val jteResp = Decoupled(params.word())
  val jceReadReq = Flipped(Decoupled(UInt(params.sramAddrWidth.W)))
  val jceReadResp = Decoupled(params.word())
  val jceWriteReq = Flipped(Decoupled(new SramWriteRequest(params)))
  val jceWriteResp = Decoupled()
  val localReq = Flipped(Valid(new SramRequest(params)))
  val localResp = Valid(params.word())
}

object SramAccessSource extends ChiselEnum {
  val Local, Jte, JceWrite, JceRead = Value
}

class SramAccessTransaction(params: ZamletParams) extends Bundle {
  val source = SramAccessSource()
  val req = new SramRequest(params)
}

class SramAccessResponse(params: ZamletParams) extends Bundle {
  val source = SramAccessSource()
  val data = params.word()
}

class Sram(params: ZamletParams) extends Module {
  val io = IO(new SramIO(params))

  val memNext = Wire(Vec(params.sramDepth, params.word()))
  val mem = RegNext(memNext)
  memNext := mem

  val readData = Mux(io.req.bits.isWrite, 0.U, mem(io.req.bits.address))

  io.resp.valid := RegNext(io.req.valid, false.B)
  io.resp.bits := RegEnable(readData, io.req.valid)

  when(io.req.valid && io.req.bits.isWrite) {
    val oldData = mem(io.req.bits.address)
    memNext(io.req.bits.address) :=
      (oldData & ~io.req.bits.writeMask) | (io.req.bits.data & io.req.bits.writeMask)
  }
}

class SramHardMacro(params: ZamletParams) extends ExtModule {
  override val desiredName = "Sram"

  val clock = IO(Input(Clock()))
  val reset = IO(Input(Bool()))
  val io = IO(new SramIO(params))
}

class SramWrapper(params: ZamletParams, useHardMacro: Boolean = false) extends Module {
  val io = IO(new SramWrapperIO(params))
  val sp = params.sramParams

  val localAReq = ValidBuffer(io.localReq, sp.localA)
  val localAResp = Wire(Valid(params.word()))
  val localBResp = ValidBuffer(localAResp, sp.localB)
  io.localResp := ValidBuffer(localBResp, sp.localC)

  val jteAReq = DoubleBuffer(io.jteReq, sp.jteAFB, sp.jteABB)
  val jteAResp = Wire(Decoupled(params.word()))
  val jteBResp = DoubleBuffer(jteAResp, sp.jteBFB, sp.jteBBB)
  io.jteResp <> DoubleBuffer(jteBResp, sp.jteCFB, sp.jteCBB)

  val jceReadAReq = io.jceReadReq
  val jceReadAResp = Wire(Decoupled(params.word()))
  io.jceReadResp <> jceReadAResp

  val jceWriteAReq = io.jceWriteReq
  val jceWriteAResp = Wire(Decoupled())
  io.jceWriteResp <> jceWriteAResp

  val sramIo = if (useHardMacro) {
    val sram = Module(new SramHardMacro(params))
    sram.clock := clock
    sram.reset := reset.asBool
    sram.io
  } else {
    Module(new Sram(params)).io
  }

  val decoupledRespSkidNext = Wire(Valid(new SramAccessResponse(params)))
  val decoupledRespSkid =
    RegNext(decoupledRespSkidNext, 0.U.asTypeOf(Valid(new SramAccessResponse(params))))

  val sram0JteSelected = !localAReq.valid && jteAReq.valid
  val sram0JceWriteSelected = !localAReq.valid && !jteAReq.valid && jceWriteAReq.valid
  val sram0JceReadSelected =
    !localAReq.valid && !jteAReq.valid && !jceWriteAReq.valid && jceReadAReq.valid

  val sram0Txn = Wire(new SramAccessTransaction(params))
  sram0Txn.source := SramAccessSource.Local
  sram0Txn.req := localAReq.bits
  when(sram0JteSelected) {
    sram0Txn.source := SramAccessSource.Jte
    sram0Txn.req := jteAReq.bits
  }.elsewhen(sram0JceWriteSelected) {
    sram0Txn.source := SramAccessSource.JceWrite
    sram0Txn.req.address := jceWriteAReq.bits.address
    sram0Txn.req.isWrite := true.B
    sram0Txn.req.data := jceWriteAReq.bits.data
    sram0Txn.req.writeMask := Fill(params.wordWidth, true.B)
  }.elsewhen(sram0JceReadSelected) {
    sram0Txn.source := SramAccessSource.JceRead
    sram0Txn.req.address := jceReadAReq.bits
    sram0Txn.req.isWrite := false.B
    sram0Txn.req.data := DontCare
    sram0Txn.req.writeMask := DontCare
  }

  val sram2Source = RegEnable(sram0Txn.source, sramIo.req.valid)
  val sram2IsDecoupled = sramIo.resp.valid && sram2Source =/= SramAccessSource.Local

  val sram2DecoupledReady = MuxLookup(sram2Source.asUInt, true.B)(Seq(
    SramAccessSource.Jte.asUInt -> jteAResp.ready,
    SramAccessSource.JceWrite.asUInt -> jceWriteAResp.ready,
    SramAccessSource.JceRead.asUInt -> jceReadAResp.ready,
  ))
  val decoupledRespSkidWillFill =
    sram2IsDecoupled && !sram2DecoupledReady && !decoupledRespSkid.valid
  val sram0CanIssueDecoupled = !decoupledRespSkid.valid && !decoupledRespSkidWillFill

  val sram0SelectedIsDecoupled = sram0JteSelected || sram0JceWriteSelected || sram0JceReadSelected
  val sram0Fire = localAReq.valid || (sram0SelectedIsDecoupled && sram0CanIssueDecoupled)
  sramIo.req.valid := sram0Fire
  sramIo.req.bits := sram0Txn.req

  jteAReq.ready := sram0JteSelected && sram0CanIssueDecoupled
  jceWriteAReq.ready := sram0JceWriteSelected && sram0CanIssueDecoupled
  jceReadAReq.ready := sram0JceReadSelected && sram0CanIssueDecoupled

  localAResp.valid := sramIo.resp.valid && sram2Source === SramAccessSource.Local
  localAResp.bits := sramIo.resp.bits

  val decoupledRespSource = Mux(decoupledRespSkid.valid, decoupledRespSkid.bits.source, sram2Source)
  val decoupledRespData = Mux(decoupledRespSkid.valid, decoupledRespSkid.bits.data, sramIo.resp.bits)
  val decoupledRespValid = decoupledRespSkid.valid || sram2IsDecoupled

  jteAResp.valid := decoupledRespValid && decoupledRespSource === SramAccessSource.Jte
  jteAResp.bits := decoupledRespData

  jceWriteAResp.valid := decoupledRespValid && decoupledRespSource === SramAccessSource.JceWrite

  jceReadAResp.valid := decoupledRespValid && decoupledRespSource === SramAccessSource.JceRead
  jceReadAResp.bits := decoupledRespData

  val decoupledRespReady = MuxLookup(decoupledRespSource.asUInt, true.B)(Seq(
    SramAccessSource.Jte.asUInt -> jteAResp.ready,
    SramAccessSource.JceWrite.asUInt -> jceWriteAResp.ready,
    SramAccessSource.JceRead.asUInt -> jceReadAResp.ready,
  ))
  val decoupledRespSkidFire = decoupledRespSkid.valid && decoupledRespReady

  decoupledRespSkidNext.valid := Mux(decoupledRespSkidWillFill, true.B,
    Mux(decoupledRespSkidFire, false.B, decoupledRespSkid.valid))
  decoupledRespSkidNext.bits.source :=
    Mux(decoupledRespSkidWillFill, sram2Source, decoupledRespSkid.bits.source)
  decoupledRespSkidNext.bits.data :=
    Mux(decoupledRespSkidWillFill, sramIo.resp.bits, decoupledRespSkid.bits.data)
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
