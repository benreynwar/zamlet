package fvpu

import chisel3._
import _root_.circt.stage.ChiselStage
import java.io.File

object Main extends App {

  // Parse command line arguments
  if (args.length < 3) {
    println("Usage: scala-cli Main.scala -- <outputDir> <moduleName> ...")
    System.exit(1)
  }

  // Debug: Print all arguments
  println("DEBUG: All arguments received:")
  args.zipWithIndex.foreach { case (arg, i) => println(s"args($i) = $arg") }

  val outputDir = args(1)
  val moduleName = args(2)
  
  // Create output directory if it doesn't exist
  val outDirFile = new File(outputDir)
  if (!outDirFile.exists()) {
    outDirFile.mkdirs()
  }
  
  // Generate Verilog based on the module name
  val moduleArgs = args.drop(3)
  
  val generator: ModuleGenerator = moduleName match {
    case "AdjustableDelay" => AdjustableDelayGenerator
    case "NetworkNode" => NetworkNodeGenerator
    case "RegisterFile" => RegisterFileGenerator
    case "DataMemory" => DataMemoryGenerator
    case "Lane" => LaneGenerator
    case "ddmAccess" => ddmAccessGenerator
    case _ => 
      println(s"Module name '${moduleName}' is unknown.")
      System.exit(1)
      null // This line is never reached due to System.exit above
  }

  // Generate the selected module
  generator.generate(outputDir, moduleArgs.toIndexedSeq)
}
