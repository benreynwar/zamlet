package fmvpu.amlet

import chisel3._
import chisel3.util._

/**
 * ALULite for Amlet implementation
 * 
 * Receives resolved ALULite instructions from ALULiteRS and produces write results.
 * Supports arithmetic and logical operations on address-width data with configurable pipeline latency.
 * 
 * Supported Operations:
 * - Add: Addition of two address registers
 * - Addi: Addition with immediate value
 * - Sub: Subtraction of two address registers  
 * - Subi: Subtraction with immediate value
 * - Mult: Multiplication of two address registers
 * - MultAcc: Multiply-accumulate operation
 * - Eq, Gte, Lte: Comparison operations
 * - Not, And, Or: Logical operations
 * - ShiftL, ShiftR: Shift operations
 * - Jump: Control flow (handled by setting result appropriately)
 */
class ALULite(params: AmletParams) extends Module {
  val io = IO(new Bundle {
    // Input instruction from ALULiteRS
    val instr = Input(Valid(new ALULiteInstr.Resolved(params)))
    
    // ALULite result output
    val result = Output(new WriteResult(params))
  })

  // Compute ALULite result
  val aluOut = Wire(UInt(params.aWidth.W))

  // Accumulator
  val accNext = Wire(UInt(params.aWidth.W))
  val acc = RegNext(accNext, 0.U)
  
  aluOut := 0.U  // Default value
  accNext := acc  // Default: preserve accumulator value
  
  switch(io.instr.bits.mode) {
    is(ALULiteInstr.Modes.None) {
      aluOut := 0.U
    }
    is(ALULiteInstr.Modes.Add) {
      aluOut := io.instr.bits.src1 + io.instr.bits.src2
    }
    is(ALULiteInstr.Modes.Addi) {
      aluOut := io.instr.bits.src1 + io.instr.bits.src2  // src2 is immediate
    }
    is(ALULiteInstr.Modes.Sub) {
      aluOut := io.instr.bits.src1 - io.instr.bits.src2
    }
    is(ALULiteInstr.Modes.Subi) {
      aluOut := io.instr.bits.src1 - io.instr.bits.src2  // src2 is immediate
    }
    is(ALULiteInstr.Modes.Mult) {
      aluOut := io.instr.bits.src1 * io.instr.bits.src2
    }
    is(ALULiteInstr.Modes.MultAcc) {
      // MultAcc: add multiplication result to accumulator and output the new accumulator value
      val multResult = io.instr.bits.src1 * io.instr.bits.src2
      accNext := acc + multResult
      aluOut := acc + multResult  // Output the new accumulator value
    }
    is(ALULiteInstr.Modes.MultAccInit) {
      // MultAccInit: multiply and write result directly to accumulator (no addition)
      val multResult = io.instr.bits.src1 * io.instr.bits.src2
      accNext := multResult
      aluOut := multResult
    }
    is(ALULiteInstr.Modes.Eq) {
      aluOut := (io.instr.bits.src1 === io.instr.bits.src2).asUInt
    }
    is(ALULiteInstr.Modes.Gte) {
      aluOut := (io.instr.bits.src1 >= io.instr.bits.src2).asUInt
    }
    is(ALULiteInstr.Modes.Lte) {
      aluOut := (io.instr.bits.src1 <= io.instr.bits.src2).asUInt
    }
    is(ALULiteInstr.Modes.Not) {
      aluOut := ~io.instr.bits.src1
    }
    is(ALULiteInstr.Modes.And) {
      aluOut := io.instr.bits.src1 & io.instr.bits.src2
    }
    is(ALULiteInstr.Modes.Or) {
      aluOut := io.instr.bits.src1 | io.instr.bits.src2
    }
    is(ALULiteInstr.Modes.ShiftL) {
      aluOut := io.instr.bits.src1 << io.instr.bits.src2(3, 0)  // Use bottom 4 bits for shift amount (16-bit max)
    }
    is(ALULiteInstr.Modes.ShiftR) {
      aluOut := io.instr.bits.src1 >> io.instr.bits.src2(3, 0)  // Use bottom 4 bits for shift amount (16-bit max)
    }
    is(ALULiteInstr.Modes.Jump) {
      // For jump instructions, the result might be a target address or control signal
      aluOut := io.instr.bits.src1  // Could be jump target
    }
  }

  // Pipeline the result through the specified latency (reuse aluLatency param)
  if (params.aluLatency == 0) {
    // Single cycle latency
    io.result.valid := io.instr.valid
    io.result.value := aluOut.pad(params.width)  // Pad to full width for WriteResult
    io.result.address.addr := io.instr.bits.dst.addr
    io.result.address.tag := io.instr.bits.dst.tag
    io.result.force := false.B
  } else {
    // Multi-cycle pipeline
    val validPipe = RegInit(VecInit(Seq.fill(params.aluLatency)(false.B)))
    val resultPipe = RegInit(VecInit(Seq.fill(params.aluLatency)(0.U(params.aWidth.W))))
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
    io.result.value := resultPipe(params.aluLatency-1).pad(params.width)  // Pad to full width
    io.result.address := dstAddrPipe(params.aluLatency-1)
    io.result.force := false.B
  }
}

/** Generator object for creating ALULite modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of ALULite modules with configurable parameters.
  */
object ALULiteGenerator extends fmvpu.ModuleGenerator {
  /** Create an ALULite module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return ALULite module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> ALULite <amletParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new ALULite(params)
    }
  }
}
