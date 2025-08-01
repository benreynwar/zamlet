package fmvpu.bamlet

import chisel3._
import chisel3.util._
import fmvpu.amlet.{Amlet, NetworkWord}

/**
 * Bamlet - A 2D grid of Amlets with shared control and instruction memory
 * Contains: InstructionMemory, Control unit, and a 2D grid of internally connected Amlets
 * Only external network connections are exposed in the interface
 */
class Bamlet(params: BamletParams) extends Module {
  val io = IO(new Bundle {
    // Position input for the entire Bamlet (base position)
    val thisX = Input(UInt(params.amlet.xPosWidth.W))
    val thisY = Input(UInt(params.amlet.yPosWidth.W))
    
    // External network interfaces (only edge connections)
    // North edge (top row)
    val ni = Vec(params.nAmletColumns, Vec(params.amlet.nChannels, Flipped(Decoupled(new NetworkWord(params.amlet)))))
    val no = Vec(params.nAmletColumns, Vec(params.amlet.nChannels, Decoupled(new NetworkWord(params.amlet))))
    
    // South edge (bottom row)  
    val si = Vec(params.nAmletColumns, Vec(params.amlet.nChannels, Flipped(Decoupled(new NetworkWord(params.amlet)))))
    val so = Vec(params.nAmletColumns, Vec(params.amlet.nChannels, Decoupled(new NetworkWord(params.amlet))))
    
    // East edge (rightmost column)
    val ei = Vec(params.nAmletRows, Vec(params.amlet.nChannels, Flipped(Decoupled(new NetworkWord(params.amlet)))))
    val eo = Vec(params.nAmletRows, Vec(params.amlet.nChannels, Decoupled(new NetworkWord(params.amlet))))
    
    // West edge (leftmost column)
    val wi = Vec(params.nAmletRows, Vec(params.amlet.nChannels, Flipped(Decoupled(new NetworkWord(params.amlet)))))
    val wo = Vec(params.nAmletRows, Vec(params.amlet.nChannels, Decoupled(new NetworkWord(params.amlet))))
  })

  // Instantiate components
  val instructionMemory = Module(new InstructionMemory(params))
  val control = Module(new Control(params))
  
  // Create 2D grid of amlets
  val amlets = Array.ofDim[Amlet](params.nAmletRows, params.nAmletColumns)
  for (row <- 0 until params.nAmletRows) {
    for (col <- 0 until params.nAmletColumns) {
      amlets(row)(col) = Module(new Amlet(params.amlet))
    }
  }

  // Connect instruction memory write interface - arbitrate between amlets
  val writeControlSignals = VecInit(amlets.flatten.toIndexedSeq.map(_.io.writeControl))

  // Connect control to instruction memory
  instructionMemory.io.imReq <> control.io.imReq
  control.io.imResp <> instructionMemory.io.imResp

  control.io.writeControl.valid := writeControlSignals.map(_.valid).reduce(_ || _)
  control.io.writeControl.bits := Mux1H(writeControlSignals.map(_.valid), writeControlSignals.map(_.bits))

  // Collect start signals from all amlets - use OR to start from any amlet
  val startSignals = VecInit(amlets.flatten.toIndexedSeq.map(_.io.start))
  control.io.start.valid := startSignals.map(_.valid).reduce(_ || _)
  control.io.start.bits := Mux1H(startSignals.map(_.valid), startSignals.map(_.bits))

  instructionMemory.io.writeControl.valid := writeControlSignals.map(_.valid).reduce(_ || _)
  instructionMemory.io.writeControl.bits := Mux1H(writeControlSignals.map(_.valid), writeControlSignals.map(_.bits))

  // Collect ready signals from all amlets
  val amletReadySignals = VecInit(amlets.flatten.toIndexedSeq.map(_.io.instruction.ready))
  
  // Control's ready is high when all amlets are ready
  control.io.instr.ready := amletReadySignals.asUInt.andR
  
  // Connect control and positions to all amlets
  for (row <- 0 until params.nAmletRows) {
    for (col <- 0 until params.nAmletColumns) {
      val amlet = amlets(row)(col)
      val linearIndex = row * params.nAmletColumns + col
      
      // Connect instruction bits from control to amlet
      amlet.io.instruction.bits := control.io.instr.bits
      
      // Valid to this amlet is high when control has valid instruction AND all OTHER amlets are ready
      // Create a mask excluding this amlet, then AND all other ready signals
      val otherReadySignals = amletReadySignals.zipWithIndex.filter(_._2 != linearIndex).map(_._1)
      val allOtherAmletsReady = otherReadySignals.reduce(_ && _)
      amlet.io.instruction.valid := control.io.instr.valid && allOtherAmletsReady
      
      // Connect loop iteration feedback from amlet to control
      control.io.loopIterations(linearIndex) <> amlet.io.loopIterations
      
      // Set position based on grid coordinates
      amlet.io.thisX := io.thisX + col.U
      amlet.io.thisY := io.thisY + row.U
    }
  }

  // Internal connections between adjacent amlets
  for (row <- 0 until params.nAmletRows) {
    for (col <- 0 until params.nAmletColumns) {
      val amlet = amlets(row)(col)
      
      // Connect to North neighbor (if exists)
      if (row > 0) {
        amlet.io.ni <> amlets(row - 1)(col).io.so
        amlets(row - 1)(col).io.si <> amlet.io.no
      }
      
      // Connect to South neighbor (if exists)  
      if (row < params.nAmletRows - 1) {
        amlet.io.si <> amlets(row + 1)(col).io.no
        amlets(row + 1)(col).io.ni <> amlet.io.so
      }
      
      // Connect to East neighbor (if exists)
      if (col < params.nAmletColumns - 1) {
        amlet.io.ei <> amlets(row)(col + 1).io.wo
        amlets(row)(col + 1).io.wi <> amlet.io.eo
      }
      
      // Connect to West neighbor (if exists)
      if (col > 0) {
        amlet.io.wi <> amlets(row)(col - 1).io.eo
        amlets(row)(col - 1).io.ei <> amlet.io.wo
      }
    }
  }

  // External connections (only for edge amlets)
  // North edge (top row)
  for (col <- 0 until params.nAmletColumns) {
    amlets(0)(col).io.ni <> io.ni(col)
    io.no(col) <> amlets(0)(col).io.no
  }
  
  // South edge (bottom row)
  for (col <- 0 until params.nAmletColumns) {
    amlets(params.nAmletRows - 1)(col).io.si <> io.si(col)
    io.so(col) <> amlets(params.nAmletRows - 1)(col).io.so
  }
  
  // East edge (rightmost column)
  for (row <- 0 until params.nAmletRows) {
    amlets(row)(params.nAmletColumns - 1).io.ei <> io.ei(row)
    io.eo(row) <> amlets(row)(params.nAmletColumns - 1).io.eo
  }
  
  // West edge (leftmost column)
  for (row <- 0 until params.nAmletRows) {
    amlets(row)(0).io.wi <> io.wi(row)
    io.wo(row) <> amlets(row)(0).io.wo
  }
}

/** Generator object for creating Bamlet modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of Bamlet modules with configurable parameters.
  */
object BamletGenerator extends fmvpu.ModuleGenerator {
  /** Create a Bamlet module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return Bamlet module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> Bamlet <bamletParamsFileName>")
      null
    } else {
      val params = BamletParams.fromFile(args(0))
      new Bamlet(params)
    }
  }
}
