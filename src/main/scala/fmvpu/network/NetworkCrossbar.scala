package fmvpu.network

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import fmvpu.core.FMPVUParams
import fmvpu.ModuleGenerator

import scala.io.Source


/**
 * Network crossbar for routing data between directions and memory units
 * 
 * This module implements a configurable crossbar switch that routes data between:
 * - Four directional ports (North, South, East, West) with multiple channels each
 * - Data Register File (DRF) for register access
 * - Distributed Data Memory (DDM) for memory access
 * 
 * Routing is controlled by external control signals that specify source 
 * selection for each output.
 * 
 * Key features:
 * - Configurable number of channels per direction
 * - 1-cycle latency for DRF/DDM outputs
 * - Combinational routing for directional outputs
 * 
 * @param params FMPVU parameters containing width and channel configuration
 * @groupdesc Signals The actual hardware fields of the IO Bundle
 */
class NetworkCrossbar(params: FMPVUParams) extends Module {
  val io = IO(new Bundle {
    /** Input data from four directions: [0]=North, [1]=South, [2]=East, [3]=West
      * Each direction has multiple independent channels
      * @group Signals
      */
    val inputs = Vec(4, Vec(params.nChannels, Input(Valid(UInt(params.width.W)))))
    
    /** Output data to four directions: [0]=North, [1]=South, [2]=East, [3]=West
      * Each direction has multiple independent channels
      * @group Signals
      */
    val outputs = Vec(4, Vec(params.nChannels, Output(Valid(UInt(params.width.W)))))
    
    /** Data output to Data Register File (1-cycle latency)
      * @group Signals
      */
    val toDRF = Output(Valid(UInt(params.width.W)))
    
    /** Data input from Data Register File
      * @group Signals
      */
    val fromDRF = Input(Valid(UInt(params.width.W)))
    
    /** Data output to Distributed Data Memory (1-cycle latency)
      * @group Signals
      */
    val toDDM = Output(Valid(UInt(params.width.W)))
    
    /** Data input from Distributed Data Memory
      * @group Signals
      */
    val fromDDM = Input(Valid(UInt(params.width.W)))
    
    /** Control signals specifying crossbar routing configuration
      * @group Signals
      */
    val control = Input(new NetworkNodeControl(params))
  })

  // Direction constants for readability
  val NORTH = 0
  val SOUTH = 1
  val EAST = 2
  val WEST = 3

  // ============================================================================
  // Input Selection Stage
  // ============================================================================
  
  // Aggregated inputs from North/South directions (nChannels + 2 extra for DRF/DDM)
  val northSouthInputs = Wire(Vec(params.nChannels + 2, Valid(UInt(params.width.W))))
  
  // Aggregated inputs from West/East directions (nChannels + 2 extra for DRF/DDM)
  val westEastInputs = Wire(Vec(params.nChannels + 2, Valid(UInt(params.width.W))))
  
  // Combined input array for DRF/DDM selection (all NS + all WE inputs)
  val allCombinedInputs = Wire(Vec(2 * params.nChannels, Valid(UInt(params.width.W))))
  
  // Select between North/South inputs for each channel
  for (channelIndex <- 0 until params.nChannels) {
    northSouthInputs(channelIndex) := Mux(io.control.nsInputSel(channelIndex), 
                                          io.inputs(SOUTH)(channelIndex), 
                                          io.inputs(NORTH)(channelIndex))
    
    westEastInputs(channelIndex) := Mux(io.control.weInputSel(channelIndex), 
                                        io.inputs(WEST)(channelIndex), 
                                        io.inputs(EAST)(channelIndex))
    
    // Build combined array for DRF/DDM input selection
    allCombinedInputs(channelIndex) := northSouthInputs(channelIndex)
    allCombinedInputs(channelIndex + params.nChannels) := westEastInputs(channelIndex)
  }
  
  // Add DRF and DDM as additional input sources
  northSouthInputs(params.nChannels) := io.fromDRF
  northSouthInputs(params.nChannels + 1) := io.fromDDM
  westEastInputs(params.nChannels) := io.fromDRF
  westEastInputs(params.nChannels + 1) := io.fromDDM

  // ============================================================================
  // Output Selection Stage
  // ============================================================================
  
  // Selected data for North-South direction outputs
  val northSouthOutputs = Wire(Vec(params.nChannels, Valid(UInt(params.width.W))))
  // Selected data for West-East direction outputs  
  val westEastOutputs = Wire(Vec(params.nChannels, Valid(UInt(params.width.W))))
  
  for (channelIndex <- 0 until params.nChannels) {
    // North-South outputs select from West-East input sources
    northSouthOutputs(channelIndex) := westEastInputs(io.control.nsCrossbarSel(channelIndex))
    // West-East outputs select from North-South input sources
    westEastOutputs(channelIndex) := northSouthInputs(io.control.weCrossbarSel(channelIndex))
  }

  // Select inputs for DRF and DDM from all available sources
  val drfSelectedInput = Wire(Valid(UInt(params.width.W)))
  val ddmSelectedInput = Wire(Valid(UInt(params.width.W)))
  drfSelectedInput := allCombinedInputs(io.control.drfSel)
  ddmSelectedInput := allCombinedInputs(io.control.ddmSel)

  // ============================================================================
  // Output Assignments
  // ============================================================================
  
  // Connect directional outputs (combinational)
  for (channelIndex <- 0 until params.nChannels) {
    io.outputs(NORTH)(channelIndex) := northSouthOutputs(channelIndex)
    io.outputs(SOUTH)(channelIndex) := northSouthOutputs(channelIndex)
    io.outputs(EAST)(channelIndex) := westEastOutputs(channelIndex)
    io.outputs(WEST)(channelIndex) := westEastOutputs(channelIndex)
  }

  // Connect DRF and DDM outputs with 1-cycle delay
  io.toDRF := RegNext(drfSelectedInput)
  io.toDDM := RegNext(ddmSelectedInput)
}
