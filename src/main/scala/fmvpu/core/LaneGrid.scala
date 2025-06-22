package fmvpu.core

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import fmvpu.utils._
import fmvpu.network._

import scala.io.Source

import fmvpu.ModuleGenerator


/** A 2D grid of processing lanes forming the complete FMVPU mesh architecture.
  *
  * The LaneGrid instantiates a configurable array of Lane modules and connects them
  * in a 2D mesh topology. Each lane can communicate with its immediate neighbors
  * (north, south, east, west) through packet interfaces. Instructions and configuration
  * flow from north to south through each column, with configurable delays to ensure
  * synchronized execution across all lanes.
  *
  * @param params System configuration parameters including grid dimensions
  * @groupdesc Boundary External mesh boundary interfaces
  * @groupdesc Control Global control and configuration signals
  */
class LaneGrid(params: FMVPUParams) extends Module {
  val io = IO(new Bundle {
    /** North boundary input channels (one vector per column)
      * @group Boundary
      */
    val nI = Vec(params.nColumns, Vec(params.nChannels, new PacketInterface(params.width)))
    
    /** North boundary output channels (one vector per column)
      * @group Boundary
      */
    val nO = Vec(params.nColumns, Vec(params.nChannels, Flipped(new PacketInterface(params.width))))
    
    /** South boundary input channels (one vector per column)  
      * @group Boundary
      */
    val sI = Vec(params.nColumns, Vec(params.nChannels, new PacketInterface(params.width)))
    
    /** South boundary output channels (one vector per column)
      * @group Boundary
      */
    val sO = Vec(params.nColumns, Vec(params.nChannels, Flipped(new PacketInterface(params.width))))
    
    /** East boundary input channels (one vector per row)
      * @group Boundary
      */
    val eI = Vec(params.nRows, Vec(params.nChannels, new PacketInterface(params.width)))
    
    /** East boundary output channels (one vector per row)
      * @group Boundary
      */
    val eO = Vec(params.nRows, Vec(params.nChannels, Flipped(new PacketInterface(params.width))))
    
    /** West boundary input channels (one vector per row)
      * @group Boundary
      */
    val wI = Vec(params.nRows, Vec(params.nChannels, new PacketInterface(params.width)))
    
    /** West boundary output channels (one vector per row)
      * @group Boundary
      */
    val wO = Vec(params.nRows, Vec(params.nChannels, Flipped(new PacketInterface(params.width))))
    
    /** Instruction inputs for each column (flows north to south)
      * @group Control
      */
    val instr = Vec(params.nColumns, Input(new Instr(params)))
    
  })

  // Instantiate 2D grid of Lanes
  val lanes = Array.tabulate(params.nRows, params.nColumns) { (row, col) =>
    Module(new Lane(params))
  }

  // Connect north/south data buses
  for (col <- 0 until params.nColumns) {
    for (row <- 0 until params.nRows) {
      if (row == 0) {
        // Top row connects to north inputs
        lanes(row)(col).io.nI <> io.nI(col)
        lanes(row)(col).io.nO <> io.nO(col)
      } else {
        // Connect to lane above
        lanes(row)(col).io.nI <> lanes(row - 1)(col).io.sO
      }
      
      if (row == params.nRows - 1) {
        // Bottom row connects to north outputs
        io.nO(col) <> lanes(row)(col).io.nO
      }
      
      if (row == params.nRows - 1) {
        // Bottom row connects to south inputs
        lanes(row)(col).io.sI <> io.sI(col)
        lanes(row)(col).io.sO <> io.sO(col)
      } else {
        // Connect to lane below
        lanes(row)(col).io.sI <> lanes(row + 1)(col).io.nO
      }
      
      if (row == 0) {
        // Top row connects to south outputs
        io.sO(col) <> lanes(row)(col).io.sO
      }
    }
  }

  // Connect east/west data buses
  for (row <- 0 until params.nRows) {
    for (col <- 0 until params.nColumns) {
      if (col == 0) {
        // Left column connects to west inputs
        lanes(row)(col).io.wI <> io.wI(row)
        lanes(row)(col).io.wO <> io.wO(row)
      } else {
        // Connect to lane to the left
        lanes(row)(col).io.wI <> lanes(row)(col - 1).io.eO
      }
      
      if (col == params.nColumns - 1) {
        // Right column connects to east inputs
        lanes(row)(col).io.eI <> io.eI(row)
        io.eO(row) <> lanes(row)(col).io.eO
      } else {
        // Connect to lane to the right
        lanes(row)(col).io.eI <> lanes(row)(col + 1).io.wO
      }
    }
  }

  // Connect instruction flow north-to-south through columns
  for (col <- 0 until params.nColumns) {
    for (row <- 0 until params.nRows) {
      if (row == 0) {
        // Top row gets instructions from grid input
        lanes(row)(col).io.nInstr := io.instr(col)
      } else {
        // Connect to sInstr of lane above
        lanes(row)(col).io.nInstr := lanes(row - 1)(col).io.sInstr
      }
      // Set delay so all lanes execute on the same cycle
      // Lane at row R needs delay of (nRows-1-R) to sync with bottom row
      lanes(row)(col).io.instrDelay := (params.nRows - 1 - row).U
    }
  }


  // Set location for each lane
  for (col <- 0 until params.nColumns) {
    for (row <- 0 until params.nRows) {
      lanes(row)(col).io.thisLoc.x := col.U
      lanes(row)(col).io.thisLoc.y := row.U
    }
  }

}


/** Generator object for creating LaneGrid modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of LaneGrid modules with parameters loaded from JSON files.
  */
object LaneGridGenerator extends ModuleGenerator {

  /** Create a LaneGrid module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return LaneGrid module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    // Parse arguments
    if (args.length < 1) {
      println("Usage: <command> <outputDir> LaneGrid <paramsFileName>")
      return null
    }
    val params = FMVPUParams.fromFile(args(0))
    new LaneGrid(params)
  }
}
