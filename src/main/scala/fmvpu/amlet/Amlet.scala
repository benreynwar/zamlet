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
  
  // Input stream of VLIW instructions from Bamlet
  val instruction = Flipped(Decoupled(new VLIWInstr.Base(params)))
  
  
  // Control outputs from ReceivePacketInterface
  val start = Valid(UInt(16.W)) // start signal for Bamlet control
  val writeIM = Valid(new IMWrite(params)) // instruction memory write from packets
  
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
  
  // Instantiate register file and rename unit
  val registerFileAndRename = Module(new RegisterFileAndRename(params))
  
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
  
  // Connect instruction input to RegisterFileAndRename
  registerFileAndRename.io.instr <> io.instruction
  
  // Connect RegisterFileAndRename outputs to reservation stations
  aluRS.io.input <> registerFileAndRename.io.aluInstr
  aluLiteRS.io.input <> registerFileAndRename.io.aluliteInstr
  loadStoreRS.io.input <> registerFileAndRename.io.ldstInstr
  sendPacketRS.io.input <> registerFileAndRename.io.sendPacketInstr
  receivePacketRS.io.input <> registerFileAndRename.io.recvPacketInstr
  
  // Connect execution units to reservation stations
  alu.io.instr := aluRS.io.output
  aluRS.io.output.ready := true.B
  
  aluLite.io.instr := aluLiteRS.io.output
  aluLiteRS.io.output.ready := true.B
  
  dataMem.io.instr := loadStoreRS.io.output
  loadStoreRS.io.output.ready := true.B
  
  sendPacketInterface.io.instr <> sendPacketRS.io.output
  receivePacketInterface.io.instr <> receivePacketRS.io.output
  
  // Collect all results for dependency resolution
  val resultBus = Wire(new ResultBus(params))
  resultBus.writes(0) := alu.io.result
  resultBus.writes(1) := aluLite.io.result
  resultBus.writes(2) := dataMem.io.result
  resultBus.writes(3) := receivePacketInterface.io.result
  
  // Connect mask results (placeholder for now)
  for (i <- 0 until params.nResultPorts) {
    resultBus.masks(i).valid := false.B
    resultBus.masks(i).value := false.B
    resultBus.masks(i).ident := 0.U
  }
  
  // Connect results to RegisterFileAndRename and reservation stations for dependency resolution
  registerFileAndRename.io.resultBus := resultBus.writes
  aluRS.io.resultBus := resultBus
  aluLiteRS.io.resultBus := resultBus
  loadStoreRS.io.resultBus := resultBus
  sendPacketRS.io.resultBus := resultBus
  receivePacketRS.io.resultBus := resultBus
  
  // Connect results to packet interfaces for dependency resolution
  sendPacketInterface.io.writeInputs := resultBus.writes
  
  
  // Connect control outputs from ReceivePacketInterface
  io.start := receivePacketInterface.io.start
  io.writeIM := receivePacketInterface.io.writeIM
  
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
