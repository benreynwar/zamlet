package fmvpu.amlet

import chisel3._
import chisel3.util._

/**
 * ALU for Amlet implementation
 * 
 * Receives resolved ALU instructions from ALURS and produces write results.
 * Supports arithmetic and logical operations with configurable pipeline latency.
 * 
 * Supported Operations:
 * - Add: Addition of two data registers
 * - Addi: Addition with immediate value
 * - Sub: Subtraction of two data registers  
 * - Subi: Subtraction with immediate value
 * - Mult: Multiplication of two data registers
 * - MultAcc: Multiply-accumulate operation
 * - Eq, Gte, Lte: Comparison operations
 * - Not, And, Or: Logical operations
 * - ShiftL, ShiftR: Shift operations
 */
class ALU(params: AmletParams) extends Module {
  val io = IO(new Bundle {
    // Input instruction from ALURS
    val instr = Input(Valid(new ALUInstr.Resolved(params)))
    
    // ALU result output
    val result = Output(Valid(new WriteResult(params)))
  })

  // Shift amount bit range for data width operations
  private val shiftBits = log2Ceil(params.width) - 1

  // Compute ALU result
  val aluOut = Wire(UInt(params.width.W))

  // Accumulator
  val accNext = Wire(UInt(params.width.W))
  val acc = RegNext(accNext, 0.U)
  
  aluOut := 0.U  // Default value
  accNext := acc  // Default: preserve accumulator value
  
  switch(io.instr.bits.mode) {
    is(ALUInstr.Modes.None) {
      aluOut := 0.U
    }
    is(ALUInstr.Modes.Add) {
      aluOut := io.instr.bits.src1 + io.instr.bits.src2
    }
    is(ALUInstr.Modes.Addi) {
      aluOut := io.instr.bits.src1 + io.instr.bits.src2  // src2 is immediate
    }
    is(ALUInstr.Modes.Sub) {
      aluOut := io.instr.bits.src1 - io.instr.bits.src2
    }
    is(ALUInstr.Modes.Subi) {
      aluOut := io.instr.bits.src1 - io.instr.bits.src2  // src2 is immediate
    }
    is(ALUInstr.Modes.Mult) {
      aluOut := io.instr.bits.src1 * io.instr.bits.src2
    }
    is(ALUInstr.Modes.MultAcc) {
      // MultAcc: add multiplication result to accumulator and output the new accumulator value
      val multResult = io.instr.bits.src1 * io.instr.bits.src2
      accNext := acc + multResult
      aluOut := acc + multResult  // Output the new accumulator value
    }
    is(ALUInstr.Modes.MultAccInit) {
      // MultAccInit: multiply and write result directly to accumulator (no addition)
      val multResult = io.instr.bits.src1 * io.instr.bits.src2
      accNext := multResult
      aluOut := multResult
    }
    is(ALUInstr.Modes.Eq) {
      aluOut := (io.instr.bits.src1 === io.instr.bits.src2).asUInt
    }
    is(ALUInstr.Modes.Gte) {
      aluOut := (io.instr.bits.src1 >= io.instr.bits.src2).asUInt
    }
    is(ALUInstr.Modes.Lte) {
      aluOut := (io.instr.bits.src1 <= io.instr.bits.src2).asUInt
    }
    is(ALUInstr.Modes.Not) {
      aluOut := ~io.instr.bits.src1
    }
    is(ALUInstr.Modes.And) {
      aluOut := io.instr.bits.src1 & io.instr.bits.src2
    }
    is(ALUInstr.Modes.Or) {
      aluOut := io.instr.bits.src1 | io.instr.bits.src2
    }
    is(ALUInstr.Modes.ShiftL) {
      aluOut := io.instr.bits.src1 << io.instr.bits.src2(shiftBits, 0)
    }
    is(ALUInstr.Modes.ShiftR) {
      aluOut := io.instr.bits.src1 >> io.instr.bits.src2(shiftBits, 0)
    }
  }

  // Pipeline the result through the specified latency
  if (params.aluLatency == 0) {
    // Single cycle latency
    io.result.valid := io.instr.valid
    io.result.bits.value := aluOut
    io.result.bits.address.addr := io.instr.bits.dst.addr
    io.result.bits.address.tag := io.instr.bits.dst.tag
    io.result.bits.force := false.B
  } else {
    // Multi-cycle pipeline
    val validPipe = RegInit(VecInit(Seq.fill(params.aluLatency)(false.B)))
    val resultPipe = RegInit(VecInit(Seq.fill(params.aluLatency)(0.U(params.width.W))))
    val dstAddrPipe = RegInit(VecInit(Seq.fill(params.aluLatency)(0.U.asTypeOf(new BTaggedReg(params)))))
    
    // Stage 0 (input)
    validPipe(0) := io.instr.valid
    resultPipe(0) := aluOut
    dstAddrPipe(0) := io.instr.bits.dst
    
    // Pipeline stages 1 to latency-1
    for (i <- 1 until params.aluLatency) {
      validPipe(i) := validPipe(i-1)
      resultPipe(i) := resultPipe(i-1)
      dstAddrPipe(i) := dstAddrPipe(i-1)
    }
    
    // Output
    io.result.valid := validPipe(params.aluLatency-1)
    io.result.bits.value := resultPipe(params.aluLatency-1)
    io.result.bits.address := dstAddrPipe(params.aluLatency-1)
    io.result.bits.force := false.B
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
      println("Usage: <command> <outputDir> ALU <amletParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new ALU(params)
    }
  }
}
