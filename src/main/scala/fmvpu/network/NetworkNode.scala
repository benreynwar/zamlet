package fmvpu.network

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import fmvpu.core.FMPVUParams
import fmvpu.utils._
import fmvpu.ModuleGenerator
import chisel3.util.DecoupledIO

import scala.io.Source


/**
 * Control signals for configuring NetworkNode routing behavior
 * @param params FMPVU parameters for sizing the control vectors
 * @groupdesc Signals The actual hardware fields of the Bundle
 */


class NetworkNodeControl(params: FMPVUParams) extends Bundle {
  /** Input selection for north-south direction per channel
    * @group Signals
    */
  val nsInputSel = Vec(params.nChannels, Bool())
  
  /** Input selection for west-east direction per channel
    * @group Signals
    */
  val weInputSel = Vec(params.nChannels, Bool())
  
  /** Crossbar selection for north-south routing per channel
    * @group Signals
    */
  val nsCrossbarSel = Vec(params.nChannels, UInt(log2Ceil(params.nChannels + 2).W))
  
  /** Crossbar selection for west-east routing per channel
    * @group Signals
    */
  val weCrossbarSel = Vec(params.nChannels, UInt(log2Ceil(params.nChannels + 2).W))
  
  /** Data register file selection signal
    * @group Signals
    */
  val drfSel = UInt(log2Ceil(params.nChannels * 2).W)
  
  /** Data memory selection signal
    * @group Signals
    */
  val ddmSel = UInt(log2Ceil(params.nChannels * 2).W)
  
  /** Enable driving outputs in each direction per channel
    * @group Signals
    */
  val nDrive = Vec(params.nChannels, Bool())
  val sDrive = Vec(params.nChannels, Bool())
  val wDrive = Vec(params.nChannels, Bool())
  val eDrive = Vec(params.nChannels, Bool())
}

/**
 * Network node that can operate in either packet or static mode
 * 
 * This module implements a configurable network router that supports:
 * - Packet mode: Uses switches and FIFOs for store-and-forward routing as nChannels independent networks
 * - Static mode: Uses crossbars and delay lines for deterministic routing as a single unified network
 * - DDM (Data Memory) and DRF (Data Register File) access interfaces
 * - Configurable routing delay and memory behavior
 * 
 * The node contains 4 directional ports (N,S,W,E) with multiple channels per direction.
 * In packet mode, packets are routed based on header information on independent channels.
 * In static mode, data flows according to static control signals across all channels.
 * 
 * @param params FMPVU parameters defining channel counts, widths, and memory sizes
 * @groupdesc Signals The actual hardware fields of the IO Bundle
 */
class NetworkNode(params: FMPVUParams) extends Module {
  val io = IO(new Bundle {
    /** Input channels from 4 directions: North(0), South(1), West(2), East(3)
      * @group Signals
      */
    val inputs = Vec(4, Vec(params.nChannels, new PacketInterface(params.width)))
    
    /** Output channels to 4 directions: North(0), South(1), West(2), East(3)
      * @group Signals
      */
    val outputs = Vec(4, Vec(params.nChannels, Flipped(new PacketInterface(params.width))))
    
    /** Interface to Data Register File for temporary data storage
      * @group Signals
      */
    val toDRF = Output(Valid(UInt(params.width.W)))
    val fromDRF = Input(Valid(UInt(params.width.W)))
    
    /** Interface to Data Memory for packet/data storage
      * @group Signals
      */
    val toDDM = Output(Valid(new HeaderTag(UInt(params.width.W))))
    val fromDDM = Input(Valid(UInt(params.width.W)))
    
    /** Control signals for static mode routing configuration
      * @group Signals
      */
    val control = Input(new NetworkNodeControl(params))
    
    /** This node's location in the network grid
      * @group Signals
      */
    val thisLoc = Input(new Location(params))
    
    /** Configuration signals for mode and timing setup
      * @group Signals
      */
    val configValid = Input(Bool())
    val configIsPacketMode = Input(Bool())
    val configDelay = Input(UInt(log2Ceil(params.networkMemoryDepth + 1).W))
  })

  // Template for HeaderTag type inference
  val headerTemplate = new HeaderTag(UInt(params.width.W))

  /** Current operating mode: true for packet mode, false for static mode */
  val isPacketMode = RegInit(true.B)
  when (io.configValid) {
    isPacketMode := io.configIsPacketMode
  }

  // Network components
  val crossbar = Module(new NetworkCrossbar(params))
  val switches = Seq.fill(params.nChannels)(withReset(reset.asBool || io.configValid) { 
    Module(new NetworkSwitch(params)) 
  })

  // DDM arbitration signals
  val ddmArbitrationActive = RegInit(false.B)
  val ddmArbitrationChannelPointer = RegInit(0.U(log2Ceil(params.nChannels).W))
  val ddmArbitrationRemaining = RegInit(0.U(log2Ceil(params.maxPacketLength+1).W))
  
  // Aggregated switch outputs for DDM access
  val switchesToDDM = Wire(DecoupledIO(headerTemplate))
  switchesToDDM.valid := false.B
  switchesToDDM.bits := DontCare

  // Route DDM interface based on operating mode
  when (isPacketMode) {
    io.toDDM.valid := switchesToDDM.valid
    io.toDDM.bits := switchesToDDM.bits
    switchesToDDM.ready := true.B
  }.otherwise {
    io.toDDM.valid := crossbar.io.toDDM.valid
    io.toDDM.bits.bits := crossbar.io.toDDM.bits
    io.toDDM.bits.header := false.B
    switchesToDDM.ready := false.B
  }

  // DDM arbitration next-state logic
  val nextDdmArbitrationActive = Wire(Bool())
  val nextDdmArbitrationChannelPointer = Wire(UInt(log2Ceil(params.nChannels).W))
  val nextDdmArbitrationRemaining = Wire(UInt(log2Ceil(params.maxPacketLength+1).W))
  
  // Default to current state
  nextDdmArbitrationActive := ddmArbitrationActive
  nextDdmArbitrationChannelPointer := ddmArbitrationChannelPointer
  nextDdmArbitrationRemaining := ddmArbitrationRemaining

  // Connect crossbar to external interfaces
  crossbar.io.fromDRF := io.fromDRF
  io.toDRF := crossbar.io.toDRF
  crossbar.io.fromDDM := io.fromDDM
  crossbar.io.control := io.control

  // Collect all switch DDM outputs
  val allSwitchToDDM = Wire(Vec(params.nChannels, DecoupledIO(headerTemplate)))
  for (i <- 0 until params.nChannels) {
    allSwitchToDDM(i) <> switches(i).io.toDDM
  }
  
  // Connect selected switch to aggregated DDM output
  switchesToDDM.valid := allSwitchToDDM(ddmArbitrationChannelPointer).valid && isPacketMode
  switchesToDDM.bits := allSwitchToDDM(ddmArbitrationChannelPointer).bits

  // Configure each channel and its associated switch
  for (channelIndex <- 0 until params.nChannels) {
    val currentSwitch = switches(channelIndex)
    
    // Connect switch location interface
    currentSwitch.io.thisLoc := io.thisLoc
    
    // DDM to switch interface (currently unused)
    currentSwitch.io.fromDDM.valid := false.B
    currentSwitch.io.fromDDM.bits := DontCare
    
    // DDM arbitration: manage which switch can access DDM
    val isSelectedForDDM = isPacketMode && ddmArbitrationChannelPointer === channelIndex.U
    when (isSelectedForDDM) {
      allSwitchToDDM(channelIndex).ready := switchesToDDM.ready
      
      when (!ddmArbitrationActive) {
        // Not actively transmitting - check for new packet start
        when (currentSwitch.io.toDDM.valid && currentSwitch.io.toDDM.bits.header) {
          // Grant DDM access and extract packet length
          nextDdmArbitrationActive := true.B
          val packetHeader = Header.fromBits(currentSwitch.io.toDDM.bits.bits, params)
          nextDdmArbitrationRemaining := packetHeader.length
        }.otherwise {
          // Move to next channel in round-robin fashion
          nextDdmArbitrationChannelPointer := (ddmArbitrationChannelPointer + 1.U) % params.nChannels.U
        }
      }.otherwise {
        // Actively transmitting - count down remaining transfers
        when (currentSwitch.io.toDDM.valid && currentSwitch.io.toDDM.ready) {
          nextDdmArbitrationRemaining := ddmArbitrationRemaining - 1.U
          when (ddmArbitrationRemaining === 1.U) {
            nextDdmArbitrationActive := false.B
          }
        }
      }
    }.otherwise {
      // This channel is not selected for DDM access
      allSwitchToDDM(channelIndex).ready := false.B
    }


    // Configure input/output routing for each direction (N=0, S=1, W=2, E=3)
    for (direction <- 0 until 4) {
      // Route inputs based on operating mode
      when (isPacketMode) {
        // Packet mode: inputs go to switches
        currentSwitch.io.inputs(direction) <> io.inputs(direction)(channelIndex)
        crossbar.io.inputs(direction)(channelIndex).valid := false.B
        crossbar.io.inputs(direction)(channelIndex).bits := DontCare
      }.otherwise {
        // Static mode: inputs go to crossbar
        currentSwitch.io.inputs(direction).valid := false.B
        currentSwitch.io.inputs(direction).bits := DontCare
        io.inputs(direction)(channelIndex).token := false.B
        crossbar.io.inputs(direction)(channelIndex) := io.inputs(direction)(channelIndex).toValid()
      }

      // Create configurable buffer (FIFO for packet mode, delay line for static mode)
      val routingBuffer = Module(new FifoOrDelay(headerTemplate, params.networkMemoryDepth))
      routingBuffer.io.config.valid := io.configValid
      routingBuffer.io.config.bits.isFifo := io.configIsPacketMode
      routingBuffer.io.config.bits.delay := io.configDelay

      // Route buffer inputs based on operating mode
      when (isPacketMode) {
        // Packet mode: buffer inputs come from switch
        routingBuffer.io.input <> currentSwitch.io.toFifos(direction)
      }.otherwise {
        // Static mode: buffer inputs come from crossbar
        routingBuffer.io.input.valid := crossbar.io.outputs(direction)(channelIndex).valid
        routingBuffer.io.input.bits.bits := crossbar.io.outputs(direction)(channelIndex).bits
        routingBuffer.io.input.bits.header := false.B
        currentSwitch.io.toFifos(direction).ready := false.B
      }

      // Route buffer outputs and determine final output signals
      val finalOutput = Wire(new PacketInterface(params.width))
      when (isPacketMode) {
        // Packet mode: buffer outputs go to switch, final output from switch
        currentSwitch.io.fromFifos(direction) <> routingBuffer.io.output
        finalOutput <> currentSwitch.io.outputs(direction)
      }.otherwise {
        // Static mode: complex output routing with passthrough capability
        // Calculate opposite direction: N<->S (0<->1), W<->E (2<->3)
        val oppositeDirection = Wire(UInt(2.W))
        oppositeDirection := Mux(direction.U < 2.U, 
          direction.U ^ 1.U,  // N<->S: 0^1=1, 1^1=0
          direction.U ^ 1.U   // W<->E: 2^1=3, 3^1=2
        )
        
        val inputFromOpposite = io.inputs(oppositeDirection)(channelIndex)
        
        // Determine if this direction should drive its output
        val shouldDriveOutput = Wire(Bool())
        shouldDriveOutput := VecInit(Seq(
          io.control.nDrive(channelIndex),  // North (0)
          io.control.sDrive(channelIndex),  // South (1) 
          io.control.wDrive(channelIndex),  // West (2)
          io.control.eDrive(channelIndex)   // East (3)
        ))(direction)
        
        when (shouldDriveOutput && routingBuffer.io.output.valid) {
          // Drive output from our own routing buffer
          finalOutput.valid := true.B
          finalOutput.bits := routingBuffer.io.output.bits
          routingBuffer.io.output.ready := finalOutput.token
          inputFromOpposite.token := false.B
        }.otherwise {
          // Pass through from opposite direction (no local drive)
          finalOutput.valid := inputFromOpposite.valid
          finalOutput.bits := inputFromOpposite.bits
          routingBuffer.io.output.ready := false.B
          inputFromOpposite.token := finalOutput.token
        }
        
        // Disable unused switch interfaces in static mode
        currentSwitch.io.fromFifos(direction).valid := false.B
        currentSwitch.io.fromFifos(direction).bits := DontCare
        currentSwitch.io.outputs(direction).token := false.B
      }
      
      // Register outputs for timing (1-cycle delay)
      io.outputs(direction)(channelIndex).valid := RegNext(finalOutput.valid)
      io.outputs(direction)(channelIndex).bits := RegNext(finalOutput.bits)
      finalOutput.token := RegNext(io.outputs(direction)(channelIndex).token)
    }
  }
  
  // Update DDM arbitration state for next cycle
  ddmArbitrationActive := nextDdmArbitrationActive
  ddmArbitrationChannelPointer := nextDdmArbitrationChannelPointer
  ddmArbitrationRemaining := nextDdmArbitrationRemaining
  
}


object NetworkNodeGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    // Parse arguments
    if (args.length < 1) {
      println("Usage: <command> <outputDir> NetworkNode <paramsFileName>")
      null
    } else {
      val params = FMPVUParams.fromFile(args(0))
      new NetworkNode(params)
    }
  }
}
