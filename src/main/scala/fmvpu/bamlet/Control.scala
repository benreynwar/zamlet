package fmvpu.bamlet

import chisel3._
import chisel3.util._
import fmvpu.amlet.ControlInstr


class LoopState(params: BamletParams) extends Bundle {
  val start = UInt(params.instrAddrWidth.W)
  val index = UInt(params.aWidth.W)
  val resolvedLength = Vec(params.nAmlets, Bool())
  val length = UInt(params.aWidth.W)
  // When we resolve or increment the index we set this to true
  // if we are on or past the last iteration.
  val terminating = Bool()
}

class InstrResp(params: BamletParams) extends Bundle {
  val instr = new VLIWInstr.Base(params.amlet)
  val pc = UInt(params.instrAddrWidth.W)
}


class Control(params: BamletParams) extends Module {
  val io = IO(new Bundle {
    // Start signals
    val start = Input(Valid(UInt(params.instrAddrWidth.W)))
    
    // Instruction memory interface
    val imReq = Output(Valid(UInt(params.instrAddrWidth.W)))
    val imResp = Input(Valid(new InstrResp(params)))

    // Instruction outputs to reservation stations
    val instr = Decoupled(new VLIWInstr.Base(params.amlet))

    // For each loop instruction that a receives it 
    val loopLengths = Input(Vec(params.nAmlets, Valid(UInt(params.aWidth.W))))
  })

  // Program counter and loop state
  val pcNext = Wire(UInt(params.instrAddrWidth.W))
  val pc = RegNext(pcNext, 0.U)
  val activeNext = Wire(Bool())
  val active = RegNext(activeNext, false.B)

  // The loop level at the start of the next instruction.
  val loopLevelNext = Wire(UInt(log2Ceil(params.nLoopLevels).W))
  // The loop level at the start of this instruction.
  val loopLevel = RegNext(loopLevelNext, 0.U)
  // The loop level in the body of this instruction.
  val loopLevelCurrent = Wire(UInt(log2Ceil(params.nLoopLevels).W))

  val loopActiveNext = Wire(Bool())
  val loopActive = RegNext(loopActiveNext, false.B)
  val loopActiveCurrent = Wire(Bool())
  val loopStatesNext = Wire(Vec(params.nLoopLevels, new LoopState(params)))
  val loopStates = RegNext(loopStatesNext)
  val loopStatesCurrent = Wire(Vec(params.nLoopLevels, new LoopState(params)))

  // The only change we make to the instruction is that we substitute some Loop for Incr.
  io.instr.bits := io.imResp.bits.instr
  io.instr.valid := io.imResp.valid

  loopActiveCurrent := loopActive
  loopStatesCurrent := loopStates
  loopLevelCurrent := loopLevel
  when (io.imResp.valid) {
    when (io.imResp.bits.instr.control.mode === ControlInstr.Modes.Loop) {
      loopActiveCurrent := true.B
      when (loopActive) {
        when (loopStates(loopLevel).start === io.imResp.bits.pc) {
          // We're at the start of the current loop
          io.instr.bits.control.mode := ControlInstr.Modes.Incr
        } .otherwise {
          // We're at the start of an new loop (inside another loop).
          loopLevelCurrent := loopLevel + 1.U
          loopStatesCurrent(loopLevelCurrent).index := 0.U
          loopStatesCurrent(loopLevelCurrent).resolvedLength := VecInit(Seq.fill(params.nAmlets)(false.B))
          loopStatesCurrent(loopLevelCurrent).terminating := false.B
        }
      } .otherwise {
        // We're at the start of a new loop
        loopLevelCurrent := 0.U
        loopStatesCurrent(loopLevelCurrent).index := 0.U
        loopStatesCurrent(loopLevelCurrent).resolvedLength := VecInit(Seq.fill(params.nAmlets)(false.B))
        loopStatesCurrent(loopLevelCurrent).terminating := false.B
      }
      loopStatesCurrent(loopLevelCurrent).start := io.imResp.bits.pc
    }
  }

  loopActiveNext := loopActiveCurrent
  loopLevelNext := loopLevelCurrent
  loopStatesNext := loopStatesCurrent
  pcNext := pc + 1.U
  when (io.imResp.valid) {
    when (io.imResp.bits.instr.control.endloop) {
      when (loopStatesCurrent(loopLevelCurrent).terminating) {
        when (loopLevelCurrent === 0.U) {
          loopLevelNext := 0.U
          loopActiveNext := false.B
        } .otherwise {
          loopLevelNext := loopLevelCurrent - 1.U
        }
      } .otherwise {
        loopStatesNext(loopLevelCurrent).index := loopStatesCurrent(loopLevelCurrent).index + 1.U
        pcNext := loopStatesCurrent(loopLevelCurrent).start
      }
    }
  }

  // Process the loop lengths received from the amlets.

  val loopLengthLevelsNext = Wire(Vec(params.nAmlets, UInt(log2Ceil(params.nLoopLevels).W)))
  val loopLengthLevels = RegNext(loopLengthLevelsNext, VecInit(Seq.fill(params.nAmlets)(0.U)))

  loopLengthLevelsNext := loopLengthLevels
  // Loop over the nAmlets
  for (amletIndex <- 0 until params.nAmlets) {
    val level = loopLengthLevels(amletIndex)
    when (io.loopLengths(amletIndex).valid) {
      loopStatesNext(level).resolvedLength(amletIndex) := true.B
      loopStatesNext(level).length := Mux(loopStates(level).length > io.loopLengths(amletIndex).bits, 
                                         loopStates(level).length, 
                                         io.loopLengths(amletIndex).bits)
      
      // Check if all amlets have resolved their lengths
      val allResolved = loopStatesNext(level).resolvedLength.asUInt.andR
      when (allResolved) {
        when (loopStatesNext(level).index >= loopStatesNext(level).length - 1.U) {
          loopStatesNext(level).terminating := true.B
        }
      }
    }
  }

  activeNext := active
  when (io.imResp.valid) {
    when (io.imResp.bits.instr.control.halt) {
      activeNext := false.B
    }
  }

  when (io.start.valid) {
    activeNext := true.B
    pcNext := io.start.bits
  }

  io.imReq.valid := active
  io.imReq.bits := pc

}



/** Generator object for creating Control modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of Control modules with configurable parameters.
  */
object ControlGenerator extends fmvpu.ModuleGenerator {
  /** Create a Control module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return Control module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> Control <bamletParamsFileName>")
      null
    } else {
      val params = BamletParams.fromFile(args(0))
      new Control(params)
    }
  }
}
