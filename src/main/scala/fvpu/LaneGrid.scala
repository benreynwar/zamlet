package fvpu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid

import scala.io.Source

import fvpu.ModuleGenerator


class LaneGrid(params: FVPUParams) extends Module {
  val nI = IO(Vec(params.nColumns, Vec(params.nBuses, new Bus(params.width))))
  val nO = IO(Vec(params.nColumns, Vec(params.nBuses, Flipped(new Bus(params.width)))))
  val sI = IO(Vec(params.nColumns, Vec(params.nBuses, new Bus(params.width))))
  val sO = IO(Vec(params.nColumns, Vec(params.nBuses, Flipped(new Bus(params.width)))))
  val eI = IO(Vec(params.nRows, Vec(params.nBuses, new Bus(params.width))))
  val eO = IO(Vec(params.nRows, Vec(params.nBuses, Flipped(new Bus(params.width)))))
  val wI = IO(Vec(params.nRows, Vec(params.nBuses, new Bus(params.width))))
  val wO = IO(Vec(params.nRows, Vec(params.nBuses, Flipped(new Bus(params.width)))))
  val instr = IO(Vec(params.nColumns, Input(new Instr(params))))
  val config = IO(Vec(params.nColumns, Input(new Config(params))))

  // Instantiate 2D grid of Lanes
  val lanes = Array.tabulate(params.nRows, params.nColumns) { (row, col) =>
    Module(new Lane(params))
  }

  // Connect north/south data buses
  for (col <- 0 until params.nColumns) {
    for (row <- 0 until params.nRows) {
      if (row == 0) {
        // Top row connects to north inputs
        lanes(row)(col).nI <> nI(col)
        lanes(row)(col).nO <> nO(col)
      } else {
        // Connect to lane above
        lanes(row)(col).nI <> lanes(row-1)(col).sO
      }
      
      if (row == params.nRows - 1) {
        // Bottom row connects to north outputs
        nO(col) <> lanes(row)(col).nO
      }
      
      if (row == params.nRows - 1) {
        // Bottom row connects to south inputs
        lanes(row)(col).sI <> sI(col)
        lanes(row)(col).sO <> sO(col)
      } else {
        // Connect to lane below
        lanes(row)(col).sI <> lanes(row+1)(col).nO
      }
      
      if (row == 0) {
        // Top row connects to south outputs
        sO(col) <> lanes(row)(col).sO
      }
    }
  }

  // Connect east/west data buses
  for (row <- 0 until params.nRows) {
    for (col <- 0 until params.nColumns) {
      if (col == 0) {
        // Left column connects to west inputs
        lanes(row)(col).wI <> wI(row)
        lanes(row)(col).wO <> wO(row)
      } else {
        // Connect to lane to the left
        lanes(row)(col).wI <> lanes(row)(col-1).eO
      }
      
      if (col == params.nColumns - 1) {
        // Right column connects to east inputs
        lanes(row)(col).eI <> eI(row)
        eO(row) <> lanes(row)(col).eO
      } else {
        // Connect to lane to the right
        lanes(row)(col).eI <> lanes(row)(col+1).wO
      }
    }
  }

  // Connect instruction flow north-to-south through columns
  for (col <- 0 until params.nColumns) {
    for (row <- 0 until params.nRows) {
      if (row == 0) {
        // Top row gets instructions from grid input
        lanes(row)(col).nInstr := instr(col)
      } else {
        // Connect to sInstr of lane above
        lanes(row)(col).nInstr := lanes(row-1)(col).sInstr
      }
      // Set delay so all lanes execute on the same cycle
      // Lane at row R needs delay of (nRows-1-R) to sync with bottom row
      lanes(row)(col).instrDelay := (params.nRows - 1 - row).U
    }
  }

  // Connect config flow north-to-south through columns
  for (col <- 0 until params.nColumns) {
    for (row <- 0 until params.nRows) {
      if (row == 0) {
        // Top row gets config from grid input
        lanes(row)(col).nConfig := config(col)
      } else {
        // Connect to sConfig of lane above
        lanes(row)(col).nConfig := lanes(row-1)(col).sConfig
      }
    }
  }

  // Set location for each lane
  for (col <- 0 until params.nColumns) {
    for (row <- 0 until params.nRows) {
      lanes(row)(col).thisLoc.x := col.U
      lanes(row)(col).thisLoc.y := row.U
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
    val params = FVPUParams.fromFile(args(0));
    return new LaneGrid(params);
  }

}
