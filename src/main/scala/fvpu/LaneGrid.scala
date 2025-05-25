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
  val nI = IO(Input(Vec(params.nColumns, Vec(params.nBuses, Valid(UInt(params.width.W))))))
  val nO = IO(Output(Vec(params.nColumns, Vec(params.nBuses, Valid(UInt(params.width.W))))))
  val sI = IO(Input(Vec(params.nColumns, Vec(params.nBuses, Valid(UInt(params.width.W))))))
  val sO = IO(Output(Vec(params.nColumns, Vec(params.nBuses, Valid(UInt(params.width.W))))))
  val eI = IO(Input(Vec(params.nRows, Vec(params.nBuses, Valid(UInt(params.width.W))))))
  val eO = IO(Output(Vec(params.nRows, Vec(params.nBuses, Valid(UInt(params.width.W))))))
  val wI = IO(Input(Vec(params.nRows, Vec(params.nBuses, Valid(UInt(params.width.W))))))
  val wO = IO(Output(Vec(params.nRows, Vec(params.nBuses, Valid(UInt(params.width.W))))))
  val instr = IO(Vec(params.nColumns, Input(new Instr(params))))

  // Instantiate 2D grid of Lanes
  val lanes = Array.tabulate(params.nRows, params.nColumns) { (row, col) =>
    Module(new Lane(params))
  }

  // Connect north/south data buses
  for (col <- 0 until params.nColumns) {
    for (row <- 0 until params.nRows) {
      if (row == 0) {
        // Top row connects to north inputs
        lanes(row)(col).nI := nI(col)
      } else {
        // Connect to lane above
        lanes(row)(col).nI := lanes(row-1)(col).nO
      }
      
      if (row == params.nRows - 1) {
        // Bottom row connects to north outputs
        nO(col) := lanes(row)(col).nO
      }
      
      if (row == params.nRows - 1) {
        // Bottom row connects to south inputs
        lanes(row)(col).sI := sI(col)
      } else {
        // Connect to lane below
        lanes(row)(col).sI := lanes(row+1)(col).sI
      }
      
      if (row == 0) {
        // Top row connects to south outputs
        sO(col) := lanes(row)(col).sO
      }
    }
  }

  // Connect east/west data buses
  for (row <- 0 until params.nRows) {
    for (col <- 0 until params.nColumns) {
      if (col == 0) {
        // Left column connects to west inputs
        lanes(row)(col).wI := wI(row)
      } else {
        // Connect to lane to the left
        lanes(row)(col).wI := lanes(row)(col-1).wO
      }
      
      if (col == 0) {
        // Left column connects to west outputs
        wO(row) := lanes(row)(col).wO
      }
      
      if (col == params.nColumns - 1) {
        // Right column connects to east inputs
        lanes(row)(col).eI := eI(row)
      } else {
        // Connect to lane to the right
        lanes(row)(col).eI := lanes(row)(col+1).eI
      }
      
      if (col == params.nColumns - 1) {
        // Right column connects to east outputs
        eO(row) := lanes(row)(col).eO
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
