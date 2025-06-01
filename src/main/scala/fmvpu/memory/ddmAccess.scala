package fmvpu.memory

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import fmvpu.core.{FMPVUParams, SendReceiveInstr}
import fmvpu.network._
import fmvpu.ModuleGenerator
import chisel3.util.{MemoryWritePort}

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
}

/**
 * State bundle for tracking DDM transfer operations
 * @param params FMPVU system parameters for address width sizing
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class DDMTransferState(params: FMPVUParams) extends Bundle {
  /** Transfer is currently active
    * @group Signals
    */
  val active = Bool()
  
  /** Remaining words to transfer
    * @group Signals
    */
  val length = UInt(params.ddmAddrWidth.W)
  
  /** Current DDM address for transfer
    * @group Signals
    */
  val address = UInt(params.ddmAddrWidth.W)
  
  /** Time slot offset for TDM scheduling
    * @group Signals
    */
  val slotOffset = UInt(params.ddmAddrWidth.W)
  
  /** Time slot spacing for TDM scheduling
    * @group Signals
    */
  val slotSpacing = UInt(params.ddmAddrWidth.W)
  
  /** Word count for TDM timing
    * @group Signals
    */
  val wordCount = UInt(params.ddmAddrWidth.W)
}


/**
 * DDM (Distributed Data Memory) Access Controller
 * 
 * This module handles communication between the distributed data memory and the network.
 * It processes Send and Receive instructions to transfer data blocks with time-division
 * multiplexing support for coordinated network sharing between multiple nodes.
 * 
 * Features:
 * - Send operations: Read sequential data from DDM and send to network
 * - Receive operations: Receive data from network and write to sequential DDM addresses
 * - Time-division multiplexing via slotSpacing/slotOffset for coordinated network sharing
 * - Slot offset: Delays when this node begins using its allocated network time slots
 * - Slot spacing: Interval between network time slots allocated to this node
 * - Header-based network packet handling for receive operations
 * - Error detection for instruction conflicts and invalid network data
 * 
 * @param params FMPVU system parameters containing DDM configuration
 * @groupdesc Signals The actual hardware fields of the IO Bundle
 */
class ddmAccess(params: FMPVUParams) extends Module {

  val io = IO(new Bundle {
    /** Input instruction port for Send/Receive commands with TDM parameters
      * @group Signals
      */
    val instr = Input(Valid(new SendReceiveInstr(params)))
    
    /** Data input from network with header/payload tagging
      * @group Signals  
      */
    val fromNetwork = Input(Valid(new HeaderTag(UInt(params.width.W))))
    
    /** Data output to network (from DDM reads) with TDM scheduling
      * @group Signals
      */
    val toNetwork = Output(Valid(UInt(params.width.W)))
    
    /** Write port to distributed data memory for sequential addresses
      * @group Signals
      */
    val writeDDM = Output(new MemoryWritePort(UInt(params.width.W), params.ddmAddrWidth, false))
    
    /** Read port from distributed data memory for sequential addresses
      * @group Signals
      */
    val readDDM = Flipped(new ValidReadPort(UInt(params.width.W), params.ddmAddrWidth))
    
    /** Error status signals indicating various fault conditions
      * @group Signals
      */
    val errors = Output(new DDMAccessErrors)
  })

  // Transfer state for Send operations (DDM -> Network)
  val sendState = RegInit(0.U.asTypeOf(new DDMTransferState(params)))
  
  // Transfer state for Receive operations (Network -> DDM)  
  val receiveState = RegInit(0.U.asTypeOf(new DDMTransferState(params)))
  
  // Helper function to check if a transfer should occur in this cycle based on TDM schedule
  def shouldTransfer(state: DDMTransferState): Bool = {
    (state.wordCount >= state.slotOffset) &&
    ((state.wordCount - state.slotOffset) % state.slotSpacing === 0.U)
  }
  
  // Helper function to initialize transfer state from instruction
  def initTransfer(state: DDMTransferState, instr: SendReceiveInstr): Unit = {
    state.active := true.B
    state.length := instr.length
    state.address := instr.addr
    state.slotOffset := instr.slotOffset
    state.slotSpacing := instr.slotSpacing
    state.wordCount := 0.U
  }
  
  // Helper function to advance transfer state (address increment, length decrement)
  def advanceTransfer(state: DDMTransferState): Unit = {
    state.length := state.length - 1.U
    state.address := state.address + 1.U
    when (state.length === 1.U) {
      state.active := false.B
    }
  }

  io.toNetwork := io.readDDM.data

  // Default outputs
  io.writeDDM.enable := false.B
  io.writeDDM.address := DontCare
  io.writeDDM.data := DontCare
  io.readDDM.address.valid := false.B
  io.readDDM.address.bits := DontCare
  io.errors.badInstr := false.B
  io.errors.badFromNetwork := false.B

  // Handle Send/Receive instructions
  when (io.instr.valid) {
    when (io.instr.bits.mode === 0.U) { // Send instruction
      when (sendState.active) {
        // Error: Cannot start new Send while previous Send is still active
        io.errors.badInstr := true.B
      }.otherwise {
        initTransfer(sendState, io.instr.bits)
      }
    }.otherwise { // Receive instruction (mode === 1.U)
      when (receiveState.active) {
        // Error: Cannot start new Receive while previous Receive is still active
        io.errors.badInstr := true.B
      }.otherwise {
        initTransfer(receiveState, io.instr.bits)
      }
    }
  }

  // Handle read operations (Send)
  when (sendState.active) {
    when (shouldTransfer(sendState)) {
      io.readDDM.address.valid := true.B
      io.readDDM.address.bits := sendState.address
      advanceTransfer(sendState)
    }.otherwise {
      io.readDDM.address.valid := false.B
    }
    
    sendState.wordCount := sendState.wordCount + 1.U
  }

  // Handle write operations (Receive)
  when (io.fromNetwork.valid) {
    when (!receiveState.active) {
      when (io.fromNetwork.bits.header) {
        // Extract address and length from the header
        val header = io.fromNetwork.bits.bits.asTypeOf(new Header(params))
        receiveState.active := true.B
        receiveState.length := header.length
        receiveState.address := header.address
        receiveState.slotOffset := 0.U   // Start immediately for header-initiated transfers
        receiveState.slotSpacing := 1.U  // Use every time slot for header-initiated transfers
        receiveState.wordCount := 0.U
      }.otherwise {
        // Error: Received network payload without header to start transfer
        io.errors.badFromNetwork := true.B
      }
    }.otherwise {
      when (shouldTransfer(receiveState)) {
        io.writeDDM.enable := true.B
        io.writeDDM.address := receiveState.address
        io.writeDDM.data := io.fromNetwork.bits.bits
        advanceTransfer(receiveState)
      }
      
      receiveState.wordCount := receiveState.wordCount + 1.U
    }
  }
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
      val params = FMPVUParams.fromFile(args(0))
      new ddmAccess(params)
    }
  }
}
