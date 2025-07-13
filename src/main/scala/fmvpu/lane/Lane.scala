package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Lane I/O interface
 */
class LaneIO(params: LaneParams) extends Bundle {
  val nChannels = params.nChannels
  
  // Current position for network routing
  val thisX = Input(UInt(params.xPosWidth.W))
  val thisY = Input(UInt(params.yPosWidth.W))
  
  // Network interfaces for 4 directions (North, South, East, West)
  val ni = Vec(nChannels, Flipped(Decoupled(new NetworkWord(params))))
  val si = Vec(nChannels, Flipped(Decoupled(new NetworkWord(params))))
  val ei = Vec(nChannels, Flipped(Decoupled(new NetworkWord(params))))
  val wi = Vec(nChannels, Flipped(Decoupled(new NetworkWord(params))))
  
  val no = Vec(nChannels, Decoupled(new NetworkWord(params)))
  val so = Vec(nChannels, Decoupled(new NetworkWord(params)))
  val eo = Vec(nChannels, Decoupled(new NetworkWord(params)))
  val wo = Vec(nChannels, Decoupled(new NetworkWord(params)))
}

/**
 * NewLane - Complete single-issue pipeline with Tomasulo execution
 */
class NewLane(params: LaneParams) extends Module {
  val io = IO(new LaneIO(params))
  
  // Instantiate all components
  val rff = Module(new RegisterFileAndFriends(params))
  val instrMem = Module(new InstructionMemory(params))
  val aluRS = Module(new AluRS(params))
  val ldstRS = Module(new LoadStoreRS(params))
  val packetRS = Module(new PacketRS(params))
  val alu = Module(new ALU(params))
  val dataMem = Module(new LaneDataMemory(params))
  val packetInterface = Module(new PacketInterface(params))
  val networkNode = Module(new LaneNetworkNode(params))
  
  // Connect RFF control inputs from PacketInterface  
  rff.io.startValid := packetInterface.io.start.valid
  rff.io.startPC := packetInterface.io.start.bits
  
  // Connect instruction memory
  instrMem.io.readAddr := rff.io.imReadAddress
  instrMem.io.readEnable := rff.io.imReadValid
  instrMem.io.writeIM <> packetInterface.io.writeIM
  
  // Connect instruction memory output to RFF
  rff.io.instrValid := instrMem.io.readValid
  rff.io.instruction := instrMem.io.readData
  
  // Connect RFF outputs to reservation stations
  aluRS.io.input <> rff.io.aluInstr
  ldstRS.io.input <> rff.io.ldstInstr
  packetRS.io.input <> rff.io.packetInstr
  
  // Connect execution units to reservation stations
  alu.io.instr := aluRS.io.output
  dataMem.io.instr := ldstRS.io.output
  packetInterface.io.instr := packetRS.io.output
  
  // Collect all write results for dependency resolution
  val writeResults = Wire(Vec(params.nWritePorts, new WriteResult(params)))
  writeResults(0) := alu.io.result
  writeResults(1) := dataMem.io.result
  writeResults(2) := packetInterface.io.writeReg.bits
  
  // Connect write results to all reservation stations for dependency resolution
  aluRS.io.writeInputs := writeResults
  ldstRS.io.writeInputs := writeResults
  packetRS.io.writeInputs := writeResults
  
  // Connect write results to RFF for register file updates
  rff.io.writeInputs := writeResults
  
  // Connect write results to PacketInterface for dependency resolution
  packetInterface.io.writeInputs := writeResults
  
  // Connect network node
  networkNode.io.thisX := io.thisX
  networkNode.io.thisY := io.thisY
  
  // Connect external network interfaces
  networkNode.io.ni <> io.ni
  networkNode.io.si <> io.si
  networkNode.io.ei <> io.ei
  networkNode.io.wi <> io.wi
  networkNode.io.no <> io.no
  networkNode.io.so <> io.so
  networkNode.io.eo <> io.eo
  networkNode.io.wo <> io.wo
  
  // Connect packet interface to network node
  packetInterface.io.toNetwork <> networkNode.io.hi
  packetInterface.io.toNetworkChannel <> networkNode.io.hiChannel
  networkNode.io.ho <> packetInterface.io.fromNetwork
  networkNode.io.forward <> packetInterface.io.forward
}

object NewLaneGenerator extends fmvpu.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length != 1) {
      println("Usage: NewLaneGenerator <config_file>")
      System.exit(1)
    }
    
    val configFile = args(0)
    val params = LaneParams.fromFile(configFile)
    
    new NewLane(params)
  }
}
