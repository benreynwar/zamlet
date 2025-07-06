package fmvpu.alu

import chisel3._
import chisel3.util.{Valid, log2Ceil}
import fmvpu.core.{ComputeInstr, FMVPUParams}
import fmvpu.ModuleGenerator

class LaneALUResult(params: FMVPUParams) extends Bundle {
  val data = UInt(params.width.W)
  val dstAddr = UInt(log2Ceil(params.nDRF).W)
}

object LaneALU {
  val PIPELINE_LENGTH = 1
}

class LaneALU(params: FMVPUParams) extends Module {
  val io = IO(new Bundle {
    val instr = Input(Valid(new ComputeInstr(params)))
    val src1Data = Input(UInt(params.width.W))
    val src2Data = Input(UInt(params.width.W))
    val result = Output(Valid(new LaneALUResult(params)))
  })

  val resultData = Wire(UInt(params.width.W))
  
  when(io.instr.bits.mode === 0.U) {
    resultData := io.src1Data + io.src2Data
  }.elsewhen(io.instr.bits.mode === 1.U) {
    resultData := io.src1Data - io.src2Data
  }.elsewhen(io.instr.bits.mode === 2.U) {
    resultData := io.src1Data * io.src2Data
  }.otherwise {
    resultData := 0.U
  }
  
  // Pipeline the result and destination address by PIPELINE_LENGTH cycles
  val pipelinedData = (0 until LaneALU.PIPELINE_LENGTH).foldLeft(resultData)((data, _) => RegNext(data))
  val pipelinedValid = (0 until LaneALU.PIPELINE_LENGTH).foldLeft(io.instr.valid)((valid, _) => RegNext(valid))
  val pipelinedDstAddr = (0 until LaneALU.PIPELINE_LENGTH).foldLeft(io.instr.bits.dst)((addr, _) => RegNext(addr))
  
  io.result.bits.data := pipelinedData
  io.result.bits.dstAddr := pipelinedDstAddr
  io.result.valid := pipelinedValid
}

object LaneALUGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> LaneALU <paramsFileName>")
      return null
    }
    val params = FMVPUParams.fromFile(args(0))
    new LaneALU(params)
  }
}