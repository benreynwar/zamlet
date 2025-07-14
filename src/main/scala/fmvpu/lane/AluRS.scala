package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * ALU Reservation Station - manages out-of-order execution for ALU operations
 */
class AluRS(params: LaneParams) extends Module {
  val io = IO(new Bundle {
    // Input instruction from RegisterFileAndFriends
    val input = Flipped(Decoupled(new ALUInstrUnresolved(params)))
    
    // Output to ALU when instruction is ready
    val output = Valid(new ALUInstrResolved(params))
    
    // Write results from execution units for dependency resolution
    val writeInputs = Input(Vec(params.nWritePorts, new WriteResult(params)))
  })

  // Reservation station slots - reuse ALUInstrUnresolved bundle
  val slots = RegInit(VecInit(Seq.fill(params.nAluRSSlots)(0.U.asTypeOf(Valid(new ALUInstrUnresolved(params))))))
  
  // Find free slot for new instruction
  val freeSlotOH = PriorityEncoderOH(slots.map(!_.valid))
  val freeSlot = PriorityEncoder(slots.map(!_.valid))
  val hasFreeLot = slots.map(!_.valid).reduce(_ || _)
  
  // Ready to accept new instruction if we have a free slot
  io.input.ready := hasFreeLot
  
  // Accept new instruction when interface fires
  when (io.input.fire) {
    slots(freeSlot).valid := true.B
    slots(freeSlot).bits := io.input.bits
    slots(freeSlot).bits.src1 := RSUtils.updateRegReadInfo(io.input.bits.src1, io.writeInputs, params)
    slots(freeSlot).bits.src2 := RSUtils.updateRegReadInfo(io.input.bits.src2, io.writeInputs, params)
    slots(freeSlot).bits.accum := RSUtils.updateRegReadInfo(io.input.bits.accum, io.writeInputs, params)
    slots(freeSlot).bits.mask := RSUtils.updateRegReadInfo(io.input.bits.mask, io.writeInputs, params)
  }
  
  
  // Update slots with write results for dependency resolution
  for (i <- 0 until params.nAluRSSlots) {
    when (slots(i).valid) {
      slots(i).bits.src1 := RSUtils.updateRegReadInfo(slots(i).bits.src1, io.writeInputs, params)
      slots(i).bits.src2 := RSUtils.updateRegReadInfo(slots(i).bits.src2, io.writeInputs, params)
      slots(i).bits.accum := RSUtils.updateRegReadInfo(slots(i).bits.accum, io.writeInputs, params)
      slots(i).bits.mask := RSUtils.updateRegReadInfo(slots(i).bits.mask, io.writeInputs, params)
    }
  }
  
  // Find ready instruction (all dependencies resolved)
  val readySlots = slots.map(slot => 
    slot.valid && 
    slot.bits.src1.resolved && 
    slot.bits.src2.resolved && 
    slot.bits.accum.resolved && 
    slot.bits.mask.resolved
  )
  readySlots.foreach(dontTouch(_))
  
  val hasReadySlot = readySlots.reduce(_ || _)
  val readySlotIdx = PriorityEncoder(readySlots)
  
  // Output ready instruction
  io.output.valid := hasReadySlot
  
  when (hasReadySlot) {
    val readySlot = slots(readySlotIdx)
    
    io.output.bits.mode := readySlot.bits.mode
    io.output.bits.src1 := readySlot.bits.src1.getData
    io.output.bits.src2 := readySlot.bits.src2.getData
    io.output.bits.accum := readySlot.bits.accum.getData
    io.output.bits.mask := readySlot.bits.mask.getData(0) // Extract single bit from mask
    io.output.bits.dstAddr := readySlot.bits.dstAddr
    io.output.bits.useLocalAccum := readySlot.bits.useLocalAccum
    
    // Clear the slot that was dispatched
    slots(readySlotIdx).valid := false.B
  } .otherwise {
    // Default output values when no instruction is ready
    io.output.bits.mode := ALUModes.Add
    io.output.bits.src1 := 0.U
    io.output.bits.src2 := 0.U
    io.output.bits.accum := 0.U
    io.output.bits.mask := false.B
    io.output.bits.dstAddr := 0.U.asTypeOf(new RegWithIdent(params))
    io.output.bits.useLocalAccum := false.B
  }
}

/** Generator object for creating AluRS modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of AluRS modules with configurable parameters.
  */
object AluRSGenerator extends fmvpu.ModuleGenerator {
  /** Create an AluRS module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return AluRS module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> AluRS <laneParamsFileName>")
      null
    } else {
      val params = LaneParams.fromFile(args(0))
      new AluRS(params)
    }
  }
}
