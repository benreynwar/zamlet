package zamlet

import chisel3._
import _root_.circt.stage.ChiselStage
import java.io.File
import zamlet.utils._
import zamlet.amlet._
import zamlet.bamlet._
import zamlet.gamlet._

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
    case "RegisterFileAndRename" => RegisterFileAndRenameGenerator
    //case "RegisterFileAndFriends" => RegisterFileAndFriendsGenerator
    //case "ALU" => ALUGenerator
    //case "AluRS" => AluRSGenerator
    case "Amlet" => AmletGenerator
    case "ALURS" => ALURSGenerator
    case "ALULiteRS" => ALULiteRSGenerator
    case "ALU" => ALUGenerator
    case "ALULite" => ALULiteGenerator
    case "ALUPredicate" => ALUPredicateGenerator
    case "ALUPredicateRS" => ALUPredicateRSGenerator
    case "LoadStoreRS" => LoadStoreRSGenerator
    case "DataMemory" => DataMemoryGenerator
    case "SendPacketRS" => SendPacketRSGenerator
    case "ReceivePacketRS" => ReceivePacketRSGenerator
    case "SendPacketInterface" => SendPacketInterfaceGenerator
    case "ReceivePacketInterface" => ReceivePacketInterfaceGenerator
    case "NetworkNode" => NetworkNodeGenerator
    case "PacketInHandler" => PacketInHandlerGenerator
    case "PacketOutHandler" => PacketOutHandlerGenerator
    case "PacketSwitch" => PacketSwitchGenerator
    case "InstructionMemory" => InstructionMemoryGenerator
    //case "Lane" => LaneGenerator
    //case "LaneArray" => LaneArrayGenerator
    case "Control" => ControlGenerator
    case "Bamlet" => BamletGenerator
    case "DependencyTracker" => DependencyTrackerGenerator
    case "Rename" => RenameGenerator
    case "Fifo" => FifoGenerator
    case "SkidBuffer" => SkidBufferGenerator
    case "DecoupledBuffer" => DecoupledBufferGenerator
    case "DoubleBuffer" => DoubleBufferGenerator
    case "ShortQueue" => ShortQueueGenerator
    case "DroppingFifo" => DroppingFifoGenerator
    case _ => 
      println(s"Module name '${moduleName}' is unknown.")
      System.exit(1)
      null // This line is never reached due to System.exit above
  }

  // Generate the selected module
  generator.generate(outputDir, moduleArgs.toIndexedSeq)
}
