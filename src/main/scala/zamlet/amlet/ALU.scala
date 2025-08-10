package zamlet.amlet

import chisel3._
import chisel3.util._
import zamlet.utils.{ValidBuffer, ResetStage}

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

  val resetBuffered = ResetStage(clock, reset)

  withReset(resetBuffered) {
  
    // Stage 'i' - Input signals (before inputBuffer)
    val iInstr = io.instr
  
    // Optional input buffer (i to a)
    val inputBuffer = Module(new ValidBuffer(new ALUInstr.Resolved(params), params.aluParams.iaBuffer))
    inputBuffer.io.i <> iInstr
    val aInstr = inputBuffer.io.o
  
    // Shift amount bit range for data width operations
    val shiftBits = log2Ceil(params.width) - 1

    // Stage 'a' - Compute and mux non-multiplier instructions, compute multiplier operations
    val aMultResult = aInstr.bits.src1 * aInstr.bits.src2
    
    // Non-multiplier result computation and muxing in stage 'a'
    val aNonMultiplierResult = Wire(UInt(params.width.W))
    aNonMultiplierResult := aInstr.bits.src1  // Default when predicate is false
    
    when (aInstr.bits.predicate) {
      switch(aInstr.bits.mode) {
        is(ALUInstr.Modes.None) { aNonMultiplierResult := 0.U(params.width.W) }
        is(ALUInstr.Modes.Add) { aNonMultiplierResult := aInstr.bits.src1 + aInstr.bits.src2 }
        is(ALUInstr.Modes.Addi) { aNonMultiplierResult := aInstr.bits.src1 + aInstr.bits.src2 }
        is(ALUInstr.Modes.Sub) { aNonMultiplierResult := aInstr.bits.src1 - aInstr.bits.src2 }
        is(ALUInstr.Modes.Subi) { aNonMultiplierResult := aInstr.bits.src1 - aInstr.bits.src2 }
        is(ALUInstr.Modes.Eq) { aNonMultiplierResult := (aInstr.bits.src1 === aInstr.bits.src2).asUInt }
        is(ALUInstr.Modes.Gte) { aNonMultiplierResult := (aInstr.bits.src1 >= aInstr.bits.src2).asUInt }
        is(ALUInstr.Modes.Lte) { aNonMultiplierResult := (aInstr.bits.src1 <= aInstr.bits.src2).asUInt }
        is(ALUInstr.Modes.Not) { aNonMultiplierResult := ~aInstr.bits.src1 }
        is(ALUInstr.Modes.And) { aNonMultiplierResult := aInstr.bits.src1 & aInstr.bits.src2 }
        is(ALUInstr.Modes.Or) { aNonMultiplierResult := aInstr.bits.src1 | aInstr.bits.src2 }
        is(ALUInstr.Modes.ShiftL) { aNonMultiplierResult := aInstr.bits.src1 << aInstr.bits.src2(shiftBits, 0) }
        is(ALUInstr.Modes.ShiftR) { aNonMultiplierResult := aInstr.bits.src1 >> aInstr.bits.src2(shiftBits, 0) }
      }
    }
    
    // Determine if instruction uses multiplier
    val aUsesMultiplier = aInstr.bits.mode === ALUInstr.Modes.Mult || 
                         aInstr.bits.mode === ALUInstr.Modes.MultAcc || 
                         aInstr.bits.mode === ALUInstr.Modes.MultAccInit

    // Apply abBuffer to required signals only (stage 'a' to 'b')
    val bNonMultiplierResult = RegNext(aNonMultiplierResult)
    val bMultResult = RegNext(aMultResult) 
    val bUsesMultiplier = RegNext(aUsesMultiplier)
    val bInstr = ValidBuffer(aInstr, params.aluParams.abBuffer)

    // Accumulator - current value is at stage 'b'
    val bAccNext = Wire(UInt(params.width.W))
    val bAcc = RegNext(bAccNext, 0.U)
    bAccNext := bAcc  // Default: preserve accumulator value

    // Update accumulator based on bInstr mode
    when (bInstr.valid && bInstr.bits.predicate) {
      switch(bInstr.bits.mode) {
        is(ALUInstr.Modes.MultAcc) {
          bAccNext := bAcc + bMultResult
        }
        is(ALUInstr.Modes.MultAccInit) {
          bAccNext := bMultResult
        }
      }
    }

    // Stage 'b' - Mux between multiplier and non-multiplier results
    val bResult = Wire(UInt(params.width.W))
    
    when (bUsesMultiplier) {
      // For multiplier operations, handle predicate in stage 'b'
      bResult := bInstr.bits.src1  // Default when predicate is false
      when (bInstr.valid && bInstr.bits.predicate) {
        switch(bInstr.bits.mode) {
          is(ALUInstr.Modes.Mult) { bResult := bMultResult }
          is(ALUInstr.Modes.MultAcc) { bResult := bAcc + bMultResult }
          is(ALUInstr.Modes.MultAccInit) { bResult := bMultResult }
        }
      }
    } .otherwise {
      // For non-multiplier operations, use pre-computed result from stage 'a'
      bResult := bNonMultiplierResult
    }

    // Create result before output buffer (stage 'b')
    val bWriteResult = Wire(Valid(new WriteResult(params)))
    bWriteResult.valid := bInstr.valid
    bWriteResult.bits.value := bResult
    bWriteResult.bits.address := bInstr.bits.dst
    bWriteResult.bits.predicate := bInstr.bits.predicate
    bWriteResult.bits.force := false.B

    // Apply boBuffer (stage 'b' to 'o')
    val oResult = ValidBuffer(bWriteResult, params.aluParams.boBuffer)
    
    // Final output (stage 'o')
    io.result := oResult
  }
}

/** Generator object for creating ALU modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of ALU modules with configurable parameters.
  */
object ALUGenerator extends zamlet.ModuleGenerator {
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
