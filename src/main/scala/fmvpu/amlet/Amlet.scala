package fmvpu.amlet

import chisel3._
import chisel3.util._

/**
 * Amlet I/O interface
 */
class AmletIO(params: AmletParams) extends Bundle {
  val nChannels = params.nChannels
  
  // Current position for network routing
  val thisX = Input(UInt(params.xPosWidth.W))
  val thisY = Input(UInt(params.yPosWidth.W))
  
  // Input stream of resolved VLIW instructions from Bamlet
  val instruction = Flipped(Decoupled(new VLIWResolving(params)))
  
  // Write backs to Bamlet (without data, only addresses)
  val writeBacks = Output(new WriteBacks(params))
  
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
 * Amlet - Smallest processing unit with reservation stations and execution units
 */
class Amlet(params: AmletParams) extends Module {
  val io = IO(new AmletIO(params))
  
  // Instantiate reservation stations
  val aluRS = Module(new ALURS(params))
  val aluLiteRS = Module(new ALULiteRS(params))
  val loadStoreRS = Module(new LoadStoreRS(params))
  val sendPacketRS = Module(new SendPacketRS(params))
  val receivePacketRS = Module(new ReceivePacketRS(params))
  
  // Instantiate execution units
  val alu = Module(new ALU(params))
  val aluLite = Module(new ALULite(params))
  val dataMem = Module(new DataMemory(params))
  val sendPacketInterface = Module(new SendPacketInterface(params))
  val receivePacketInterface = Module(new ReceivePacketInterface(params))
  val networkNode = Module(new NetworkNode(params))
  
  // Connect instruction input to reservation stations
  val instrValid = io.instruction.valid
  val instr = io.instruction.bits
  
  // Connect instruction to each reservation station
  aluRS.io.input.valid := instrValid
  aluRS.io.input.bits := instr.alu
  
  aluLiteRS.io.input.valid := instrValid
  aluLiteRS.io.input.bits := instr.aluLite
  
  loadStoreRS.io.input.valid := instrValid
  loadStoreRS.io.input.bits := instr.loadStore
  
  sendPacketRS.io.input.valid := instrValid
  sendPacketRS.io.input.bits := instr.packetSend
  
  receivePacketRS.io.input.valid := instrValid
  receivePacketRS.io.input.bits := instr.packetReceive
  
  // Ready when all reservation stations are ready
  io.instruction.ready := aluRS.io.input.ready && 
                          aluLiteRS.io.input.ready && 
                          loadStoreRS.io.input.ready && 
                          sendPacketRS.io.input.ready && 
                          receivePacketRS.io.input.ready
  
  // Connect execution units to reservation stations
  alu.io.instr := aluRS.io.output
  aluRS.io.output.ready := true.B
  
  aluLite.io.instr := aluLiteRS.io.output
  aluLiteRS.io.output.ready := true.B
  
  dataMem.io.instr := loadStoreRS.io.output
  loadStoreRS.io.output.ready := true.B
  
  sendPacketInterface.io.instr <> sendPacketRS.io.output
  receivePacketInterface.io.instr <> receivePacketRS.io.output
  
  // Collect all write results for dependency resolution
  val writeResults = Wire(new WriteBacks(params))
  writeResults.writes(0) := alu.io.result
  writeResults.writes(1) := aluLite.io.result
  writeResults.writes(2) := dataMem.io.result
  writeResults.writes(3) := receivePacketInterface.io.writeReg
  
  // Connect mask results (placeholder for now)
  for (i <- 0 until params.nWriteBacks) {
    writeResults.masks(i).valid := false.B
    writeResults.masks(i).value := false.B
    writeResults.masks(i).ident := 0.U
  }
  
  // Connect write results to all reservation stations for dependency resolution
  aluRS.io.writeBacks := writeResults
  aluLiteRS.io.writeBacks := writeResults
  loadStoreRS.io.writeBacks := writeResults
  sendPacketRS.io.writeBacks := writeResults
  receivePacketRS.io.writeBacks := writeResults
  
  // Connect write results to packet interfaces for dependency resolution
  sendPacketInterface.io.writeInputs := writeResults.writes
  
  // Output write backs to Bamlet
  io.writeBacks := writeResults
  
  // Connect position to modules that need it
  networkNode.io.thisX := io.thisX
  networkNode.io.thisY := io.thisY
  receivePacketInterface.io.thisX := io.thisX
  receivePacketInterface.io.thisY := io.thisY
  
  // Connect external network interfaces
  networkNode.io.ni <> io.ni
  networkNode.io.si <> io.si
  networkNode.io.ei <> io.ei
  networkNode.io.wi <> io.wi
  networkNode.io.no <> io.no
  networkNode.io.so <> io.so
  networkNode.io.eo <> io.eo
  networkNode.io.wo <> io.wo
  
  // Connect packet interfaces to network node
  sendPacketInterface.io.toNetwork <> networkNode.io.hi
  networkNode.io.ho <> receivePacketInterface.io.fromNetwork
  networkNode.io.forward <> receivePacketInterface.io.forward
}

object AmletGenerator extends fmvpu.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length != 1) {
      println("Usage: AmletGenerator <config_file>")
      System.exit(1)
    }
    
    val configFile = args(0)
    val params = AmletParams.fromFile(configFile)
    
    new Amlet(params)
  }
}