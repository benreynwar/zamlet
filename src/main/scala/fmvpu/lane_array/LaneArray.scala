package fmvpu.lane_array

import chisel3._
import chisel3.util._
import fmvpu.lane.{Lane, LaneIO, NetworkWord}

/**
 * LaneArray I/O interface
 */
class LaneArrayIO(params: LaneArrayParams) extends Bundle {
  val nChannels = params.lane.nChannels
  
  // External network interfaces for the array edges
  // North edge
  val ni = Vec(params.nColumns, Vec(nChannels, Flipped(Decoupled(new NetworkWord(params.lane)))))
  val no = Vec(params.nColumns, Vec(nChannels, Decoupled(new NetworkWord(params.lane))))
  
  // South edge  
  val si = Vec(params.nColumns, Vec(nChannels, Flipped(Decoupled(new NetworkWord(params.lane)))))
  val so = Vec(params.nColumns, Vec(nChannels, Decoupled(new NetworkWord(params.lane))))
  
  // East edge
  val ei = Vec(params.nRows, Vec(nChannels, Flipped(Decoupled(new NetworkWord(params.lane)))))
  val eo = Vec(params.nRows, Vec(nChannels, Decoupled(new NetworkWord(params.lane))))
  
  // West edge
  val wi = Vec(params.nRows, Vec(nChannels, Flipped(Decoupled(new NetworkWord(params.lane)))))
  val wo = Vec(params.nRows, Vec(nChannels, Decoupled(new NetworkWord(params.lane))))
}

/**
 * LaneArray - A grid of interconnected lanes
 */
class LaneArray(params: LaneArrayParams) extends Module {
  val io = IO(new LaneArrayIO(params))
  
  // Create 2D array of lanes
  val lanes = Array.tabulate(params.nRows, params.nColumns) { case (row, col) =>
    val lane = Module(new Lane(params.lane))
    
    // Set position for each lane
    lane.io.thisX := (col+1).U(params.lane.xPosWidth.W)
    lane.io.thisY := (row+1).U(params.lane.yPosWidth.W)
    
    lane
  }
  
  // Connect internal lanes to each other
  for (row <- 0 until params.nRows) {
    for (col <- 0 until params.nColumns) {
      val currentLane = lanes(row)(col)
      
      // Connect North-South links
      if (row > 0) {
        // Connect to lane above (North)
        currentLane.io.ni <> lanes(row - 1)(col).io.so
        currentLane.io.no <> lanes(row - 1)(col).io.si
      } else {
        // Connect to external North interface
        currentLane.io.ni <> io.ni(col)
        currentLane.io.no <> io.no(col)
      }
      
      if (row < params.nRows - 1) {
        // Connect to lane below (South)
        currentLane.io.si <> lanes(row + 1)(col).io.no
        currentLane.io.so <> lanes(row + 1)(col).io.ni
      } else {
        // Connect to external South interface
        currentLane.io.si <> io.si(col)
        currentLane.io.so <> io.so(col)
      }
      
      // Connect East-West links
      if (col > 0) {
        // Connect to lane to the left (West)
        currentLane.io.wi <> lanes(row)(col - 1).io.eo
        currentLane.io.wo <> lanes(row)(col - 1).io.ei
      } else {
        // Connect to external West interface
        currentLane.io.wi <> io.wi(row)
        currentLane.io.wo <> io.wo(row)
      }
      
      if (col < params.nColumns - 1) {
        // Connect to lane to the right (East)
        currentLane.io.ei <> lanes(row)(col + 1).io.wo
        currentLane.io.eo <> lanes(row)(col + 1).io.wi
      } else {
        // Connect to external East interface
        currentLane.io.ei <> io.ei(row)
        currentLane.io.eo <> io.eo(row)
      }
    }
  }
}

object LaneArrayGenerator extends fmvpu.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length != 1) {
      println("Usage: LaneArrayGenerator <config_file>")
      System.exit(1)
    }
    
    val configFile = args(0)
    val params = LaneArrayParams.fromFile(configFile)
    
    new LaneArray(params)
  }
}
