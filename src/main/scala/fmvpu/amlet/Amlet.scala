package fmvpu.amlet

import chisel3._
import chisel3.util._
import fmvpu.utils.{DecoupledBuffer, SkidBuffer}

/**
 * Amlet I/O interface
 */
class AmletIO(params: AmletParams) extends Bundle {
  val nChannels = params.nChannels
  
  // Current position for network routing
  val thisX = Input(UInt(params.xPosWidth.W))
  val thisY = Input(UInt(params.yPosWidth.W))
  
  // Input stream of VLIW instructions from Bamlet
  val instruction = Flipped(Decoupled(new VLIWInstr.Expanded(params)))
  
  
  // Control outputs from ReceivePacketInterface
  val start = Valid(UInt(16.W)) // start signal for Bamlet control
  val writeControl = Valid(new ControlWrite(params)) // instruction memory write from packets
  
  // Loop iteration reporting to Bamlet control
  val loopIterations = Valid(UInt(params.aWidth.W))
  
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

class AmletErrors extends Bundle {
  val receivePacketInterface = new ReceivePacketInterfaceErrors()
}

/**
 * Amlet - Smallest processing unit with reservation stations and execution units
 */
class Amlet(params: AmletParams) extends Module {
  val io = IO(new AmletIO(params))

  val errors = Wire(new AmletErrors())
  dontTouch(errors)

  // Buffer thisX and thisY
  val bufferedThisX = RegNext(io.thisX)
  val bufferedThisY = RegNext(io.thisY)
  
  // Instantiate register file and rename unit
  val registerFileAndRename = Module(new RegisterFileAndRename(params))
  
  // Instantiate reservation stations
  val aluRS = Module(new ALURS(params))
  val aluLiteRS = Module(new ALULiteRS(params))
  val aluPredicateRS = Module(new ALUPredicateRS(params))
  val loadStoreRS = Module(new LoadStoreRS(params))
  val sendPacketRS = Module(new SendPacketRS(params))
  val receivePacketRS = Module(new ReceivePacketRS(params))
  
  // Instantiate execution units
  val alu = Module(new ALU(params))
  val aluLite = Module(new ALULite(params))
  val aluPredicate = Module(new ALUPredicate(params))
  val dataMem = Module(new DataMemory(params))
  val sendPacketInterface = Module(new SendPacketInterface(params))
  val receivePacketInterface = Module(new ReceivePacketInterface(params))
  val networkNode = Module(new NetworkNode(params))
  
  // Connect instruction input to RegisterFileAndRename with optional buffering
  val skidBuffer = Module(new SkidBuffer(new VLIWInstr.Expanded(params), params.instructionBackwardBuffer))
  val decoupledBuffer = Module(new DecoupledBuffer(new VLIWInstr.Expanded(params), params.instructionForwardBuffer))
  
  // Chain: instruction -> SkidBuffer -> DecoupledBuffer -> RegisterFileAndRename
  skidBuffer.io.i <> io.instruction
  decoupledBuffer.io.i <> skidBuffer.io.o
  registerFileAndRename.io.instr <> decoupledBuffer.io.o
  
  // Connect RegisterFileAndRename outputs to reservation stations
  aluRS.io.input <> registerFileAndRename.io.aluInstr
  aluLiteRS.io.input <> registerFileAndRename.io.aluliteInstr
  aluPredicateRS.io.input <> registerFileAndRename.io.aluPredicateInstr
  loadStoreRS.io.input <> registerFileAndRename.io.ldstInstr
  sendPacketRS.io.input <> registerFileAndRename.io.sendPacketInstr
  receivePacketRS.io.input <> registerFileAndRename.io.recvPacketInstr
  
  // Connect execution units to reservation stations
  alu.io.instr := aluRS.io.output
  aluRS.io.output.ready := true.B
  
  aluLite.io.instr := aluLiteRS.io.output
  aluLiteRS.io.output.ready := true.B

  aluPredicate.io.instr := aluPredicateRS.io.output
  aluPredicateRS.io.output.ready := true.B
  
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
  resultBus.predicate(0) := aluPredicate.io.result
  resultBus.predicate(1) := receivePacketInterface.io.resultPredicate
  
  
  // Connect results to RegisterFileAndRename and reservation stations for dependency resolution
  registerFileAndRename.io.resultBus := resultBus
  aluRS.io.resultBus := resultBus
  aluLiteRS.io.resultBus := resultBus
  aluPredicateRS.io.resultBus := resultBus
  loadStoreRS.io.resultBus := resultBus
  sendPacketRS.io.resultBus := resultBus
  receivePacketRS.io.resultBus := resultBus
  
  // Connect results to packet interfaces for dependency resolution
  sendPacketInterface.io.writeInputs := resultBus.writes
  
  
  // Connect control outputs from ReceivePacketInterface
  io.start := receivePacketInterface.io.start
  io.writeControl := receivePacketInterface.io.writeControl
  
  // Connect loop iteration reporting from RegisterFileAndRename
  io.loopIterations := registerFileAndRename.io.loopIterations

  errors.receivePacketInterface := receivePacketInterface.io.errors
  
  // Connect position to modules that need it
  networkNode.io.thisX := bufferedThisX
  networkNode.io.thisY := bufferedThisY
  receivePacketInterface.io.thisX := bufferedThisX
  receivePacketInterface.io.thisY := bufferedThisY
  
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
