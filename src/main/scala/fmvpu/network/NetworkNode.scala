package fmvpu.network

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import fmvpu.core.{FMVPUParams, NetworkInstr, SendReceiveInstr}
import fmvpu.utils._
import fmvpu.ModuleGenerator
import chisel3.util.DecoupledIO
import chisel3.util.MemoryWritePort
import chisel3.util.Cat

import scala.io.Source


/**
 * Error signals for the NetworkNode module
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class NetworkNodeErrors extends Bundle {
  /** Asserted when both network and send/receive instructions are valid simultaneously
    * @group Signals
    */
  val instrConflict = Bool()
}

// This is  configuration for the network that is expected to change
// relatively infrequently.  It will only be possible to change these
// after flushing the network pipeline.
class ChannelSlowControl(params: FMVPUParams) extends Bundle {
    val IsPacketMode = Bool()
    // How many cycles to delay for each of the 4 directions.
    val delays = Vec(4, UInt(log2Ceil(params.networkMemoryDepth + 1).W))
    // If this is false the delay is on the inputs.
    // If it is true the delay is on the outputs.
    val isOutputDelay = Bool()
    /** Enable driving outputs in each direction per channel
      * @group Signals
      */
    val nDrive = Vec(params.nChannels, Bool())
    val sDrive = Vec(params.nChannels, Bool())
    val wDrive = Vec(params.nChannels, Bool())
    val eDrive = Vec(params.nChannels, Bool())

    // How many cycles to delay the nsInputSel signal before applying it to the
    // mux
    val nsInputSelDelay = UInt(log2Ceil(params.maxNetworkControlDelay + 1).W)
    // How many cycles to delay the weInputSel signal before applying it to the
    // mux
    val weInputSelDelay = UInt(log2Ceil(params.maxNetworkControlDelay + 1).W)

    val nsCrossbarSelDelay = UInt(log2Ceil(params.maxNetworkControlDelay + 1).W)
    val weCrossbarSelDelay = UInt(log2Ceil(params.maxNetworkControlDelay + 1).W)
}

class GeneralSlowControl(params: FMVPUParams) extends Bundle {
  val drfSelDelay = UInt(log2Ceil(params.maxNetworkControlDelay + 1).W)
  val ddmSelDelay = UInt(log2Ceil(params.maxNetworkControlDelay + 1).W)
}

class NetworkSlowControl(params: FMVPUParams) extends Bundle {
  val channels = Vec(params.nChannels, new ChannelSlowControl(params))
  val general = new GeneralSlowControl(params)
}

class ChannelFastControl(params: FMVPUParams) extends Bundle {
  /** Input selection for north-south direction per channel
    * @group Signals
    */
  val nsInputSel = Bool()
  
  /** Input selection for west-east direction per channel
    * @group Signals
    */
  val weInputSel = Bool()
  
  /** Crossbar selection for north-south routing per channel
    * @group Signals
    */
  val nsCrossbarSel = UInt(log2Ceil(params.nChannels + 2).W)
  
  /** Crossbar selection for west-east routing per channel
    * @group Signals
    */
  val weCrossbarSel = UInt(log2Ceil(params.nChannels + 2).W)
}

class GeneralFastControl(params: FMVPUParams) extends Bundle {
  
  /** Data register file selection signal
    * @group Signals
    */
  val drfSel = UInt(log2Ceil(params.nChannels * 2).W)
  
  /** Data memory selection signal
    * @group Signals
    */
  val ddmSel = UInt(log2Ceil(params.nChannels * 2).W)
}


class NetworkFastControl(params: FMVPUParams) extends Bundle {

  val channels = Vec(params.nChannels, new ChannelFastControl(params))
  val general = new GeneralFastControl(params)
}

/**
 * The slow and fast control signals are stored in small memories in the NetworkNode.
 * The contents of these memories are written by the writeConfig signal.
 * If width is 32 we'd expect something like
 * 0 - slow config channel 0 slot 0
 * 1 - slow config channel 1 slot 0
 * 2 - slow config channel 2 slot 0
 * 3 - slow config channel 3 slot 0
 * 4 - slow config network   slot 0 (starts on the next power of two)
 * 8 - slot 1                       (starts on the next power of two)
 * 16 - slot 2
 * 
 * parameters to describe the address mapping are
 * wordsPerChannelSlowControl = ceil(channelSlowControl.Width/width)
 * wordsPerGeneralSlowControl = words for the fields in NetworkSlowControl excluding the channel ones.
 * wordsPerNetworkSlowControl = wordsPerChannelSlowControl * nChannels + wordsPerGeneralSlowControl
 * networkSlowControlStep = round wordsPerNetworkSlowControl up to a power of two.
 * nNetworkSlowControlSlots
 * nNetworkFastControlSlots
 * 
 * then we do the same for the FastControl.
 *
 * When we receive an address we need to work out whether it is modifying 
 * - If it is less than nNetworkSlotControlSlots * networkSlotControlSteps we're modifying the slow control.
 *   The we work out which of the slots we're modifying and so on.
 */ 

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
 * @param params FMVPU parameters defining channel counts, widths, and memory sizes
 * @groupdesc Signals The actual hardware fields of the IO Bundle
 */
class NetworkNode(params: FMVPUParams) extends Module {
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
    val fromDDM = Flipped(DecoupledIO(new HeaderTag(UInt(params.width.W))))
    val fromDDMChannel = Input(UInt(log2Ceil(params.nChannels).W))
    
    /** Updates the control signals.
      * @group Signals
      */
    val writeControl = Input(new MemoryWritePort(UInt(params.width.W), params.networkControlAddrWidth, false))
    
    /** Network instruction for slot configuration
      * @group Signals
      */
    val networkInstr = Input(Valid(new NetworkInstr(params)))
    
    /** Send/receive instruction for network slot selection
      * @group Signals
      */
    val sendReceiveInstr = Input(Valid(new SendReceiveInstr(params)))
    
    /** This node's location in the network grid
      * @group Signals
      */
    val thisLoc = Input(new Location(params))
    
    /** Error status signals indicating various fault conditions
      * @group Signals
      */
    val errors = Output(new NetworkNodeErrors)
  })

  // Deals with the Control memories.
  //
  val slowControlMemory = Reg(Vec(params.nSlowNetworkControlSlots, new NetworkSlowControl(params)))
  val fastControlMemory = Reg(Vec(params.nFastNetworkControlSlots, new NetworkFastControl(params)))
  
  // On reset, ensure all channels are in packet mode
  when (reset.asBool) {
    for (slotIdx <- 0 until params.nSlowNetworkControlSlots) {
      for (channelIdx <- 0 until params.nChannels) {
        slowControlMemory(slotIdx).channels(channelIdx).IsPacketMode := true.B
      }
    }
  }
  
  val currentSlowControlSlot = RegInit(0.U(log2Ceil(params.nSlowNetworkControlSlots).W))
  
  // Detect when slow control slot is being set
  val slowControlBeingModified = Wire(Bool())
  slowControlBeingModified := io.networkInstr.valid && io.networkInstr.bits.instrType === 1.U

  // Handle set slow control slot instruction
  when (slowControlBeingModified) {
    currentSlowControlSlot := io.networkInstr.bits.slot
  }

  // Helper function to update a word within a bundle
  def updateBundleWord[T <: Data](bundle: T, wordAddress: UInt, newData: UInt): T = {
    val bundleAsUInt = bundle.asUInt
    val wordsInBundle = (bundleAsUInt.getWidth + params.width - 1) / params.width
    val paddedWidth = wordsInBundle * params.width
    val paddedBundle = Cat(0.U((paddedWidth - bundleAsUInt.getWidth).W), bundleAsUInt)
    val words = VecInit((0 until wordsInBundle).map(i => 
      paddedBundle((i + 1) * params.width - 1, i * params.width)
    ))
    words(wordAddress) := newData
    Cat(words.reverse)(bundleAsUInt.getWidth - 1, 0).asTypeOf(bundle)
  }

  // Control memory writes are already decoded by ddmAccess module
  when (io.writeControl.enable) {
    when (io.writeControl.address < (params.nSlowNetworkControlSlots * params.wordsPerSlowNetworkControlSlot).U) {
      val slowSlot = io.writeControl.address / params.wordsPerSlowNetworkControlSlot.U
      dontTouch(slowSlot)
      val addressInSlot = io.writeControl.address - slowSlot * params.wordsPerSlowNetworkControlSlot.U
      dontTouch(addressInSlot)
      // First we have the general control
      val isGeneral = addressInSlot < params.wordsPerGeneralSlowNetworkControl.U
      dontTouch(isGeneral)
      when (isGeneral) {
        slowControlMemory(slowSlot).general := updateBundleWord(slowControlMemory(slowSlot).general, addressInSlot, io.writeControl.data)
      }.otherwise {
        val channelIndex = (addressInSlot - params.wordsPerGeneralSlowNetworkControl.U) / params.wordsPerChannelSlowNetworkControl.U
        dontTouch(channelIndex)
        val addressInChannel = addressInSlot - params.wordsPerGeneralSlowNetworkControl.U - channelIndex * params.wordsPerChannelSlowNetworkControl.U
        dontTouch(addressInChannel)
        slowControlMemory(slowSlot).channels(channelIndex) := updateBundleWord(slowControlMemory(slowSlot).channels(channelIndex), addressInChannel, io.writeControl.data)
      }
    }.otherwise {
      val fastSlot = (io.writeControl.address - params.fastNetworkControlOffset.U) / params.wordsPerFastNetworkControlSlot.U
      val addressInSlot = (io.writeControl.address - params.fastNetworkControlOffset.U) - fastSlot * params.wordsPerFastNetworkControlSlot.U
      val isGeneral = addressInSlot < params.wordsPerGeneralFastNetworkControl.U
      when (isGeneral) {
        fastControlMemory(fastSlot).general := updateBundleWord(fastControlMemory(fastSlot).general, addressInSlot, io.writeControl.data)
      }.otherwise {
        val channelIndex = (addressInSlot - params.wordsPerGeneralFastNetworkControl.U) / params.wordsPerChannelFastNetworkControl.U
        val addressInChannel = addressInSlot - params.wordsPerGeneralFastNetworkControl.U - channelIndex * params.wordsPerChannelFastNetworkControl.U
        fastControlMemory(fastSlot).channels(channelIndex) := updateBundleWord(fastControlMemory(fastSlot).channels(channelIndex), addressInChannel, io.writeControl.data)
      }
    }
  }

  // Template for HeaderTag type inference
  val headerTemplate = new HeaderTag(UInt(params.width.W))

  /** Current operating mode: true for packet mode, false for static mode */
  val currentSlowControl = slowControlMemory(currentSlowControlSlot)

  // Network components
  val crossbar = Module(new NetworkCrossbar(params))
  val switches = Seq.fill(params.nChannels)(Module(new NetworkSwitch(params)))

  // DDM arbitration signals
  val ddmArbitrationActive = RegInit(false.B)
  val ddmArbitrationChannelPointer = RegInit(0.U(log2Ceil(params.nChannels).W))
  val ddmArbitrationRemaining = RegInit(0.U(log2Ceil(params.maxPacketLength+1).W))
  
  // Aggregated switch outputs for DDM access
  val switchesToDDM = Wire(DecoupledIO(headerTemplate))

  io.toDDM.valid := switchesToDDM.valid
  io.toDDM.bits := switchesToDDM.bits
  switchesToDDM.ready := true.B

  // DDM arbitration next-state logic
  val nextDdmArbitrationActive = Wire(Bool())
  val nextDdmArbitrationChannelPointer = Wire(UInt(log2Ceil(params.nChannels).W))
  val nextDdmArbitrationRemaining = Wire(UInt(log2Ceil(params.maxPacketLength+1).W))
  
  // Default to current state
  nextDdmArbitrationActive := ddmArbitrationActive
  nextDdmArbitrationChannelPointer := ddmArbitrationChannelPointer
  nextDdmArbitrationRemaining := ddmArbitrationRemaining

  // Error detection and default error output
  io.errors.instrConflict := false.B
  
  // Connect crossbar to external interfaces  
  // Error detection: both instructions should not be valid simultaneously
  when (io.networkInstr.valid && io.sendReceiveInstr.valid) {
    io.errors.instrConflict := true.B
  }
  
  // Select fast control slot: always use network instruction mode (send/receive use packets, not control memory)
  val fastControlSlotSel = io.networkInstr.bits.mode
  dontTouch(fastControlSlotSel)
  val currentFastControl = fastControlMemory(fastControlSlotSel)
  
  // Create delayed control signals using AdjustableDelay instances
  val delayedFastControl = Wire(new NetworkFastControl(params))
  
  // Delay general control signals
  val drfSelDelay = Module(new AdjustableDelay(params.maxNetworkControlDelay, log2Ceil(params.nChannels * 2)))
  drfSelDelay.io.delay := currentSlowControl.general.drfSelDelay
  drfSelDelay.io.input.valid := true.B
  drfSelDelay.io.input.bits := currentFastControl.general.drfSel
  delayedFastControl.general.drfSel := drfSelDelay.io.output.bits
  
  val ddmSelDelay = Module(new AdjustableDelay(params.maxNetworkControlDelay, log2Ceil(params.nChannels * 2)))
  ddmSelDelay.io.delay := currentSlowControl.general.ddmSelDelay
  ddmSelDelay.io.input.valid := true.B
  ddmSelDelay.io.input.bits := currentFastControl.general.ddmSel
  delayedFastControl.general.ddmSel := ddmSelDelay.io.output.bits
  
  // Delay channel control signals
  for (i <- 0 until params.nChannels) {
    val nsInputSelDelay = Module(new AdjustableDelay(params.maxNetworkControlDelay, 1))
    nsInputSelDelay.io.delay := currentSlowControl.channels(i).nsInputSelDelay
    nsInputSelDelay.io.input.valid := true.B
    nsInputSelDelay.io.input.bits := currentFastControl.channels(i).nsInputSel
    delayedFastControl.channels(i).nsInputSel := nsInputSelDelay.io.output.bits
    
    val weInputSelDelay = Module(new AdjustableDelay(params.maxNetworkControlDelay, 1))
    weInputSelDelay.io.delay := currentSlowControl.channels(i).weInputSelDelay
    weInputSelDelay.io.input.valid := true.B
    weInputSelDelay.io.input.bits := currentFastControl.channels(i).weInputSel
    delayedFastControl.channels(i).weInputSel := weInputSelDelay.io.output.bits
    
    val nsCrossbarSelDelay = Module(new AdjustableDelay(params.maxNetworkControlDelay, log2Ceil(params.nChannels + 2)))
    nsCrossbarSelDelay.io.delay := currentSlowControl.channels(i).nsCrossbarSelDelay
    nsCrossbarSelDelay.io.input.valid := true.B
    nsCrossbarSelDelay.io.input.bits := currentFastControl.channels(i).nsCrossbarSel
    delayedFastControl.channels(i).nsCrossbarSel := nsCrossbarSelDelay.io.output.bits
    
    val weCrossbarSelDelay = Module(new AdjustableDelay(params.maxNetworkControlDelay, log2Ceil(params.nChannels + 2)))
    weCrossbarSelDelay.io.delay := currentSlowControl.channels(i).weCrossbarSelDelay
    weCrossbarSelDelay.io.input.valid := true.B
    weCrossbarSelDelay.io.input.bits := currentFastControl.channels(i).weCrossbarSel
    delayedFastControl.channels(i).weCrossbarSel := weCrossbarSelDelay.io.output.bits
  }
  
  crossbar.io.fromDRF := io.fromDRF
  io.toDRF := crossbar.io.toDRF
  crossbar.io.control := delayedFastControl
  
  // Route DDM data to the appropriate switch based on channel
  // Default all switches to not ready and invalid
  for (channelIndex <- 0 until params.nChannels) {
    switches(channelIndex).io.fromDDM.valid := false.B
    switches(channelIndex).io.fromDDM.bits := DontCare
  }
  
  // Default ready signal
  io.fromDDM.ready := false.B
  
  // Connect selected switch
  for (channelIndex <- 0 until params.nChannels) {
    when (io.fromDDMChannel === channelIndex.U) {
      switches(channelIndex).io.fromDDM <> io.fromDDM
    }
  }

  // Collect all switch DDM outputs
  val allSwitchToDDM = Wire(Vec(params.nChannels, DecoupledIO(headerTemplate)))
  for (i <- 0 until params.nChannels) {
    allSwitchToDDM(i) <> switches(i).io.toDDM
  }
  
  // Connect selected switch to aggregated DDM output
  switchesToDDM.valid := allSwitchToDDM(ddmArbitrationChannelPointer).valid && 
    currentSlowControl.channels(ddmArbitrationChannelPointer).IsPacketMode
  switchesToDDM.bits := allSwitchToDDM(ddmArbitrationChannelPointer).bits

  // Configure each channel and its associated switch
  for (channelIndex <- 0 until params.nChannels) {
    val currentSwitch = switches(channelIndex)
    
    // Connect switch location interface
    currentSwitch.io.thisLoc := io.thisLoc
    
    
    // DDM arbitration: manage which switch can access DDM
    val isSelectedForDDM = currentSlowControl.channels(channelIndex).IsPacketMode && ddmArbitrationChannelPointer === channelIndex.U
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
      val channelIsPacketMode = currentSlowControl.channels(channelIndex).IsPacketMode
      when (channelIsPacketMode) {
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
      routingBuffer.io.config.valid := slowControlBeingModified
      routingBuffer.io.config.bits.isFifo := slowControlMemory(io.networkInstr.bits.slot).channels(channelIndex).IsPacketMode
      routingBuffer.io.config.bits.delay := slowControlMemory(io.networkInstr.bits.slot).channels(channelIndex).delays(direction)

      // Route buffer inputs based on operating mode
      when (channelIsPacketMode) {
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
      when (channelIsPacketMode) {
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
          currentSlowControl.channels(channelIndex).nDrive(channelIndex),  // North (0)
          currentSlowControl.channels(channelIndex).sDrive(channelIndex),  // South (1) 
          currentSlowControl.channels(channelIndex).wDrive(channelIndex),  // West (2)
          currentSlowControl.channels(channelIndex).eDrive(channelIndex)   // East (3)
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
      val params = FMVPUParams.fromFile(args(0))
      new NetworkNode(params)
    }
  }
}
