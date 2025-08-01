package fmvpu.bamlet

import chisel3._
import chisel3.util._
import fmvpu.amlet.{ControlWrite, ControlWriteMode, ControlInstr, PredicateInstr, VLIWInstr}


class LoopState(params: BamletParams) extends Bundle {
  val start = UInt(params.amlet.instrAddrWidth.W)
  val end = UInt(params.amlet.instrAddrWidth.W)
  val index = UInt(params.aWidth.W)
  val predicate = params.amlet.pReg()
  val resolvedIterations = Vec(params.nAmlets, Bool())  // Tracks which Amlets have reported back resolved iteration counts
  val iterations = UInt(params.aWidth.W)
  // When we resolve or increment the index we set this to true
  // if we are on or past the last iteration.
  val terminating = Bool()
  
  // NOTE: Bamlet determines loop termination by stopping instruction dispatch
  // from loop body. No explicit termination signal needed to Amlets.
  // Predicates (loop_index < loop_iterations) control which Amlets execute.
  
  // NOTE: This is the authoritative loop state for the entire Bamlet.
  // Amlets maintain their own LoopState only to track A-register writes.
  // 
  // Loop iteration resolution flow:
  // - LoopGlobal: Bamlet resolves iteration count from global registers
  // - LoopLocal: Each Amlet resolves iteration count from local registers/state
  //   and reports back to Bamlet via resolvedIterations Vec
}


class ControlState(params: BamletParams) extends Bundle {
  val loopActive = Bool()
  val loopStates = Vec(params.nLoopLevels, new LoopState(params))
  val loopLevel = UInt(log2Ceil(params.nLoopLevels).W)
  val globals = Vec(params.amlet.nGRegs, params.amlet.aReg())
  val active = Bool()
  def dWord(): UInt = UInt(params.amlet.width.W)
  def activeLoopState(): LoopState = loopStates(loopLevel)
}


class InstrResp(params: BamletParams) extends Bundle {
  val instr = new VLIWInstr.Base(params.amlet)
  val pc = UInt(params.amlet.instrAddrWidth.W)
}


class Control(params: BamletParams) extends Module {
  val io = IO(new Bundle {
    // Start signals
    val start = Input(Valid(UInt(params.amlet.instrAddrWidth.W)))
    
    // Instruction memory interface
    val imReq = Output(Valid(UInt(params.amlet.instrAddrWidth.W)))
    val imResp = Input(Valid(new InstrResp(params)))

    val writeControl = Input(Valid(new ControlWrite(params.amlet)))

    // Instruction outputs to reservation stations
    val instr = Decoupled(new VLIWInstr.Expanded(params.amlet))

    // For each loop instruction that a receives it 
    val loopIterations = Input(Vec(params.nAmlets, Valid(UInt(params.aWidth.W))))
  })

  val pc = Wire(UInt(params.amlet.instrAddrWidth.W))
  pc := io.imResp.bits.pc // default

  // The state for the next cycle
  val stateNext = Wire(new ControlState(params))
  // The state for the body of this instruction.  After the control has been evaluated but before
  // the rest.
  val stateBody = Wire(new ControlState(params))
  val stateInit = Wire(new ControlState(params))
  stateInit.loopActive := false.B
  stateInit.loopLevel := 0.U
  for (i <- 0 until params.nLoopLevels) {
    stateInit.loopStates(i).start := 0.U
    stateInit.loopStates(i).end := 0.U
    stateInit.loopStates(i).index := 0.U
    stateInit.loopStates(i).predicate := 0.U
    stateInit.loopStates(i).resolvedIterations := VecInit(Seq.fill(params.nAmlets)(false.B))
    stateInit.loopStates(i).iterations := 0.U
    stateInit.loopStates(i).terminating := false.B
  }
  for (i <- 0 until params.amlet.nGRegs) {
    stateInit.globals(i) := 0.U
  }
  stateInit.active := false.B
  
  val state = RegNext(stateNext, stateInit)
  val instrBuffered = Wire(Decoupled(new VLIWInstr.Expanded(params.amlet)))

  when (state.active && instrBuffered.ready) {
    pc := io.imResp.bits.pc + 1.U
  } 

  // Convert from Base to Expanded format and substitute some Loop for Incr.
  val expandedInstr = io.imResp.bits.instr.expand()
  
  // Handle predicate src1 mode resolution
  val predicateSrc1Resolved = Wire(UInt(params.amlet.aWidth.W))
  when (io.imResp.bits.instr.predicate.src1.mode === PredicateInstr.Src1Mode.Immediate) {
    predicateSrc1Resolved := io.imResp.bits.instr.predicate.src1.value
  } .elsewhen (io.imResp.bits.instr.predicate.src1.mode === PredicateInstr.Src1Mode.LoopIndex) {
    predicateSrc1Resolved := state.loopStates(io.imResp.bits.instr.predicate.src1.value(log2Ceil(params.amlet.nLoopLevels)-1, 0)).index
  } .elsewhen (io.imResp.bits.instr.predicate.src1.mode === PredicateInstr.Src1Mode.Global) {
    predicateSrc1Resolved := state.globals(io.imResp.bits.instr.predicate.src1.value(log2Ceil(params.amlet.nGRegs)-1, 0))
  } .otherwise {
    predicateSrc1Resolved := 0.U
  }
  
  instrBuffered.bits := expandedInstr
  instrBuffered.bits.predicate.src1 := predicateSrc1Resolved
  instrBuffered.valid := io.imResp.valid && state.active

  val instrBuffer = Module(new fmvpu.utils.SkidBuffer(new VLIWInstr.Expanded(params.amlet)))
  instrBuffer.io.i <> instrBuffered
  io.instr <> instrBuffer.io.o

  stateBody := state     // default
  stateNext := stateBody // default

  // Update the Loop States if we have a loop instruction
  val isLocalLoop = io.imResp.bits.instr.control.mode === ControlInstr.Modes.LoopLocal
  val isGlobalLoop = io.imResp.bits.instr.control.mode === ControlInstr.Modes.LoopGlobal
  val isImmediateLoop = io.imResp.bits.instr.control.mode === ControlInstr.Modes.LoopImmediate

  // We explicitly send the loop level to the Amlet so they don't need to track that.
  instrBuffered.bits.control.level := stateBody.loopLevel

  when (io.imResp.valid && instrBuffered.ready) {
    when (isLocalLoop || isGlobalLoop || isImmediateLoop) {
      stateBody.loopActive := true.B
      // If we were already in a loop.
      when (state.loopActive) {
        when (state.activeLoopState().start === io.imResp.bits.pc) {
          // We're at the start of the current loop
          instrBuffered.bits.control.mode := ControlInstr.Modes.Incr
        } .otherwise {
          // We're at the start of an new loop (inside another loop).
          stateBody.loopLevel := state.loopLevel + 1.U
          stateBody.loopStates(stateBody.loopLevel).index := 0.U
          when (isLocalLoop) {
            stateBody.loopStates(stateBody.loopLevel).resolvedIterations :=
              VecInit(Seq.fill(params.nAmlets)(false.B))
            stateBody.loopStates(stateBody.loopLevel).terminating := false.B
          } .elsewhen (isGlobalLoop) {
            stateBody.loopStates(stateBody.loopLevel).iterations := state.globals(io.imResp.bits.instr.control.iterations)
            stateBody.loopStates(stateBody.loopLevel).resolvedIterations :=
              VecInit(Seq.fill(params.nAmlets)(true.B))
            stateBody.loopStates(stateBody.loopLevel).terminating :=
              (state.globals(io.imResp.bits.instr.control.iterations) <= 1.U)
          } .otherwise { // isImmediateLoop
            stateBody.loopStates(stateBody.loopLevel).iterations := io.imResp.bits.instr.control.iterations
            stateBody.loopStates(stateBody.loopLevel).resolvedIterations :=
              VecInit(Seq.fill(params.nAmlets)(true.B))
            stateBody.loopStates(stateBody.loopLevel).terminating :=
              (io.imResp.bits.instr.control.iterations <= 1.U)
          }
        }
      } .otherwise {
        // We're at the start of a new loop
        stateBody.loopLevel := 0.U
        stateBody.loopStates(stateBody.loopLevel).index := 0.U
        when (isLocalLoop) {
          stateBody.loopStates(stateBody.loopLevel).resolvedIterations :=
            VecInit(Seq.fill(params.nAmlets)(false.B))
          stateBody.loopStates(stateBody.loopLevel).terminating := false.B
        } .elsewhen (isGlobalLoop) {
          stateBody.loopStates(stateBody.loopLevel).iterations := state.globals(io.imResp.bits.instr.control.iterations)
          stateBody.loopStates(stateBody.loopLevel).resolvedIterations :=
            VecInit(Seq.fill(params.nAmlets)(true.B))
          stateBody.loopStates(stateBody.loopLevel).terminating :=
            (state.globals(io.imResp.bits.instr.control.iterations) <= 1.U)
        } .otherwise { // isImmediateLoop
          stateBody.loopStates(stateBody.loopLevel).iterations := io.imResp.bits.instr.control.iterations
          stateBody.loopStates(stateBody.loopLevel).resolvedIterations :=
            VecInit(Seq.fill(params.nAmlets)(true.B))
          stateBody.loopStates(stateBody.loopLevel).terminating :=
            (io.imResp.bits.instr.control.iterations <= 1.U)
        }
      }
      stateBody.loopStates(stateBody.loopLevel).start := io.imResp.bits.pc
      stateBody.loopStates(stateBody.loopLevel).end :=
        io.imResp.bits.pc + io.imResp.bits.instr.control.length
    }
  }

  // Update the Loop States if we reached the end of a loop
  when (io.imResp.valid && instrBuffered.ready) {
    when (stateBody.activeLoopState().end === io.imResp.bits.pc) {
      when (stateBody.activeLoopState().terminating) {
        when (stateBody.loopLevel === 0.U) {
          stateNext.loopLevel := 0.U
          stateNext.loopActive := false.B
        } .otherwise {
          stateNext.loopLevel := stateBody.loopLevel - 1.U
        }
      } .otherwise {
        stateNext.loopStates(stateBody.loopLevel).index := stateBody.activeLoopState().index + 1.U
        stateNext.loopStates(stateBody.loopLevel).terminating :=
          (stateBody.activeLoopState().index >= stateBody.activeLoopState().iterations-2.U) && stateBody.activeLoopState().resolvedIterations.asUInt.andR
        pc := stateBody.activeLoopState().start
      }
    }
  }

  // Loop over the nAmlets
  for (amletIndex <- 0 until params.nAmlets) {
    // Find the lowest level where this amlet hasn't resolved iterations yet
    val unresolvedLevels = Wire(Vec(params.nLoopLevels, Bool()))
    for (i <- 0 until params.nLoopLevels) {
      unresolvedLevels(i) := !state.loopStates(i).resolvedIterations(amletIndex)
    }
    val level = PriorityEncoder(unresolvedLevels)
    when (io.loopIterations(amletIndex).valid) {
      stateNext.loopStates(level).resolvedIterations(amletIndex) := true.B
      when (state.loopStates(level).iterations > io.loopIterations(amletIndex).bits) {
        stateNext.loopStates(level).iterations := state.loopStates(level).iterations
      } .otherwise {
        stateNext.loopStates(level).iterations := io.loopIterations(amletIndex).bits
      }
      // Check if all amlets have resolved their iterations
      val allResolved = stateNext.loopStates(level).resolvedIterations.asUInt.andR
      when (allResolved) {
        when (stateNext.loopStates(level).index >= stateNext.loopStates(level).iterations - 1.U) {
          stateNext.loopStates(level).terminating := true.B
        }
      }
    }
  }

  stateNext.active := state.active
  when (instrBuffered.valid && instrBuffered.ready) {
    when (instrBuffered.bits.control.mode === ControlInstr.Modes.Halt) {
      stateNext.active := false.B
    }
  }

  val startReg = RegNext(io.start)

  when (io.start.valid) {
    stateNext.active := true.B
    stateNext.loopActive := false.B
  }
  when (startReg.valid) {
    pc := io.start.bits
  }

  io.imReq.valid := state.active
  io.imReq.bits := pc

  // Update the globals
  // Do this to stateNext rather than stateBody to help with timing
  when (io.writeControl.valid && io.writeControl.bits.mode === ControlWriteMode.GlobalRegister) {
    stateNext.globals(io.writeControl.bits.address(log2Ceil(params.amlet.nGRegs)-1, 0)) := io.writeControl.bits.data
  }


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
