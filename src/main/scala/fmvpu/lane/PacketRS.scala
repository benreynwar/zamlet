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
    
    // Output to send packet interface when send instruction is ready
    val sendOutput = Decoupled(new PacketInstrResolved(params))
    
    // Output to receive packet interface when receive instruction is ready
    val receiveOutput = Decoupled(new PacketInstrResolved(params))
    
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
    slots(freeSlot).bits.target := RSUtils.updateRegReadInfo(io.input.bits.target, io.writeInputs, params)
    slots(freeSlot).bits.sendLength := RSUtils.updateRegReadInfo(io.input.bits.sendLength, io.writeInputs, params)
    slots(freeSlot).bits.channel := RSUtils.updateRegReadInfo(io.input.bits.channel, io.writeInputs, params)
    slots(freeSlot).bits.mask := RSUtils.updateRegReadInfo(io.input.bits.mask, io.writeInputs, params)
  }
  
  
  // Update slots with write results for dependency resolution
  for (i <- 0 until params.nPacketRSSlots) {
    when (slots(i).valid) {
      slots(i).bits.target := RSUtils.updateRegReadInfo(slots(i).bits.target, io.writeInputs, params)
      slots(i).bits.sendLength := RSUtils.updateRegReadInfo(slots(i).bits.sendLength, io.writeInputs, params)
      slots(i).bits.channel := RSUtils.updateRegReadInfo(slots(i).bits.channel, io.writeInputs, params)
      slots(i).bits.mask := RSUtils.updateRegReadInfo(slots(i).bits.mask, io.writeInputs, params)
    }
  }
  
  // Helper function to determine if instruction should go to send or receive interface
  def isSendInstruction(mode: PacketModes.Type): Bool = {
    mode === PacketModes.Send || mode === PacketModes.ForwardAndAppend || mode === PacketModes.ReceiveForwardAndAppend
  }
  
  def isReceiveInstruction(mode: PacketModes.Type): Bool = {
    mode === PacketModes.Receive || mode === PacketModes.ReceiveAndForward || 
    mode === PacketModes.ReceiveForwardAndAppend || mode === PacketModes.GetWord
  }
  
  // Find ready instructions (all dependencies resolved AND target interface(s) are ready)
  val readySlots = slots.map(slot => {
    val depsResolved = slot.valid && 
                      slot.bits.target.resolved && 
                      slot.bits.sendLength.resolved && 
                      slot.bits.channel.resolved &&
                      slot.bits.mask.resolved
    
    val goesToSend = isSendInstruction(slot.bits.mode)
    val goesToReceive = isReceiveInstruction(slot.bits.mode)
    
    val interfaceReady = (!goesToSend || io.sendOutput.ready) && 
                        (!goesToReceive || io.receiveOutput.ready)
    
    depsResolved && interfaceReady
  })
  
  val hasReadySlot = readySlots.reduce(_ || _)
  val readySlotIdx = PriorityEncoder(readySlots)
  
  // Determine which interface(s) to send to
  val readySlotGoesToSend = hasReadySlot && isSendInstruction(slots(readySlotIdx).bits.mode)
  val readySlotGoesToReceive = hasReadySlot && isReceiveInstruction(slots(readySlotIdx).bits.mode)
  
  // Send interface output
  io.sendOutput.valid := readySlotGoesToSend
  io.sendOutput.bits := DontCare
  val readySlot = slots(readySlotIdx)
  io.sendOutput.bits.mode := readySlot.bits.mode
  io.sendOutput.bits.xTarget := readySlot.bits.xTarget
  io.sendOutput.bits.yTarget := readySlot.bits.yTarget
  io.sendOutput.bits.result := readySlot.bits.result
  io.sendOutput.bits.sendLength := readySlot.bits.sendLength.getData
  io.sendOutput.bits.channel := readySlot.bits.channel.getData(1, 0)
  io.sendOutput.bits.mask := readySlot.bits.mask.getData(0) // Extract single bit from mask
  
  // Receive interface output
  io.receiveOutput.valid := readySlotGoesToReceive
  io.receiveOutput.bits := DontCare
  io.receiveOutput.bits.mode := readySlot.bits.mode
  io.receiveOutput.bits.xTarget := readySlot.bits.xTarget
  io.receiveOutput.bits.yTarget := readySlot.bits.yTarget
  io.receiveOutput.bits.result := readySlot.bits.result
  io.receiveOutput.bits.sendLength := readySlot.bits.sendLength.getData
  io.receiveOutput.bits.channel := readySlot.bits.channel.getData(1, 0)
  io.receiveOutput.bits.mask := readySlot.bits.mask.getData(0) // Extract single bit from mask
  
  // Clear the slot when instruction is consumed by all required interfaces
  val slotConsumed = (!readySlotGoesToSend || io.sendOutput.ready) && 
                     (!readySlotGoesToReceive || io.receiveOutput.ready)
  
  when (hasReadySlot && slotConsumed) {
    slots(readySlotIdx).valid := false.B
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