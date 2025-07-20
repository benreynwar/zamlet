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
 * - Jump: Control flow (handled by setting result appropriately)
 */
class ALU(params: AmletParams) extends Module {
  val io = IO(new Bundle {
    // Input instruction from ALURS
    val instr = Input(Valid(new ALUInstr.Resolved(params)))
    
    // ALU result output
    val result = Output(new WriteResult(params))
  })

  // Compute ALU result
  val aluOut = Wire(UInt(params.width.W))
  
  aluOut := 0.U  // Default value
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
      // For MultAcc, we assume the accumulator value is already included in the computation
      // This could be enhanced to track local accumulator state if needed
      aluOut := io.instr.bits.src1 * io.instr.bits.src2
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
      aluOut := io.instr.bits.src1 << io.instr.bits.src2(4, 0)  // Use bottom 5 bits for shift amount
    }
    is(ALUInstr.Modes.ShiftR) {
      aluOut := io.instr.bits.src1 >> io.instr.bits.src2(4, 0)  // Use bottom 5 bits for shift amount
    }
    is(ALUInstr.Modes.Jump) {
      // For jump instructions, the result might be a target address or control signal
      aluOut := io.instr.bits.src1  // Could be jump target
    }
  }

  // Pipeline the result through the specified latency
  if (params.aluLatency == 0) {
    // Single cycle latency
    io.result.valid := io.instr.valid
    io.result.value := aluOut
    io.result.address.addr := io.instr.bits.dst.addr
    io.result.address.ident := io.instr.bits.dst.ident
    io.result.force := false.B
  } else {
    // Multi-cycle pipeline
    val validPipe = RegInit(VecInit(Seq.fill(params.aluLatency)(false.B)))
    val resultPipe = RegInit(VecInit(Seq.fill(params.aluLatency)(0.U(params.width.W))))
    val dstAddrPipe = RegInit(VecInit(Seq.fill(params.aluLatency)(0.U.asTypeOf(new DRegWithIdent(params)))))
    
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
      println("Usage: <command> <outputDir> ALU <amletParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new ALU(params)
    }
  }
}
