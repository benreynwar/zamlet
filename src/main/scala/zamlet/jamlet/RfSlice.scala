package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.utils.DoubleBuffer

/**
 * RfSlice - Register file slice for a single jamlet
 *
 * Each jamlet holds a portion of the vector register file.
 * Size: rfSliceWords * wordBytes (default 48 * 8 = 384 bytes)
 *
 * Provides multiple Decoupled ports for concurrent access by different consumers:
 * - JTE: mask, index, data read ports and a byte-masked write port
 * - LocalExec: read/write port
 *
 * Reads are combinational. All ports can read concurrently.
 * All ports can write. Two ports writing to the same address results in DontCare.
 */
class RfSlice(params: ZamletParams) extends Module {
  val io = IO(new Bundle {
    // JTE read ports
    val maskReq = Flipped(Decoupled(new RfReq(params)))
    val maskResp = Decoupled(new RfResp(params))

    val indexReq = Flipped(Decoupled(new RfReq(params)))
    val indexResp = Decoupled(new RfResp(params))

    val dataReq = Flipped(Decoupled(new RfReq(params)))
    val dataResp = Decoupled(new RfResp(params))

    val jteWriteReq = Flipped(Decoupled(new RFWriteReq(params)))
    val jteWriteResp = Decoupled(Bool())

    // LocalExec port (read/write)
    val localExecReq = Flipped(Decoupled(new RfReq(params)))
    val localExecResp = Decoupled(new RfResp(params))
  })

  // Memory array - combinational read, registered write
  // Two ports writing to the same address simultaneously results in DontCare.
  val mem = Reg(Vec(params.rfSliceWords, UInt(params.wordWidth.W)))

  val rp = params.rfSliceParams

  // === Mask port ===
  // Request: io.maskReq (input) -> buffer -> maskReq (internal)
  val maskReq = DoubleBuffer(io.maskReq, rp.maskReqForwardBuffer, rp.maskReqBackwardBuffer)
  // Response: maskResp (internal) -> buffer -> io.maskResp (output)
  val maskResp = Wire(Decoupled(new RfResp(params)))
  io.maskResp <> DoubleBuffer(maskResp, rp.maskRespForwardBuffer, rp.maskRespBackwardBuffer)

  maskReq.ready := maskResp.ready || maskReq.bits.isWrite
  maskResp.valid := maskReq.valid && !maskReq.bits.isWrite
  maskResp.bits.readData := mem(maskReq.bits.addr)

  val maskWrite = maskReq.fire && maskReq.bits.isWrite

  // === Index port ===
  val indexReq = DoubleBuffer(io.indexReq, rp.indexReqForwardBuffer, rp.indexReqBackwardBuffer)
  val indexResp = Wire(Decoupled(new RfResp(params)))
  io.indexResp <> DoubleBuffer(indexResp, rp.indexRespForwardBuffer, rp.indexRespBackwardBuffer)

  indexReq.ready := indexResp.ready || indexReq.bits.isWrite
  indexResp.valid := indexReq.valid && !indexReq.bits.isWrite
  indexResp.bits.readData := mem(indexReq.bits.addr)

  val indexWrite = indexReq.fire && indexReq.bits.isWrite

  // === Data port ===
  val dataReq = DoubleBuffer(io.dataReq, rp.dataReqForwardBuffer, rp.dataReqBackwardBuffer)
  val dataResp = Wire(Decoupled(new RfResp(params)))
  io.dataResp <> DoubleBuffer(dataResp, rp.dataRespForwardBuffer, rp.dataRespBackwardBuffer)

  dataReq.ready := dataResp.ready || dataReq.bits.isWrite
  dataResp.valid := dataReq.valid && !dataReq.bits.isWrite
  dataResp.bits.readData := mem(dataReq.bits.addr)

  val dataWrite = dataReq.fire && dataReq.bits.isWrite

  // === JTE write port ===
  io.jteWriteReq.ready := io.jteWriteResp.ready
  io.jteWriteResp.valid := io.jteWriteReq.valid
  io.jteWriteResp.bits := true.B

  val jteWrite = io.jteWriteReq.fire
  val jteWriteMask = VecInit((0 until params.wordBytes).map { i =>
    Fill(8, io.jteWriteReq.bits.byteMask(i))
  }).asUInt

  // === LocalExec port ===
  val localExecReq = DoubleBuffer(io.localExecReq,
    rp.localExecReqForwardBuffer, rp.localExecReqBackwardBuffer)
  val localExecResp = Wire(Decoupled(new RfResp(params)))
  io.localExecResp <> DoubleBuffer(localExecResp,
    rp.localExecRespForwardBuffer, rp.localExecRespBackwardBuffer)

  localExecReq.ready := localExecResp.ready || localExecReq.bits.isWrite
  localExecResp.valid := localExecReq.valid && !localExecReq.bits.isWrite
  localExecResp.bits.readData := mem(localExecReq.bits.addr)

  val localExecWrite = localExecReq.fire && localExecReq.bits.isWrite

  // === Write logic with collision detection ===
  // Check for address collisions between all pairs of writers
  val maskCollision = maskWrite && (
    (indexWrite && maskReq.bits.addr === indexReq.bits.addr) ||
    (dataWrite && maskReq.bits.addr === dataReq.bits.addr) ||
    (localExecWrite && maskReq.bits.addr === localExecReq.bits.addr) ||
    (jteWrite && maskReq.bits.addr === io.jteWriteReq.bits.address))

  val indexCollision = indexWrite && (
    (maskWrite && indexReq.bits.addr === maskReq.bits.addr) ||
    (dataWrite && indexReq.bits.addr === dataReq.bits.addr) ||
    (localExecWrite && indexReq.bits.addr === localExecReq.bits.addr) ||
    (jteWrite && indexReq.bits.addr === io.jteWriteReq.bits.address))

  val dataCollision = dataWrite && (
    (maskWrite && dataReq.bits.addr === maskReq.bits.addr) ||
    (indexWrite && dataReq.bits.addr === indexReq.bits.addr) ||
    (localExecWrite && dataReq.bits.addr === localExecReq.bits.addr) ||
    (jteWrite && dataReq.bits.addr === io.jteWriteReq.bits.address))

  val localExecCollision = localExecWrite && (
    (maskWrite && localExecReq.bits.addr === maskReq.bits.addr) ||
    (indexWrite && localExecReq.bits.addr === indexReq.bits.addr) ||
    (dataWrite && localExecReq.bits.addr === dataReq.bits.addr) ||
    (jteWrite && localExecReq.bits.addr === io.jteWriteReq.bits.address))

  val jteCollision = jteWrite && (
    (maskWrite && io.jteWriteReq.bits.address === maskReq.bits.addr) ||
    (indexWrite && io.jteWriteReq.bits.address === indexReq.bits.addr) ||
    (dataWrite && io.jteWriteReq.bits.address === dataReq.bits.addr) ||
    (localExecWrite && io.jteWriteReq.bits.address === localExecReq.bits.addr))

  when(maskWrite) {
    mem(maskReq.bits.addr) := Mux(maskCollision, DontCare, maskReq.bits.writeData)
  }
  when(indexWrite) {
    mem(indexReq.bits.addr) := Mux(indexCollision, DontCare, indexReq.bits.writeData)
  }
  when(dataWrite) {
    mem(dataReq.bits.addr) := Mux(dataCollision, DontCare, dataReq.bits.writeData)
  }
  when(localExecWrite) {
    mem(localExecReq.bits.addr) := Mux(localExecCollision, DontCare, localExecReq.bits.writeData)
  }
  when(jteWrite) {
    val oldData = mem(io.jteWriteReq.bits.address)
    val newData = (oldData & ~jteWriteMask) | (io.jteWriteReq.bits.data & jteWriteMask)
    mem(io.jteWriteReq.bits.address) := Mux(jteCollision, DontCare, newData)
  }
}

/** Generator for RfSlice module */
object RfSliceGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> RfSlice <zamletParamsFileName>")
      null
    } else {
      val params = ZamletParams.fromFile(args(0))
      new RfSlice(params)
    }
  }
}

object RfSliceMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  RfSliceGenerator.generate(outputDir, Seq(configFile))
}
