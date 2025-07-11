package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Packet Reservation Station - manages out-of-order execution for packet operations
 */
class PacketRS(params: LaneParams) extends Module {
  val io = IO(new Bundle {
    // Input instruction from RegisterFileAndFriends
    val input = Flipped(Decoupled(new PacketInstrUnresolved(params)))
    
    // Output to packet interface when instruction is ready
    val output = Valid(new PacketInstrResolved(params))
    
    // Write results from execution units for dependency resolution
    val writeInputs = Input(Vec(params.nWritePorts, new WriteResult(params)))
  })

  // Reservation station slots
  val slots = RegInit(VecInit(Seq.fill(params.nPacketRSSlots)(0.U.asTypeOf(Valid(new PacketInstrUnresolved(params))))))
  
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
  for (i <- 0 until params.nPacketRSSlots) {
    when (slots(i).valid) {
      for (j <- 0 until params.nWritePorts) {
        slots(i).bits.target := updateRegReadInfo(slots(i).bits.target, io.writeInputs(j).valid, io.writeInputs(j).value, io.writeInputs(j).address)
        slots(i).bits.sendLength := updateRegReadInfo(slots(i).bits.sendLength, io.writeInputs(j).valid, io.writeInputs(j).value, io.writeInputs(j).address)
        slots(i).bits.channel := updateRegReadInfo(slots(i).bits.channel, io.writeInputs(j).valid, io.writeInputs(j).value, io.writeInputs(j).address)
      }
    }
  }
  
  // Find ready instruction (all dependencies resolved)
  val readySlots = slots.map(slot => 
    slot.valid && 
    slot.bits.target.resolved && 
    slot.bits.sendLength.resolved && 
    slot.bits.channel.resolved
  )
  
  val hasReadySlot = readySlots.reduce(_ || _)
  val readySlotIdx = PriorityEncoder(readySlots)
  
  // Output ready instruction
  io.output.valid := hasReadySlot
  
  when (hasReadySlot) {
    val readySlot = slots(readySlotIdx)
    
    io.output.bits.mode := readySlot.bits.mode
    io.output.bits.target := readySlot.bits.target.getData
    io.output.bits.result := readySlot.bits.result
    io.output.bits.sendLength := readySlot.bits.sendLength.getData
    io.output.bits.channel := readySlot.bits.channel.getData(1, 0) // Extract 2 bits for channel
    
    // Clear the slot that was dispatched
    slots(readySlotIdx).valid := false.B
  } .otherwise {
    // Default output values when no instruction is ready
    io.output.bits.mode := PacketModes.Receive
    io.output.bits.target := 0.U
    io.output.bits.result := 0.U.asTypeOf(new RegWithIdent(params))
    io.output.bits.sendLength := 0.U
    io.output.bits.channel := 0.U
  }
}

/** Generator object for creating PacketRS modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of PacketRS modules with configurable parameters.
  */
object PacketRSGenerator extends fmvpu.ModuleGenerator {
  /** Create a PacketRS module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return PacketRS module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> PacketRS <laneParamsFileName>")
      null
    } else {
      val params = LaneParams.fromFile(args(0))
      new PacketRS(params)
    }
  }
}