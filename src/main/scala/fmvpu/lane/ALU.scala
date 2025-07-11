package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Basic ALU for Lane implementation
 * 
 * Supports Add, Sub, Mult, MultAcc operations with configurable pipeline latency.
 * Immediate variants use src2 as immediate value.
 * Maintains local accumulator for chained MultAcc operations.
 */
class ALU(params: LaneParams) extends Module {
  val io = IO(new Bundle {
    // Input instruction
    val instr = Input(Valid(new ALUInstrResolved(params)))
    
    // ALU result output
    val result = Output(new WriteResult(params))
  })


  // Local accumulator storage
  val localAccumulator = RegInit(0.U(params.width.W))
  
  // Determine which accumulator value to use
  val accumValue = Mux(io.instr.bits.useLocalAccum, localAccumulator, io.instr.bits.accum)

  // Compute ALU result
  val aluOut = Wire(UInt(params.width.W))
  
  aluOut := 0.U  // Default value
  switch(io.instr.bits.mode) {
    is(ALUModes.Add) {
      aluOut := io.instr.bits.src1 + io.instr.bits.src2
    }
    is(ALUModes.Addi) {
      aluOut := io.instr.bits.src1 + io.instr.bits.src2  // src2 is immediate
    }
    is(ALUModes.Sub) {
      aluOut := io.instr.bits.src1 - io.instr.bits.src2
    }
    is(ALUModes.Subi) {
      aluOut := io.instr.bits.src1 - io.instr.bits.src2  // src2 is immediate
    }
    is(ALUModes.Mult) {
      aluOut := io.instr.bits.src1 * io.instr.bits.src2
    }
    is(ALUModes.MultAcc) {
      aluOut := accumValue + (io.instr.bits.src1 * io.instr.bits.src2)
    }
  }

  // Update local accumulator when writing to accumulator register
  val isWritingToAccum = io.instr.valid && io.instr.bits.dstAddr.regAddr === params.accumRegAddr.U
  when (isWritingToAccum) {
    localAccumulator := aluOut
  }

  // Pipeline the result through the specified latency
  if (params.aluLatency == 1) {
    // Single cycle latency
    io.result.valid := io.instr.valid
    io.result.value := aluOut
    io.result.address := io.instr.bits.dstAddr
    io.result.force := false.B
  } else {
    // Multi-cycle pipeline
    val validPipe = Reg(Vec(params.aluLatency, Bool()))
    val resultPipe = Reg(Vec(params.aluLatency, UInt(params.width.W)))
    val dstAddrPipe = Reg(Vec(params.aluLatency, new RegWithIdent(params)))
    
    // Stage 0 (input)
    validPipe(0) := io.instr.valid
    resultPipe(0) := aluOut
    dstAddrPipe(0) := io.instr.bits.dstAddr
    
    // Pipeline stages 1 to latency-1
    for (i <- 1 until params.aluLatency) {
      validPipe(i) := validPipe(i-1)
      resultPipe(i) := resultPipe(i-1)
      dstAddrPipe(i) := dstAddrPipe(i-1)
    }
    
    // Output
    io.result.valid := validPipe(params.aluLatency-1)
    io.result.value := resultPipe(params.aluLatency-1)
    io.result.address := dstAddrPipe(params.aluLatency-1)
    io.result.force := false.B
  }
}

/** Generator object for creating ALU modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of ALU modules with configurable parameters.
  */
object ALUGenerator extends fmvpu.ModuleGenerator {
  /** Create an ALU module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return ALU module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> ALU <laneParamsFileName>")
      null
    } else {
      val params = LaneParams.fromFile(args(0))
      new ALU(params)
    }
  }
}