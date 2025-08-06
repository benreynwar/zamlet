package fmvpu.bamlet

import chisel3._
import chisel3.util._
import fmvpu.amlet._
import fmvpu.utils.{DroppingFifo, SkidBuffer, DecoupledBuffer}

class DependencyTracker(params: BamletParams) extends Module {
  val io = IO(new Bundle {
    // Instructions from the control
    val i = Flipped(DecoupledIO(new VLIWInstr.Expanded(params.amlet)))
    // Instructions out to the Amlets
    val o = DecoupledIO(new VLIWInstr.Expanded(params.amlet))
  })

  // Add optional input buffers
  val inputBackwardBuffer = Module(new SkidBuffer(new VLIWInstr.Expanded(params.amlet), params.dependencyTracker.inputBackwardBuffer))
  val inputForwardBuffer = Module(new DecoupledBuffer(new VLIWInstr.Expanded(params.amlet), params.dependencyTracker.inputForwardBuffer))
  
  // Chain: io.i -> SkidBuffer -> DecoupledBuffer -> internal processing
  inputBackwardBuffer.io.i <> io.i
  inputForwardBuffer.io.i <> inputBackwardBuffer.io.o
  val bufferedInput = inputForwardBuffer.io.o

  // Create DroppingFifos for each of the 6 VLIW instruction slots
  val fifoDepth = params.dependencyTracker.fifoDepth
  val countBits = params.dependencyTracker.countBits
  
  val controlFifo = Module(new DroppingFifo(new ControlInstr.Expanded(params.amlet), fifoDepth, countBits))
  val predicateFifo = Module(new DroppingFifo(new PredicateInstr.Expanded(params.amlet), fifoDepth, countBits))
  val packetFifo = Module(new DroppingFifo(new PacketInstr.Expanded(params.amlet), fifoDepth, countBits))
  val aluLiteFifo = Module(new DroppingFifo(new ALULiteInstr.Expanded(params.amlet), fifoDepth, countBits))
  val loadStoreFifo = Module(new DroppingFifo(new LoadStoreInstr.Expanded(params.amlet), fifoDepth, countBits))
  val aluFifo = Module(new DroppingFifo(new ALUInstr.Expanded(params.amlet), fifoDepth, countBits))

  // Connect input data to FIFOs
  controlFifo.io.i.bits := bufferedInput.bits.control
  predicateFifo.io.i.bits := bufferedInput.bits.predicate  
  packetFifo.io.i.bits := bufferedInput.bits.packet
  aluLiteFifo.io.i.bits := bufferedInput.bits.aluLite
  loadStoreFifo.io.i.bits := bufferedInput.bits.loadStore
  aluFifo.io.i.bits := bufferedInput.bits.alu

  // Set valid signals based on instruction modes (drop if mode is NULL/None)
  controlFifo.io.i.valid := bufferedInput.valid
  predicateFifo.io.i.valid := bufferedInput.valid
  packetFifo.io.i.valid := bufferedInput.valid
  aluLiteFifo.io.i.valid := bufferedInput.valid
  loadStoreFifo.io.i.valid := bufferedInput.valid
  aluFifo.io.i.valid := bufferedInput.valid

  // Set drop signals based on instruction modes
  controlFifo.io.drop := bufferedInput.bits.control.mode === ControlInstr.Modes.None
  predicateFifo.io.drop := bufferedInput.bits.predicate.mode === PredicateInstr.Modes.None
  packetFifo.io.drop := bufferedInput.bits.packet.mode === PacketInstr.Modes.Null
  aluLiteFifo.io.drop := bufferedInput.bits.aluLite.mode === ALULiteInstr.Modes.None
  loadStoreFifo.io.drop := bufferedInput.bits.loadStore.mode === LoadStoreInstr.Modes.None
  aluFifo.io.drop := bufferedInput.bits.alu.mode === ALUInstr.Modes.None

  // Input is ready when all FIFOs are ready
  bufferedInput.ready := controlFifo.io.i.ready && predicateFifo.io.i.ready && packetFifo.io.i.ready &&
                         aluLiteFifo.io.i.ready && loadStoreFifo.io.i.ready && aluFifo.io.i.ready

  // Create vectors for easier processing
  val fifos = Seq(controlFifo, predicateFifo, packetFifo, aluLiteFifo, loadStoreFifo, aluFifo)
  val fifoOutputs = fifos.map(_.io.o)
  val fifoCounts = fifos.map(_.io.count)

  // Determine which instructions can be output (no dependencies on older instructions)
  val canOutput = Wire(Vec(6, Bool()))
  
  // Debug signals for waveform visibility - extracted from loops
  val instrIsOlder = Wire(Vec(6, Vec(6, Vec(fifoDepth, Bool()))))
  val hasBlockingDependency = Wire(Vec(6, Bool()))
  
  // Create DependencyChecker modules for each possible comparison
  val instructionTypes = Seq(
    new ControlInstr.Expanded(params.amlet),
    new PredicateInstr.Expanded(params.amlet), 
    new PacketInstr.Expanded(params.amlet),
    new ALULiteInstr.Expanded(params.amlet),
    new LoadStoreInstr.Expanded(params.amlet),
    new ALUInstr.Expanded(params.amlet)
  )
  
  val dependencyCheckers = Array.tabulate(6, 6, fifoDepth) { (i, j, k) =>
    Module(new DependencyChecker(instructionTypes(i), instructionTypes(j))).suggestName(s"depChecker_${i}_${j}_${k}")
  }
  
  for (i <- 0 until 6) {
    hasBlockingDependency(i) := false.B
    
    // Initialize all debug signals and connect DependencyCheckers
    for (j <- 0 until 6) {
      for (k <- 0 until fifoDepth) {
        instrIsOlder(i)(j)(k) := false.B
        
        // Connect DependencyChecker inputs
        dependencyCheckers(i)(j)(k).io.instr1 := fifoOutputs(i).bits
        dependencyCheckers(i)(j)(k).io.instr2 := fifos(j).io.allContents(k)
      }
    }
    
    // Check dependencies against all internal entries in all OTHER FIFOs
    for (j <- 0 until 6 if j != i) {
      val jFifo = fifos(j)
      
      // Check against all internal entries in FIFO j
      for (k <- 0 until fifoDepth) {
        when (jFifo.io.allValids(k) && fifoOutputs(i).valid) {
          // Determine age: larger count is older, tie-break by slot precedence
          when (jFifo.io.allCounts(k) > fifoCounts(i)) {
            instrIsOlder(i)(j)(k) := true.B
          } .elsewhen (jFifo.io.allCounts(k) === fifoCounts(i)) {
            instrIsOlder(i)(j)(k) := j.U < i.U // Earlier slots have higher precedence
          } .otherwise {
            instrIsOlder(i)(j)(k) := false.B
          }
          
          // Check for dependency if j is older using DependencyChecker module
          when (instrIsOlder(i)(j)(k) && dependencyCheckers(i)(j)(k).io.hasDependency) {
            hasBlockingDependency(i) := true.B
          }
        }
      }
    }
    
    canOutput(i) := fifoOutputs(i).valid && !hasBlockingDependency(i)
  }

  // Create internal output signal for buffering
  val internalOutput = Wire(DecoupledIO(new VLIWInstr.Expanded(params.amlet)))
  
  // Set output ready signals (only pop instructions that are being output)
  for (i <- 0 until 6) {
    fifoOutputs(i).ready := internalOutput.ready && canOutput(i)
  }

  // Build output instruction - connect data directly and mux only the modes
  internalOutput.bits.control := controlFifo.io.o.bits
  internalOutput.bits.control.mode := Mux(canOutput(0), controlFifo.io.o.bits.mode, ControlInstr.Modes.None)
  
  internalOutput.bits.predicate := predicateFifo.io.o.bits
  internalOutput.bits.predicate.mode := Mux(canOutput(1), predicateFifo.io.o.bits.mode, PredicateInstr.Modes.None)
  
  internalOutput.bits.packet := packetFifo.io.o.bits
  internalOutput.bits.packet.mode := Mux(canOutput(2), packetFifo.io.o.bits.mode, PacketInstr.Modes.Null)
  
  internalOutput.bits.aluLite := aluLiteFifo.io.o.bits
  internalOutput.bits.aluLite.mode := Mux(canOutput(3), aluLiteFifo.io.o.bits.mode, ALULiteInstr.Modes.None)
  
  internalOutput.bits.loadStore := loadStoreFifo.io.o.bits
  internalOutput.bits.loadStore.mode := Mux(canOutput(4), loadStoreFifo.io.o.bits.mode, LoadStoreInstr.Modes.None)
  
  internalOutput.bits.alu := aluFifo.io.o.bits
  internalOutput.bits.alu.mode := Mux(canOutput(5), aluFifo.io.o.bits.mode, ALUInstr.Modes.None)
  
  // Output is valid when at least one slot can be output
  internalOutput.valid := canOutput.reduceTree(_ || _)

  // Add optional output buffers
  val outputForwardBuffer = Module(new DecoupledBuffer(new VLIWInstr.Expanded(params.amlet), params.dependencyTracker.outputForwardBuffer))
  val outputBackwardBuffer = Module(new SkidBuffer(new VLIWInstr.Expanded(params.amlet), params.dependencyTracker.outputBackwardBuffer))
  
  // Chain: internal processing -> DecoupledBuffer -> SkidBuffer -> io.o
  outputForwardBuffer.io.i <> internalOutput
  outputBackwardBuffer.io.i <> outputForwardBuffer.io.o
  io.o <> outputBackwardBuffer.io.o

}

class DependencyChecker[T1 <: Instr.Expanded, T2 <: Instr.Expanded](instr1Type: T1, instr2Type: T2) extends Module {
  val io = IO(new Bundle {
    val instr1 = Input(instr1Type)
    val instr2 = Input(instr2Type)
    val hasDependency = Output(Bool())
    
    // Debug outputs for waveform visibility
    val rawDependency = Output(Bool())
    val wawDependency = Output(Bool())
  })

  val reads1 = io.instr1.getTReads()
  val writes1 = io.instr1.getTWrites()
  val reads2 = io.instr2.getTReads()
  val writes2 = io.instr2.getTWrites()
  
  // RAW: instr1 reads what instr2 writes
  // But skip dependencies for hardwired register 0 values
  io.rawDependency := reads1.map(r1 => 
    writes2.map(w2 => {
      val validDependency = r1.valid && w2.valid && (r1.bits === w2.bits)
      val isHardwiredRead = DependencyUtils.isRegister0Read(r1.bits)
      validDependency && !isHardwiredRead
    }).reduceOption(_ || _).getOrElse(false.B)
  ).reduceOption(_ || _).getOrElse(false.B)
  
  // WAW: both instructions write to same register
  // Special cases for address 0:
  // - A-reg 0 and P-reg 0: no WAW dependencies (hardwired)
  // - D-reg 0: WAW still matters for ordering
  io.wawDependency := writes1.map(w1 =>
    writes2.map(w2 => {
      val validWAW = w1.valid && w2.valid && (w1.bits === w2.bits)
      val isHardwiredWrite = DependencyUtils.isRegister0WriteNoWAW(w1.bits)
      validWAW && !isHardwiredWrite
    }).reduceOption(_ || _).getOrElse(false.B)
  ).reduceOption(_ || _).getOrElse(false.B)
  
  io.hasDependency := io.rawDependency || io.wawDependency
}

object DependencyUtils {
  /**
   * Check if instruction1 has a dependency on instruction2
   * Returns true if instruction1 reads from a register that instruction2 writes to (RAW),
   * or if both instructions write to the same register (WAW)
   * 
   * Special cases for register 0:
   * - A-reg 0 and P-reg 0: reads don't create dependencies (hardwired constants)
   * - D-reg 0: reads don't create dependencies, but WAW still matters
   */
  def hasDependency(instr1: Instr.Expanded, instr2: Instr.Expanded): Bool = {
    val reads1 = instr1.getTReads()
    val writes1 = instr1.getTWrites()
    val reads2 = instr2.getTReads()
    val writes2 = instr2.getTWrites()
    
    // RAW: instr1 reads what instr2 writes
    // But skip dependencies for hardwired register 0 values
    val rawDependency = reads1.map(r1 => 
      writes2.map(w2 => {
        val validDependency = r1.valid && w2.valid && (r1.bits === w2.bits)
        val isHardwiredRead = isRegister0Read(r1.bits)
        validDependency && !isHardwiredRead
      }).reduceOption(_ || _).getOrElse(false.B)
    ).reduceOption(_ || _).getOrElse(false.B)
    
    // WAW: both instructions write to same register
    // Special cases for address 0:
    // - A-reg 0 and P-reg 0: no WAW dependencies (hardwired)
    // - D-reg 0: WAW still matters for ordering
    val wawDependency = writes1.map(w1 =>
      writes2.map(w2 => {
        val validWAW = w1.valid && w2.valid && (w1.bits === w2.bits)
        val isHardwiredWrite = isRegister0WriteNoWAW(w1.bits)
        validWAW && !isHardwiredWrite
      }).reduceOption(_ || _).getOrElse(false.B)
    ).reduceOption(_ || _).getOrElse(false.B)
    
    rawDependency || wawDependency
  }
  
  /**
   * Check if a T-register encoding refers to register 0 in A, P, or D register spaces
   * T-register encoding: upper 2 bits indicate type (00=A, 01=D, 10=P, 11=L)
   */
  def isRegister0Read(tReg: UInt): Bool = {
    val regType = tReg >> (tReg.getWidth - 2)  // Extract upper 2 bits
    val regAddr = tReg & ((1.U << (tReg.getWidth - 2)) - 1.U)  // Extract lower bits
    
    // A-reg 0 (00) or P-reg 0 (10) or D-reg 0 (01) - all hardwired for reads
    val isAReg0 = (regType === 0.U) && (regAddr === 0.U)  // A-register 0
    val isPReg0 = (regType === 2.U) && (regAddr === 0.U)  // P-register 0  
    val isDReg0 = (regType === 1.U) && (regAddr === 0.U)  // D-register 0
    
    isAReg0 || isPReg0 || isDReg0
  }
  
  /**
   * Check if a T-register write to address 0 should skip WAW dependencies
   * A-reg 0 and P-reg 0 don't have WAW dependencies (hardwired)
   * D-reg 0 still has WAW dependencies for ordering
   */
  def isRegister0WriteNoWAW(tReg: UInt): Bool = {
    val regType = tReg >> (tReg.getWidth - 2)  // Extract upper 2 bits
    val regAddr = tReg & ((1.U << (tReg.getWidth - 2)) - 1.U)  // Extract lower bits
    
    // Only A-reg 0 (00) and P-reg 0 (10) skip WAW dependencies
    val isAReg0 = (regType === 0.U) && (regAddr === 0.U)  // A-register 0
    val isPReg0 = (regType === 2.U) && (regAddr === 0.U)  // P-register 0
    
    isAReg0 || isPReg0
  }
}



/** Generator object for creating DependencyTracker modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of DependencyTracker modules with configurable parameters.
  */
object DependencyTrackerGenerator extends fmvpu.ModuleGenerator {
  /** Create a DependencyTracker module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return DependencyTracker module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> DependencyTracker <bamletParamsFileName>")
      null
    } else {
      val params = BamletParams.fromFile(args(0))
      new DependencyTracker(params)
    }
  }
}
