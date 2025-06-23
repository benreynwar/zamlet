package fmvpu.memory

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import fmvpu.core.{FMVPUParams, SendReceiveInstr, SendReceiveInstrResponse}
import fmvpu.network._
import fmvpu.ModuleGenerator
import chisel3.util.{MemoryWritePort, Queue, ShiftRegister, Decoupled, DecoupledIO}

import scala.io.Source


/**
 * Error signals for the ddmAccess module
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class DDMAccessErrors extends Bundle {
  /** Asserted when trying to start a new instruction while another is active
    * @group Signals
    */
  val badInstr = Bool()
  
  /** Asserted when receiving network payload without proper header
    * @group Signals
    */
  val badFromNetwork = Bool()
  
  /** Asserted when both header and DDM data are valid simultaneously
    * @group Signals
    */
  val sendConflict = Bool()
  
  /** Asserted when trying to enqueue to full send output FIFO
    * @group Signals
    */
  val sendFifoOverflow = Bool()
  
  /** Asserted when trying to store a receive instruction in an occupied slot
    * @group Signals
    */
  val receiveSlotOccupied = Bool()
}

/**
 * State bundle for tracking DDM send operations
 * @param params FMVPU system parameters for address width sizing
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class SendState(params: FMVPUParams) extends Bundle {
  /** Transfer is currently active
    * @group Signals
    */
  val active = Bool()
  
  /** Remaining words to transfer
    * @group Signals
    */
  val length = UInt(params.ddmAddrWidth.W)
  
  /** Current source DDM address for reading (Send operations)
    * @group Signals
    */
  val srcAddress = UInt(params.ddmAddrWidth.W)
  
  /** Destination address for packet header
    * @group Signals
    */
  val dstAddress = UInt((params.ddmAddrWidth + 1).W)
  
  /** Channel for send operations
    * @group Signals
    */
  val channel = UInt(log2Ceil(params.nChannels).W)
  
  /** Header has been sent for this transfer
    * @group Signals
    */
  val headerSent = Bool()
  
  /** Destination X coordinate
    * @group Signals
    */
  val destX = UInt(log2Ceil(params.nColumns).W)
  
  /** Destination Y coordinate
    * @group Signals
    */
  val destY = UInt(log2Ceil(params.nRows).W)
}

object SendState {
  def inactive(params: FMVPUParams): SendState = {
    val state = Wire(new SendState(params))
    state.active := false.B
    state.length := DontCare
    state.srcAddress := DontCare
    state.dstAddress := DontCare
    state.channel := DontCare
    state.headerSent := DontCare
    state.destX := DontCare
    state.destY := DontCare
    state
  }
}

/**
 * State bundle for tracking DDM receive operations
 * @param params FMVPU system parameters for address width sizing
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class ReceiveState(params: FMVPUParams) extends Bundle {
  /** Transfer is currently active
    * @group Signals
    */
  val active = Bool()
  
  /** Remaining words to transfer
    * @group Signals
    */
  val wordsRemaining = UInt(log2Ceil(params.maxPacketLength).W)
  
  /** Current destination address for writing
    * @group Signals
    */
  val currentAddr = UInt((params.ddmAddrWidth + 1).W)
  
  /** Packet expects a receive instruction
    * @group Signals
    */
  val expectsReceiveInstr = Bool()
  
  /** Identifier for receive instruction matching
    * @group Signals
    */
  val ident = UInt(params.networkIdentWidth.W)
}

object ReceiveState {
  def inactive(params: FMVPUParams): ReceiveState = {
    val state = Wire(new ReceiveState(params))
    state.active := false.B
    state.wordsRemaining := DontCare
    state.currentAddr := DontCare
    state.expectsReceiveInstr := DontCare
    state.ident := DontCare
    state
  }
}


/**
 * DDM (Distributed Data Memory) Access Controller
 * 
 * This module handles communication between the distributed data memory and the network.
 *
 * It only deals with data transmitted in packets.  Data can also be transmitted over the
 * network in a statically configured manner, however that data moves between DRF and is
 * not read from or written to the DDM.
 *
 * This controller can receive 'Send' or 'Receive' instructions.  A 'Send' instruction
 * causes it to produce a data packet and send it over the network.
 * A data packet specifies whether it expects to be 'caught' by a 'Receive' instruction or not.
 *
 * A receive instruction tells the controller to expect to receive a packet.  This is necessary
 * to receieve a packet that expects to be 'caught' be a 'Receive' instruction but is otherwise
 * not necessary.
 *
 * Send instruction are queued in a FIFO.  When a Send intruction finishes a complete signal
 * is sent back to the source of the instruction.
 *
 * A small number of Receive instructions can be stored.  The packets do not need to arrive in
 * the same order as the instructions.  Packets are labelled with the source and this is used
 * to distinguish them.  Packets with the same source and dest are expected to arrive in the 
 * same order (because we have simple routing).
 *
 * Packet header (doesn't expect Receive instruction)
 * type dest_x dest_y address length 
 * Packet header (does expect Receive instruction)
 * type dest_x dest_y address length ident
 *
 * Receiving a Packet
 *  - process header
 *  - if it expects a Receive instruction check to see if the 'ident' slot in the receive instruction
 *    queue contains an instruction.  If it doesn't it's an error.
 *  - As the words in the packet arrive send them to the DDM to be written.
 *  - After the last word arrives, if there is a corresponding Receive instruction mark it as completed
 *    and send a response to whereever the instruction came from.
 *
 * Sending a Packet
 *  - Recieve a 'Send' instruction and place it in the FIFO.
 *  - If we're not processing a packet pop a new one from the FIFO and start processing.
 *  - We have back pressure from the network so all of this needs to handle that.
 *  - Create a small FIFO that holds the words that will be sent to the network.  The depth
 *     of this needs to be at least the latency of the read.
 *  - If there is room in the output FIFO we either send a read to the DDM, or we make a header
 *     and put it into a shift register of the same length as the read latency.
 *  - The read data from the DDM or the output from this shift register are placed into the output
 *     FIFO.  If the output FIFO is full then this is an error (it should not happen because we
 *     previously checked that there was enough space before submitting the read to the DDM or
 *     placing the header in the shift register).
 * 
 * @param params FMVPU system parameters containing DDM configuration
 * @groupdesc Signals The actual hardware fields of the IO Bundle
 */
class ddmAccess(params: FMVPUParams) extends Module {

  val io = IO(new Bundle {
    /** Input instruction port for Send/Receive commands with TDM parameters
      * @group Signals
      */
    val instr = Input(Valid(new SendReceiveInstr(params)))
    val instrResponse = Output(Valid(new SendReceiveInstrResponse(params)))
    
    /** Data input from network with header/payload tagging
      * @group Signals  
      */
    val fromNetwork = Input(Valid(new HeaderTag(UInt(params.width.W))))
    
    /** Data output to network (from DDM reads) with ready/valid flow control
      * @group Signals
      */
    val toNetwork = DecoupledIO(new HeaderTag(UInt(params.width.W)))
    
    /** Channel selection for network output
      * @group Signals
      */
    val toNetworkChannel = Output(UInt(log2Ceil(params.nChannels).W))
    
    /** Current lane location for packet generation
      * @group Signals
      */
    val thisLoc = Input(new Location(params))
    
    /** Write port to distributed data memory
      * @group Signals
      */
    val writeDDM = Output(new MemoryWritePort(UInt(params.width.W), params.ddmAddrWidth, false))
    
    /** Write port to network control memory for configuration
      * @group Signals
      */
    val writeControl = Output(new MemoryWritePort(UInt(params.width.W), params.networkControlAddrWidth, false))
    
    /** Read port from distributed data memory
      * @group Signals
      */
    val readDDM = Flipped(new ValidReadPort(UInt(params.width.W), params.ddmAddrWidth))
    
    /** Error status signals indicating various fault conditions
      * @group Signals
      */
    val errors = Output(new DDMAccessErrors)
  })

  // Calculate control memory address range (starts after DDM space rounded up to power of 2)
  val ddmMaxAddr = params.ddmBankDepth * params.ddmNBanks
  val controlMemStartAddr = 1 << log2Ceil(ddmMaxAddr)

  // Default outputs
  io.writeDDM.enable := false.B
  io.writeDDM.address := DontCare
  io.writeDDM.data := DontCare
  io.writeControl.enable := false.B
  io.writeControl.address := DontCare
  io.writeControl.data := DontCare
  io.readDDM.address.valid := false.B
  io.readDDM.address.bits := DontCare
  io.errors.badInstr := false.B
  io.errors.badFromNetwork := false.B
  io.errors.sendConflict := false.B
  io.errors.sendFifoOverflow := false.B
  io.errors.receiveSlotOccupied := false.B
  io.instrResponse.valid := false.B
  io.instrResponse.bits := DontCare

  // Note to Claude: Please add implementations between the following comments.

  // SENDING

  // Constants
  val SEND_MODE = 0.U
  val RECEIVE_MODE = 1.U
  val SEND_FIFO_DEPTH = 4
  val SEND_OUTPUT_FIFO_DEPTH = 4
  val DDM_READ_LATENCY = 1

  // Bundle for send output FIFO entries
  class SendOutputEntry extends Bundle {
    val data = UInt(params.width.W)
    val isLast = Bool()
    val isHeader = Bool()
    val channel = UInt(log2Ceil(params.nChannels).W)
  }
  
  // Send output FIFO
  val sendOutputFIFO = Module(new Queue(new SendOutputEntry, SEND_OUTPUT_FIFO_DEPTH))

  // Receive 'Send' instructions and place them into a sendInstrFIFO.
  val sendInstrFIFO = Module(new Queue(new SendReceiveInstr(params), SEND_FIFO_DEPTH))
  sendInstrFIFO.io.enq.valid := io.instr.valid && io.instr.bits.mode === SEND_MODE
  sendInstrFIFO.io.enq.bits := io.instr.bits

  // If there is not an active sendState then pop an instruction from the FIFO
  // and use it to initialize the sendState.
  val sendState = RegInit(SendState.inactive(params))
  
  // Can we read from DDM this cycle (to be implemented based on output FIFO space)
  val sendCanRead = Wire(Bool())
  sendCanRead := sendOutputFIFO.io.count < (SEND_OUTPUT_FIFO_DEPTH - DDM_READ_LATENCY).U
  
  // We can pop when inactive or when we're about to finish the current operation
  val isLastWord = sendState.active && sendState.headerSent && (sendState.length === 1.U) && sendCanRead
  sendInstrFIFO.io.deq.ready := !sendState.active || isLastWord
  
  when(sendInstrFIFO.io.deq.fire) {
    sendState.active := true.B
    sendState.length := sendInstrFIFO.io.deq.bits.length
    sendState.srcAddress := sendInstrFIFO.io.deq.bits.srcAddr
    sendState.dstAddress := sendInstrFIFO.io.deq.bits.dstAddr
    sendState.channel := sendInstrFIFO.io.deq.bits.channel
    sendState.headerSent := false.B
    sendState.destX := Mux(sendInstrFIFO.io.deq.bits.useSameX, io.thisLoc.x, sendInstrFIFO.io.deq.bits.destX)
    sendState.destY := Mux(sendInstrFIFO.io.deq.bits.useSameY, io.thisLoc.y, sendInstrFIFO.io.deq.bits.destY)
  }

  // Bundle for data going through the shift register
  class SendShiftRegData extends Bundle {
    val data = UInt(params.width.W)
    val isHeader = Bool()
    val isLast = Bool()
  }
  
  // Shift register for header/DDM data
  val sendShiftRegIn = Wire(new SendShiftRegData)
  val sendShiftRegOut = ShiftRegister(sendShiftRegIn, DDM_READ_LATENCY)
  
  // If there is room in the sendOutputFIFO
  //   If the header has not been produced yet then place the header in a shiftregister (length should be the same as the
  //   read latency of the DDM).
  //   If the header has been produced then submit the read request to the DDM.  If it was the last request then
  //   mark the sendState as completed, and also add a 'final' bool to a shift register (this is used to know that
  //   the response from the DDM is the last word in a packet.
  
  // Default shift register input
  sendShiftRegIn.data := DontCare
  sendShiftRegIn.isHeader := false.B
  sendShiftRegIn.isLast := false.B
  
  when(sendState.active && sendCanRead) {
    when(!sendState.headerSent) {
      // Generate header and put it in shift register
      val packetHeader = Wire(new Header(params))
      packetHeader.dest.x := sendState.destX
      packetHeader.dest.y := sendState.destY
      packetHeader.src.x := io.thisLoc.x
      packetHeader.src.y := io.thisLoc.y
      packetHeader.address := sendState.dstAddress
      packetHeader.length := sendState.length
      packetHeader.expectsReceive := false.B  // Send instructions don't expect receive instructions
      packetHeader.ident := 0.U  // Not used when expectsReceive is false
      
      sendShiftRegIn.data := packetHeader.asUInt
      sendShiftRegIn.isHeader := true.B
      sendShiftRegIn.isLast := false.B
      sendState.headerSent := true.B
    }.otherwise {
      // Submit DDM read request
      io.readDDM.address.valid := true.B
      io.readDDM.address.bits := sendState.srcAddress
      
      // Shift register tracks metadata for DDM reads
      sendShiftRegIn.data := DontCare
      sendShiftRegIn.isHeader := false.B
      sendShiftRegIn.isLast := sendState.length === 1.U
      
      // Advance send state
      sendState.srcAddress := sendState.srcAddress + 1.U
      sendState.length := sendState.length - 1.U
      when(sendState.length === 1.U) {
        sendState.active := false.B
      }
    }
  }

  // If the output from the header shiftregister or the response from the DDM is valid then add them to the sendOutputFIFO.
  // If both are valid then this is an error to add to the error bundle.
  // If the FIFO is full and one is valid then this is also an error.
  // There should also be a bit in this FIFO that indicates whether this word is the final one in a packet.
  
  // Combine header from shift register and data from DDM
  val sendOutputEntry = Wire(new SendOutputEntry)
  sendOutputEntry.channel := sendState.channel
  sendOutputEntry.data := DontCare
  sendOutputEntry.isLast := DontCare
  sendOutputEntry.isHeader := DontCare
  
  // Determine if we have valid data to enqueue
  val headerValid = Wire(Bool())
  headerValid := sendShiftRegOut.isHeader
  dontTouch(headerValid)
  val dataValid = Wire(Bool())
  dataValid := io.readDDM.data.valid
  dontTouch(dataValid)
  
  // Error checking
  when(headerValid && dataValid) {
    io.errors.sendConflict := true.B
  }
  
  // Route to output FIFO
  when(headerValid || dataValid) {
    sendOutputFIFO.io.enq.valid := true.B
    sendOutputEntry.data := Mux(headerValid, sendShiftRegOut.data, io.readDDM.data.bits)
    sendOutputEntry.isLast := Mux(headerValid, false.B, sendShiftRegOut.isLast)
    sendOutputEntry.isHeader := headerValid
    sendOutputFIFO.io.enq.bits := sendOutputEntry
    
    // Error if FIFO is full
    when(!sendOutputFIFO.io.enq.ready) {
      io.errors.sendFifoOverflow := true.B
    }
  }.otherwise {
    sendOutputFIFO.io.enq.valid := false.B
    sendOutputFIFO.io.enq.bits := DontCare
  }

  // Connect the output from the sendOutputFIFO to the toNetwork.  When we send the last word in a packet, send an response
  // indicates that it has compeleted (instrResponse).
  
  // Connect send output FIFO directly to network interface
  io.toNetwork.valid := sendOutputFIFO.io.deq.valid
  io.toNetwork.bits.bits := sendOutputFIFO.io.deq.bits.data
  io.toNetwork.bits.header := sendOutputFIFO.io.deq.bits.isHeader
  sendOutputFIFO.io.deq.ready := io.toNetwork.ready
  io.toNetworkChannel := sendOutputFIFO.io.deq.bits.channel
  
  // Send completion response when last word is sent
  when(sendOutputFIFO.io.deq.fire && sendOutputFIFO.io.deq.bits.isLast) {
    io.instrResponse.valid := true.B
    io.instrResponse.bits.mode := SEND_MODE
    io.instrResponse.bits.ident := 0.U  // Send instructions don't use ident
  }

  // RECEIVING

  // Storage for pending receive instructions indexed by ident
  val pendingReceiveInstructions = RegInit(VecInit(Seq.fill(1 << params.networkIdentWidth)({
    val entry = Wire(Valid(new SendReceiveInstr(params)))
    entry.valid := false.B
    entry.bits := DontCare
    entry
  })))

  // Receive an 'Receive' instruction.  Place that instruction in the pendingReceiveInstructions[ident].  If there was
  // already an instruction there then that is an error.
  when(io.instr.valid && io.instr.bits.mode === RECEIVE_MODE) {
    val ident = io.instr.bits.ident
    when(pendingReceiveInstructions(ident).valid) {
      io.errors.receiveSlotOccupied := true.B
    }.otherwise {
      pendingReceiveInstructions(ident).valid := true.B
      pendingReceiveInstructions(ident).bits := io.instr.bits
    }
  }

  // Receive state for tracking incoming packet processing
  val receiveState = RegInit(ReceiveState.inactive(params))

  // We receive a packet.  If the header indicates that we expect it to be 'caught' then check for a corresponding instruction
  // if pendingReceiveInstructions. If it does not exist then that is an error.
  // The receiveState becomes active.
  when(io.fromNetwork.valid && io.fromNetwork.bits.header) {
    // Process packet header
    when(receiveState.active) {
      io.errors.badFromNetwork := true.B
    }.otherwise {
      val header = Header.fromBits(io.fromNetwork.bits.bits, params)
      val receiveInstruction = pendingReceiveInstructions(header.ident)
      
      receiveState.active := true.B
      receiveState.wordsRemaining := header.length
      receiveState.currentAddr := header.address
      receiveState.expectsReceiveInstr := header.expectsReceive
      receiveState.ident := header.ident
      
      when(header.expectsReceive && !receiveInstruction.valid) {
        io.errors.badFromNetwork := true.B
      }
    }
  }
  //
  // As words arrive for the packet we work out whether the write targets the DDM or the control memory and submit them
  // accordingly.
  //
  when(io.fromNetwork.valid && !io.fromNetwork.bits.header) {
    // Process packet data
    when(!receiveState.active) {
      io.errors.badFromNetwork := true.B
    }.otherwise {
      // Determine if write goes to DDM or control memory
      when(receiveState.currentAddr >= controlMemStartAddr.U) {
        // Write to control memory
        io.writeControl.enable := true.B
        io.writeControl.address := receiveState.currentAddr - controlMemStartAddr.U
        io.writeControl.data := io.fromNetwork.bits.bits
      }.otherwise {
        // Write to DDM
        io.writeDDM.enable := true.B
        io.writeDDM.address := receiveState.currentAddr
        io.writeDDM.data := io.fromNetwork.bits.bits
      }
      
      // Update receive state
      receiveState.currentAddr := receiveState.currentAddr + 1.U
      receiveState.wordsRemaining := receiveState.wordsRemaining - 1.U
      
      when(receiveState.wordsRemaining === 1.U) {
        // Last word - complete the transfer
        receiveState.active := false.B
        
        when(receiveState.expectsReceiveInstr) {
          // Send completion response for receive instruction
          io.instrResponse.valid := true.B
          io.instrResponse.bits.mode := RECEIVE_MODE
          io.instrResponse.bits.ident := receiveState.ident
          
          // Clear the pending receive instruction
          pendingReceiveInstructions(receiveState.ident).valid := false.B
        }
      }
    }
  }
  // When the final word is written we send a instrResponse (if the packet was 'caught' by a Receive instruction).
}

/** Generator object for creating ddmAccess modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of ddmAccess modules with parameters loaded from JSON files.
  */
object ddmAccessGenerator extends ModuleGenerator {
  /** Create a ddmAccess module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return ddmAccess module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    // Parse arguments
    if (args.length < 1) {
      println("Usage: <command> <outputDir> ddmAccess <paramsFileName>")
      null
    } else {
      val params = FMVPUParams.fromFile(args(0))
      new ddmAccess(params)
    }
  }
}
