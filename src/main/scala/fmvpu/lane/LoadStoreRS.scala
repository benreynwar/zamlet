package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Load/Store Reservation Station - manages out-of-order execution for memory operations
 */
class LoadStoreRS(params: LaneParams) extends Module {
  val io = IO(new Bundle {
    // Input instruction from RegisterFileAndFriends
    val input = Flipped(Decoupled(new LdStInstrUnresolved(params)))
    
    // Output to memory unit when instruction is ready
    val output = Valid(new LdStInstrResolved(params))
    
    // Write results from execution units for dependency resolution
    val writeInputs = Input(Vec(params.nWritePorts, new WriteResult(params)))
  })

  // Reservation station slots
  val slots = RegInit(VecInit(Seq.fill(params.nLdStRSSlots)(0.U.asTypeOf(Valid(new LdStInstrUnresolved(params))))))
  
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
  }
  
  // Helper function to update RegReadInfo with write result if addresses match
  def updateRegReadInfo(regInfo: RegReadInfo, writeValid: Bool, writeValue: UInt, writeAddr: RegWithIdent): RegReadInfo = {
    val result = Wire(new RegReadInfo(params))
    val regRef = regInfo.getRegWithIdent
    
    when (!regInfo.resolved && writeValid && 
          regRef.regAddr === writeAddr.regAddr &&
          regRef.writeIdent === writeAddr.writeIdent) {
      // Address matches - resolve this dependency
      result.resolved := true.B
      result.value := writeValue
    } .otherwise {
      // No match - keep original value
      result := regInfo
    }
    
    result
  }
  
  // Update slots with write results for dependency resolution
  for (i <- 0 until params.nLdStRSSlots) {
    when (slots(i).valid) {
      for (j <- 0 until params.nWritePorts) {
        slots(i).bits.baseAddress := updateRegReadInfo(slots(i).bits.baseAddress, io.writeInputs(j).valid, io.writeInputs(j).value, io.writeInputs(j).address)
        slots(i).bits.offset := updateRegReadInfo(slots(i).bits.offset, io.writeInputs(j).valid, io.writeInputs(j).value, io.writeInputs(j).address)
        slots(i).bits.value := updateRegReadInfo(slots(i).bits.value, io.writeInputs(j).valid, io.writeInputs(j).value, io.writeInputs(j).address)
      }
    }
  }
  
  // Find ready instruction (all dependencies resolved)
  val readySlots = slots.map(slot => 
    slot.valid && 
    slot.bits.baseAddress.resolved && 
    slot.bits.offset.resolved && 
    (slot.bits.mode === LdStModes.Load || slot.bits.value.resolved) // Only stores need value resolved
  )
  
  val hasReadySlot = readySlots.reduce(_ || _)
  val readySlotIdx = PriorityEncoder(readySlots)
  
  // Output ready instruction
  io.output.valid := hasReadySlot
  
  when (hasReadySlot) {
    val readySlot = slots(readySlotIdx)
    
    io.output.bits.mode := readySlot.bits.mode
    io.output.bits.baseAddress := readySlot.bits.baseAddress.getData
    io.output.bits.offset := readySlot.bits.offset.getData
    io.output.bits.dstAddr := readySlot.bits.dstAddr
    io.output.bits.value := readySlot.bits.value.getData
    
    // Clear the slot that was dispatched
    slots(readySlotIdx).valid := false.B
  } .otherwise {
    // Default output values when no instruction is ready
    io.output.bits.mode := LdStModes.Load
    io.output.bits.baseAddress := 0.U
    io.output.bits.offset := 0.U
    io.output.bits.dstAddr := 0.U.asTypeOf(new RegWithIdent(params))
    io.output.bits.value := 0.U
  }
}

/** Generator object for creating LoadStoreRS modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of LoadStoreRS modules with configurable parameters.
  */
object LoadStoreRSGenerator extends fmvpu.ModuleGenerator {
  /** Create a LoadStoreRS module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return LoadStoreRS module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> LoadStoreRS <laneParamsFileName>")
      null
    } else {
      val params = LaneParams.fromFile(args(0))
      new LoadStoreRS(params)
    }
  }
}