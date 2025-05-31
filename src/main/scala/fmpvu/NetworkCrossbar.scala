package fmpvu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid

import scala.io.Source

import fmpvu.ModuleGenerator

/**
 * Network crossbar for routing data between directions and memory units
 * 
 * This module implements a configurable crossbar switch that routes data between:
 * - Four directional ports (North, South, East, West) with multiple buses each
 * - Data Register File (DRF) for register access
 * - Distributed Data Memory (DDM) for memory access
 * 
 * Routing is controlled by external control signals that specify source 
 * selection for each output.
 * 
 * Key features:
 * - Configurable number of buses per direction
 * - 1-cycle latency for DRF/DDM outputs
 * - Combinational routing for directional outputs
 * 
 * @param params FMPVU parameters containing width and bus configuration
 * @groupdesc Signals The actual hardware fields of the IO Bundle
 */
class NetworkCrossbar(params: FMPVUParams) extends Module {
  val io = IO(new Bundle {
    /** Input data from four directions: [0]=North, [1]=South, [2]=East, [3]=West
      * Each direction has multiple independent buses
      * @group Signals
      */
    val inputs = Vec(4, Vec(params.nBuses, Input(Valid(UInt(params.width.W)))))
    
    /** Output data to four directions: [0]=North, [1]=South, [2]=East, [3]=West
      * Each direction has multiple independent buses
      * @group Signals
      */
    val outputs = Vec(4, Vec(params.nBuses, Output(Valid(UInt(params.width.W)))))
    
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
  
  // Aggregated inputs from North/South directions (nBuses + 2 extra for DRF/DDM)
  val northSouthInputs = Wire(Vec(params.nBuses + 2, Valid(UInt(params.width.W))))
  
  // Aggregated inputs from West/East directions (nBuses + 2 extra for DRF/DDM)
  val westEastInputs = Wire(Vec(params.nBuses + 2, Valid(UInt(params.width.W))))
  
  // Combined input array for DRF/DDM selection (all NS + all WE inputs)
  val allCombinedInputs = Wire(Vec(2 * params.nBuses, Valid(UInt(params.width.W))))
  
  // Select between North/South inputs for each bus
  for (busIndex <- 0 until params.nBuses) {
    northSouthInputs(busIndex) := Mux(io.control.nsInputSel(busIndex), 
                                      io.inputs(SOUTH)(busIndex), 
                                      io.inputs(NORTH)(busIndex))
    
    westEastInputs(busIndex) := Mux(io.control.weInputSel(busIndex), 
                                    io.inputs(WEST)(busIndex), 
                                    io.inputs(EAST)(busIndex))
    
    // Build combined array for DRF/DDM input selection
    allCombinedInputs(busIndex) := northSouthInputs(busIndex)
    allCombinedInputs(busIndex + params.nBuses) := westEastInputs(busIndex)
  }
  
  // Add DRF and DDM as additional input sources
  northSouthInputs(params.nBuses) := io.fromDRF
  northSouthInputs(params.nBuses + 1) := io.fromDDM
  westEastInputs(params.nBuses) := io.fromDRF
  westEastInputs(params.nBuses + 1) := io.fromDDM

  // ============================================================================
  // Output Selection Stage
  // ============================================================================
  
  // Selected data for North-South direction outputs
  val northSouthOutputs = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))))
  // Selected data for West-East direction outputs  
  val westEastOutputs = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))))
  
  for (busIndex <- 0 until params.nBuses) {
    // North-South outputs select from West-East input sources
    northSouthOutputs(busIndex) := westEastInputs(io.control.nsCrossbarSel(busIndex))
    // West-East outputs select from North-South input sources
    westEastOutputs(busIndex) := northSouthInputs(io.control.weCrossbarSel(busIndex))
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
  for (busIndex <- 0 until params.nBuses) {
    io.outputs(NORTH)(busIndex) := northSouthOutputs(busIndex)
    io.outputs(SOUTH)(busIndex) := northSouthOutputs(busIndex)
    io.outputs(EAST)(busIndex) := westEastOutputs(busIndex)
    io.outputs(WEST)(busIndex) := westEastOutputs(busIndex)
  }

  // Connect DRF and DDM outputs with 1-cycle delay
  io.toDRF := RegNext(drfSelectedInput)
  io.toDDM := RegNext(ddmSelectedInput)
}
