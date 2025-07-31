package fmvpu.amlet

import chisel3._
import chisel3.util._

/**
 * ALUPredicate for Amlet implementation
 */
class ALUPredicate(params: AmletParams) extends Module {
  val io = IO(new Bundle {
    // Input instruction from ALUPredicateRS
    val instr = Input(Valid(new PredicateInstr.Resolved(params)))
    
    // ALUPredicate result output
    val result = Output(Valid(new PredicateResult(params)))
  })

  // Compute comparison result
  val comparisonResult = Wire(Bool())

  comparisonResult := true.B  // Default value

  switch(io.instr.bits.mode) {
    is(PredicateInstr.Modes.None) {
      comparisonResult := true.B
    }
    is(PredicateInstr.Modes.Eq) {
      comparisonResult := io.instr.bits.src1 === io.instr.bits.src2
    }
    is(PredicateInstr.Modes.NEq) {
      comparisonResult := io.instr.bits.src1 =/= io.instr.bits.src2
    }
    is(PredicateInstr.Modes.Gte) {
      comparisonResult := io.instr.bits.src1 >= io.instr.bits.src2
    }
    is(PredicateInstr.Modes.Gt) {
      comparisonResult := io.instr.bits.src1 > io.instr.bits.src2
    }
    is(PredicateInstr.Modes.Lte) {
      comparisonResult := io.instr.bits.src1 <= io.instr.bits.src2
    }
    is(PredicateInstr.Modes.Lt) {
      comparisonResult := io.instr.bits.src1 < io.instr.bits.src2
    }
    is(PredicateInstr.Modes.Unused7) {
      comparisonResult := true.B
    }
  }

  // Combine comparison result with base predicate: final = comparison AND base
  val finalResult = Wire(Bool())
  finalResult := comparisonResult && io.instr.bits.base

  // Pipeline the result through the specified latency (reuse aluLatency param)
  if (params.aluPredicateLatency == 0) {
    // Single cycle latency
    io.result.valid := io.instr.valid
    io.result.bits.value := finalResult
    io.result.bits.address.addr := io.instr.bits.dst.addr
    io.result.bits.address.tag := io.instr.bits.dst.tag
  } else {
    // Multi-cycle pipeline
    val validPipe = RegInit(VecInit(Seq.fill(params.aluPredicateLatency)(false.B)))
    val resultPipe = RegInit(VecInit(Seq.fill(params.aluPredicateLatency)(false.B)))
    val dstAddrPipe = RegInit(VecInit(Seq.fill(params.aluPredicateLatency)(0.U.asTypeOf(new PTaggedReg(params)))))
    
    // Stage 0 (input)
    validPipe(0) := io.instr.valid
    resultPipe(0) := finalResult
    dstAddrPipe(0) := io.instr.bits.dst
    
    // Pipeline stages 1 to latency-1
    for (i <- 1 until params.aluPredicateLatency) {
      validPipe(i) := validPipe(i-1)
      resultPipe(i) := resultPipe(i-1)
      dstAddrPipe(i) := dstAddrPipe(i-1)
    }
    
    // Output
    io.result.valid := validPipe(params.aluPredicateLatency-1)
    io.result.bits.value := resultPipe(params.aluPredicateLatency-1)
    io.result.bits.address := dstAddrPipe(params.aluPredicateLatency-1)
  }
}

/** Generator object for creating ALUPredicate modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of ALUPredicate modules with configurable parameters.
  */
object ALUPredicateGenerator extends fmvpu.ModuleGenerator {
  /** Create an ALUPredicate module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return ALUPredicate module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> ALUPredicate <amletParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new ALUPredicate(params)
    }
  }
}
