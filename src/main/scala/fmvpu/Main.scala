package fmvpu

import chisel3._
import _root_.circt.stage.ChiselStage
import java.io.File
import fmvpu.core._
import fmvpu.memory._
import fmvpu.network._
import fmvpu.utils._
import fmvpu.alu._

/** Main entry point for generating Verilog from FMVPU modules.
  *
  * This object provides a command-line interface for generating Verilog files
  * from any FMVPU module. It supports all major modules including Lane, LaneGrid,
  * NetworkNode, RegisterFile, DataMemory, and utility modules.
  *
  * Usage: scala-cli Main.scala -- <outputDir> <moduleName> [moduleArgs...]
  */
object Main extends App {

  // Parse command line arguments
  if (args.length < 2) {
    println("Usage: <outputDir> <moduleName> [moduleArgs...]")
    System.exit(1)
  }

  // Debug: Print all arguments
  println("DEBUG: All arguments received:")
  args.zipWithIndex.foreach { case (arg, i) => println(s"args($i) = $arg") }

  val outputDir = args(0)
  val moduleName = args(1)
  
  // Create output directory if it doesn't exist
  val outDirFile = new File(outputDir)
  if (!outDirFile.exists()) {
    outDirFile.mkdirs()
  }
  
  // Generate Verilog based on the module name
  val moduleArgs = args.drop(2)
  
  val generator: ModuleGenerator = moduleName match {
    case "AdjustableDelay" => AdjustableDelayGenerator
    case "NetworkNode" => NetworkNodeGenerator
    case "RegisterFile" => RegisterFileGenerator
    case "DataMemory" => DataMemoryGenerator
    case "ddmAccess" => ddmAccessGenerator
    case "Lane" => LaneGenerator
    case "LaneGrid" => LaneGridGenerator
    case "LaneALU" => LaneALUGenerator
    case _ => 
      println(s"Module name '${moduleName}' is unknown.")
      System.exit(1)
      null // This line is never reached due to System.exit above
  }

  // Generate the selected module
  generator.generate(outputDir, moduleArgs.toIndexedSeq)
}
