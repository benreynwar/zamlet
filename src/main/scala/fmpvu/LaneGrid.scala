package fmpvu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid

import scala.io.Source

import fmpvu.ModuleGenerator


class LaneGrid(params: FMPVUParams) extends Module {
  val io = IO(new Bundle {
    val nI = Vec(params.nColumns, Vec(params.nBuses, new Bus(params.width)))
    val nO = Vec(params.nColumns, Vec(params.nBuses, Flipped(new Bus(params.width))))
    val sI = Vec(params.nColumns, Vec(params.nBuses, new Bus(params.width)))
    val sO = Vec(params.nColumns, Vec(params.nBuses, Flipped(new Bus(params.width))))
    val eI = Vec(params.nRows, Vec(params.nBuses, new Bus(params.width)))
    val eO = Vec(params.nRows, Vec(params.nBuses, Flipped(new Bus(params.width))))
    val wI = Vec(params.nRows, Vec(params.nBuses, new Bus(params.width)))
    val wO = Vec(params.nRows, Vec(params.nBuses, Flipped(new Bus(params.width))))
    val instr = Vec(params.nColumns, Input(new Instr(params)))
    val config = Vec(params.nColumns, Input(new Config(params)))
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

  // Connect config flow north-to-south through columns
  for (col <- 0 until params.nColumns) {
    for (row <- 0 until params.nRows) {
      if (row == 0) {
        // Top row gets config from grid input
        lanes(row)(col).io.nConfig := io.config(col)
      } else {
        // Connect to sConfig of lane above
        lanes(row)(col).io.nConfig := lanes(row - 1)(col).io.sConfig
      }
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


object LaneGridGenerator extends ModuleGenerator {

  override def makeModule(args: Seq[String]): Module = {
    // Parse arguments
    if (args.length < 1) {
      println("Usage: <command> <outputDir> LaneGrid <paramsFileName>")
      return null
    }
    val params = FMPVUParams.fromFile(args(0))
    new LaneGrid(params)
  }
}
