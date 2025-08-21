package zamlet.amlet

import chisel3._
import chisel3.util._
import zamlet.utils.{DecoupledBuffer, SkidBuffer, ResetStage, ValidBuffer}

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
  val aluRS = new ReservationStationErrors()
  val aluLiteRS = new ReservationStationErrors()
  val aluPredicateRS = new ReservationStationErrors()
  val loadStoreRS = new ReservationStationErrors()
  val sendPacketRS = new ReservationStationErrors()
  val receivePacketRS = new ReservationStationErrors()
}

/**
 * Amlet - Smallest processing unit with reservation stations and execution units
 */
class Amlet(params: AmletParams) extends Module {
  val io = IO(new AmletIO(params))

  val errors = Wire(new AmletErrors())
  dontTouch(errors)

  
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

  val resetBuffered = ResetStage(clock, reset)

  withReset(resetBuffered) {
  
    // Buffer thisX and thisY
    val bufferedThisX = RegNext(io.thisX)
    val bufferedThisY = RegNext(io.thisY)

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
    val namedResultBus = Wire(new NamedResultBus(params))
    namedResultBus.alu := alu.io.result
    namedResultBus.alulite := aluLite.io.result
    namedResultBus.ldSt := dataMem.io.result
    namedResultBus.packet := receivePacketInterface.io.result
    namedResultBus.aluPredicate := aluPredicate.io.result
    namedResultBus.packetPredicate := receivePacketInterface.io.resultPredicate
    
    // Convert to generic result bus for reservation stations
    val resultBus = namedResultBus.toResultBus()

    // This buffer is here to delay the resultBus so that we don't miss some results
    // in between the RF and the RS.
    //
    // The time for a the effect of a result to get here via the RF is
    // resultBus -> RF.iaResultsBuffer -> write_cycle -> RF.aoBuffer -> RS.iaBuffer
    // resultBus -> resultBusBuffer -> RS.iaBuffer
    //
    // It should arrive via the resultBus on the same cycle
    // if it arrived earlier to will have instructions that missed it from the RF and
    // missed it from the resultBus.
    // if it arrives later that's just unnecessary latency.

    // This means that resultBusBuffer should have a latency of 1 + RF.iaResultsBuffer + RF.aoBuffer
    val resultBusDelay = 1 + (if (params.rfParams.iaResultsBuffer) 1 else 0)  + (if (params.rfParams.aoBuffer) 1 else 0)
    val resultBusInit = Wire(new ResultBus(params))
    resultBusInit := DontCare
    for (i <- 0 until params.nResultPorts) {
      resultBusInit.writes(i).valid := false.B
    }
    for (i <- 0 until 2) {
      resultBusInit.predicate(i).valid := false.B
    }
    val delayedResultBus = ShiftRegister(resultBus, resultBusDelay, resultBusInit, true.B)
    
    // Connect results to RegisterFileAndRename (uses named bus) and reservation stations (use generic bus)
    registerFileAndRename.io.resultBus := namedResultBus
    aluRS.io.resultBus := delayedResultBus
    aluLiteRS.io.resultBus := delayedResultBus
    aluPredicateRS.io.resultBus := delayedResultBus
    loadStoreRS.io.resultBus := delayedResultBus
    sendPacketRS.io.resultBus := delayedResultBus
    receivePacketRS.io.resultBus := delayedResultBus
    
    // Connect results to packet interfaces for dependency resolution
    sendPacketInterface.io.writeInputs := resultBus.writes
    
    // Connect control outputs from ReceivePacketInterface
    io.start := receivePacketInterface.io.start
    io.writeControl := receivePacketInterface.io.writeControl
    
    // Connect loop iteration reporting from RegisterFileAndRename
    io.loopIterations := registerFileAndRename.io.loopIterations

    errors.receivePacketInterface := receivePacketInterface.io.errors
    errors.aluRS := aluRS.io.error
    errors.aluLiteRS := aluLiteRS.io.error
    errors.aluPredicateRS := aluPredicateRS.io.error
    errors.loadStoreRS := loadStoreRS.io.error
    errors.sendPacketRS := sendPacketRS.io.error
    errors.receivePacketRS := receivePacketRS.io.error
    
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
}

object AmletGenerator extends zamlet.ModuleGenerator {
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
