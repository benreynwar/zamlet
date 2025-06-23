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
  // Grid coordinates: lanes exist from (1,1) to (nColumns-2, nRows-2)
  // Coordinates 0 and nColumns-1/nRows-1 are reserved for routing data off the grid
  val io = IO(new Bundle {
    /** North boundary input channels (one vector per column)
      * @group Boundary
      */
    val nI = Vec(params.nColumns-2, Vec(params.nChannels, new PacketInterface(params.width)))
    
    /** North boundary output channels (one vector per column)
      * @group Boundary
      */
    val nO = Vec(params.nColumns-2, Vec(params.nChannels, Flipped(new PacketInterface(params.width))))
    
    /** South boundary input channels (one vector per column)  
      * @group Boundary
      */
    val sI = Vec(params.nColumns-2, Vec(params.nChannels, new PacketInterface(params.width)))
    
    /** South boundary output channels (one vector per column)
      * @group Boundary
      */
    val sO = Vec(params.nColumns-2, Vec(params.nChannels, Flipped(new PacketInterface(params.width))))
    
    /** East boundary input channels (one vector per row)
      * @group Boundary
      */
    val eI = Vec(params.nRows-2, Vec(params.nChannels, new PacketInterface(params.width)))
    
    /** East boundary output channels (one vector per row)
      * @group Boundary
      */
    val eO = Vec(params.nRows-2, Vec(params.nChannels, Flipped(new PacketInterface(params.width))))
    
    /** West boundary input channels (one vector per row)
      * @group Boundary
      */
    val wI = Vec(params.nRows-2, Vec(params.nChannels, new PacketInterface(params.width)))
    
    /** West boundary output channels (one vector per row)
      * @group Boundary
      */
    val wO = Vec(params.nRows-2, Vec(params.nChannels, Flipped(new PacketInterface(params.width))))
    
    /** Instruction inputs for each column (flows north to south)
      * @group Control
      */
    val instr = Vec(params.nColumns-2, Input(new Instr(params)))
    
  })

  // Instantiate 2D grid of Lanes
  val lanes = Array.tabulate(params.nRows-2, params.nColumns-2) { (row, col) =>
    Module(new Lane(params))
  }

  // Connect north/south data buses
  for (col <- 1 until params.nColumns-1) {
    val arrayCol = col - 1  // Convert from coordinate to array index
    for (row <- 1 until params.nRows-1) {
      val arrayRow = row - 1  // Convert from coordinate to array index
      if (row == 1) {
        // Top row connects to north inputs
        lanes(arrayRow)(arrayCol).io.nI <> io.nI(arrayCol)
        lanes(arrayRow)(arrayCol).io.nO <> io.nO(arrayCol)
      } else {
        // Connect to lane above
        lanes(arrayRow)(arrayCol).io.nI <> lanes(arrayRow - 1)(arrayCol).io.sO
      }
      
      if (row == params.nRows - 2) {
        // Bottom row connects to south inputs
        lanes(arrayRow)(arrayCol).io.sI <> io.sI(arrayCol)
        lanes(arrayRow)(arrayCol).io.sO <> io.sO(arrayCol)
      } else {
        // Connect to lane below
        lanes(arrayRow)(arrayCol).io.sI <> lanes(arrayRow + 1)(arrayCol).io.nO
      }
    }
  }

  // Connect east/west data buses
  for (row <- 1 until params.nRows-1) {
    val arrayRow = row - 1  // Convert from coordinate to array index
    for (col <- 1 until params.nColumns-1) {
      val arrayCol = col - 1  // Convert from coordinate to array index
      if (col == 1) {
        // Left column connects to west inputs
        lanes(arrayRow)(arrayCol).io.wI <> io.wI(arrayRow)
        lanes(arrayRow)(arrayCol).io.wO <> io.wO(arrayRow)
      } else {
        // Connect to lane to the left
        lanes(arrayRow)(arrayCol).io.wI <> lanes(arrayRow)(arrayCol - 1).io.eO
      }
      
      if (col == params.nColumns - 2) {
        // Right column connects to east inputs
        lanes(arrayRow)(arrayCol).io.eI <> io.eI(arrayRow)
        lanes(arrayRow)(arrayCol).io.eO <> io.eO(arrayRow)
      } else {
        // Connect to lane to the right
        lanes(arrayRow)(arrayCol).io.eI <> lanes(arrayRow)(arrayCol + 1).io.wO
      }
    }
  }

  // Connect instruction flow north-to-south through columns
  for (col <- 1 until params.nColumns-1) {
    val arrayCol = col - 1  // Convert from coordinate to array index
    for (row <- 1 until params.nRows-1) {
      val arrayRow = row - 1  // Convert from coordinate to array index
      if (row == 1) {
        // Top row gets instructions from grid input
        lanes(arrayRow)(arrayCol).io.nInstr := io.instr(arrayCol)
      } else {
        // Connect to sInstr of lane above
        lanes(arrayRow)(arrayCol).io.nInstr := lanes(arrayRow - 1)(arrayCol).io.sInstr
      }
      // Set delay so all lanes execute on the same cycle
      // Lane at row R needs delay of (nRows-1-R) to sync with bottom row
      lanes(arrayRow)(arrayCol).io.instrDelay := (params.nRows - 1 - row).U
    }
  }


  // Set location for each lane
  for (col <- 1 until params.nColumns-1) {
    val arrayCol = col - 1  // Convert from coordinate to array index
    for (row <- 1 until params.nRows-1) {
      val arrayRow = row - 1  // Convert from coordinate to array index
      lanes(arrayRow)(arrayCol).io.thisLoc.x := col.U
      lanes(arrayRow)(arrayCol).io.thisLoc.y := row.U
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
