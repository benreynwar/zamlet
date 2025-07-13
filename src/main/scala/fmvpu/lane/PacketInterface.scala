package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Packet header format
 */
class PacketHeader(params: LaneParams) extends Bundle {
  val length = UInt(params.packetLengthWidth.W)
  val xDest = UInt(params.xPosWidth.W)
  val yDest = UInt(params.yPosWidth.W)
  val mode = PacketHeaderModes()
  val forward = Bool()
  val isBroadcast = Bool()
  val broadcastDirection = BroadcastDirections()
  
  // Backward compatibility: destination field as concatenated x,y
  def destination: UInt = Cat(yDest, xDest)
}

/**
 * Network word with header indication
 */
class NetworkWord(params: LaneParams) extends Bundle {
  val data = UInt(params.width.W)
  val isHeader = Bool()
}

/**
 * Instruction memory write bundle
 */
class IMWrite(params: LaneParams) extends Bundle {
  val address = UInt(params.instrAddrWidth.W)
  val data = UInt(params.width.W)
}

/**
 * Packet forward bundle
 */
class PacketForward(params: LaneParams) extends Bundle {
  val networkDirection = NetworkDirections()
  val header = UInt(params.width.W)
  val append = Bool()
}

/**
 * Packet interface error signals
 */
class PacketInterfaceErrors extends Bundle {
  val unexpectedDataWord = Bool()
}

/**
 * Packet Interface IO
 */
class PacketInterfaceIO(params: LaneParams) extends Bundle {
  // Network interface
  val fromNetwork = Flipped(Decoupled(new NetworkWord(params)))
  val toNetwork = Decoupled(new NetworkWord(params))
  val toNetworkChannel = Output(UInt(log2Ceil(params.nChannels).W))
  
  // Instruction interface
  val instr = Input(Valid(new PacketInstrResolved(params)))
  
  // Write inputs for packet data
  val writeInputs = Input(Vec(params.nWritePorts, new WriteResult(params)))
  
  // Forward interface
  val forward = Decoupled(new PacketForward(params))
  
  // Register write interface
  val writeReg = Valid(new WriteResult(params))
  
  // Instruction memory write interface
  val writeIM = Valid(new IMWrite(params))
  
  // Control outputs
  val start = Valid(UInt(params.instrAddrWidth.W))
  
  // Status outputs
  val sendReady = Output(Bool())
  val receiveReady = Output(Bool())
  val getWordReady = Output(Bool())
  
  // Error outputs
  val errors = Output(new PacketInterfaceErrors)
}

/**
 * Packet interface send states
 */
object SendStates extends ChiselEnum {
  val Idle = Value(0.U)
  val SendingHeader = Value(1.U)
  val SendingData = Value(2.U)
}

/**
 * Packet interface receive states
 */
object ReceiveStates extends ChiselEnum {
  val Idle = Value(0.U)
  val WaitingForReceiveInstr = Value(1.U)
  val WaitingForHeader = Value(2.U)
  val ReceivingData = Value(3.U)
  val ProcessingCommand = Value(4.U)
}

/**
 * Packet Interface Module
 * Handles packet send/receive/forward operations
 */
class PacketInterface(params: LaneParams) extends Module {
  val io = IO(new PacketInterfaceIO(params))
  
  // Packet buffer for out-of-order sends
  val packetOutBuffer = RegInit(VecInit(Seq.fill(params.nPacketOutIdents){
    val init = Wire(Valid(UInt(params.width.W)))
    init.valid := false.B
    init.bits := 0.U
    init
  }))
  val packetOutReadPtr = RegInit(0.U(log2Ceil(params.nPacketOutIdents).W))
  
  // Send state
  val sendState = RegInit(SendStates.Idle)
  val sendRemainingWords = RegInit(0.U(8.W))
  val sendChannel = RegInit(0.U(log2Ceil(params.nChannels).W))
  
  // Receive state  
  val receiveState = RegInit(ReceiveStates.Idle)
  val receiveRemainingWords = RegInit(0.U(8.W))
  val receiveHeader = RegInit(0.U(params.width.W))
  val receiveIsCommand = RegInit(false.B)
  val receiveDataBuffer = RegInit(0.U(params.width.W))
  val receiveDataValid = RegInit(false.B)
  
  // Forward state
  val forwardPending = RegInit(false.B)
  val forwardDirection = RegInit(NetworkDirections.North)
  val forwardHeader = RegInit(0.U(params.width.W))
  
  // Write identifier counter for received words
  val receiveWriteIdent = RegInit(0.U(params.writeIdentWidth.W))
  
  // Status outputs
  io.sendReady := sendState === SendStates.Idle
  io.receiveReady := receiveState === ReceiveStates.Idle || receiveState === ReceiveStates.WaitingForReceiveInstr
  io.getWordReady := receiveDataValid
  
  // Default outputs
  io.toNetwork.valid := false.B
  io.toNetwork.bits := DontCare
  io.writeReg.valid := false.B
  io.writeReg.bits := DontCare
  io.writeIM.valid := false.B
  io.writeIM.bits := DontCare
  
  io.start.valid := false.B
  io.start.bits := DontCare
  io.forward.valid := false.B
  io.forward.bits := DontCare
  io.fromNetwork.ready := false.B
  
  // Helper signals
  val receivingHeader = io.fromNetwork.valid && io.fromNetwork.bits.isHeader
  val receivingReceiveInstr = io.instr.valid && (io.instr.bits.mode === PacketModes.Receive || 
                                                 io.instr.bits.mode === PacketModes.ReceiveAndForward ||
                                                 io.instr.bits.mode === PacketModes.ReceiveForwardAndAppend)
  
  /*
   * PACKET RECEPTION STATE MACHINE OVERVIEW:
   * 
   * The complexity comes from handling the race between:
   * 1. Packet headers arriving from network
   * 2. Receive instructions arriving from processor
   * 
   * For COMMAND packets: Always accept immediately (no instruction needed)
   * For NORMAL packets: Need a receive instruction to proceed
   * 
   * State transitions:
   * - Idle + receive_instr → WaitingForHeader  
   * - Idle + normal_header (no instr) → WaitingForReceiveInstr
   * - Idle + normal_header + receive_instr (same cycle) → ReceivingData
   * - WaitingForHeader + normal_header → ReceivingData
   * - WaitingForReceiveInstr + receive_instr → ReceivingData
   * - Any + command_header → ProcessingCommand
   */
  
  // Process incoming network packet headers
  when(receivingHeader) {
    val header = io.fromNetwork.bits.data.asTypeOf(new PacketHeader(params))
    
    when(header.mode === PacketHeaderModes.Command) {
      // Command packets: always accept immediately
      receiveHeader := io.fromNetwork.bits.data
      receiveRemainingWords := header.length
      receiveIsCommand := true.B
      receiveState := ReceiveStates.ProcessingCommand
      receiveWriteIdent := 0.U
      io.fromNetwork.ready := true.B
    }.elsewhen(receiveState === ReceiveStates.WaitingForHeader || 
               (receiveState === ReceiveStates.Idle && receivingReceiveInstr)) {
      // Normal packet with receive instruction (either waiting or arriving same cycle)
      receiveHeader := io.fromNetwork.bits.data
      receiveRemainingWords := header.length
      receiveIsCommand := false.B
      receiveState := ReceiveStates.ReceivingData
      receiveWriteIdent := 0.U
      io.fromNetwork.ready := true.B
    }.otherwise {
      // Normal packet but no receive instruction yet
      receiveHeader := io.fromNetwork.bits.data
      receiveRemainingWords := header.length
      receiveIsCommand := false.B
      receiveState := ReceiveStates.WaitingForReceiveInstr
      receiveWriteIdent := 0.U
      io.fromNetwork.ready := true.B
    }
  }
  
  // Handle receive instructions when waiting for them
  when(receivingReceiveInstr && receiveState === ReceiveStates.WaitingForReceiveInstr) {
    receiveState := ReceiveStates.ReceivingData
  }
  
  // Handle receive instructions when idle (will wait for header)
  when(receivingReceiveInstr && receiveState === ReceiveStates.Idle) {
    receiveState := ReceiveStates.WaitingForHeader
  }
  
  /*
   * DATA BUFFER TIMING CRITICAL SECTION:
   * 
   * The receiveDataBuffer can only hold one word at a time. We need to handle
   * the case where GetPacketWord consumes data in the SAME cycle that new data arrives.
   */
  
  // Handle GetPacketWord instruction first (before data reception)
  when(io.instr.valid && io.instr.bits.mode === PacketModes.GetPacketWord && receiveDataValid) {
    io.writeReg.valid := true.B
    io.writeReg.bits.valid := true.B
    io.writeReg.bits.value := receiveDataBuffer
    io.writeReg.bits.address.regAddr := io.instr.bits.result.regAddr
    io.writeReg.bits.address.writeIdent := io.instr.bits.result.writeIdent
    io.writeReg.bits.force := false.B
    receiveDataValid := false.B  // Clear buffer for new data
    receiveWriteIdent := receiveWriteIdent + 1.U
  }
  
  // Check if data buffer can accept new data
  val receiveDataReady = io.instr.valid && io.instr.bits.mode === PacketModes.GetPacketWord
  val receiveDataCanAccept = !receiveDataValid || receiveDataReady  // Empty OR being consumed this cycle
  
  // Process packet data words
  when(io.fromNetwork.valid && !io.fromNetwork.bits.isHeader) {
    // Error detection
    io.errors.unexpectedDataWord := receiveRemainingWords === 0.U
    
    when(receiveState === ReceiveStates.ProcessingCommand) {
      // Command packets: decode and execute commands
      val commandWord = io.fromNetwork.bits.data
      val commandType = commandWord(params.width-1, params.width-2) // Top 2 bits = command type
      val commandData = commandWord(params.width-3, 0)              // Bottom width-2 bits = data
      
      receiveRemainingWords := receiveRemainingWords - 1.U
      when(receiveRemainingWords === 1.U) {
        receiveState := ReceiveStates.Idle
      }
      
      // Execute command based on type
      switch(commandType) {
        is(0.U) { // Start processor command
          io.start.valid := true.B
          io.start.bits := commandData(params.instrAddrWidth-1, 0)
        }
        is(1.U) { // Write to instruction memory command
          io.writeIM.valid := true.B
          io.writeIM.bits.address := commandData(params.instrAddrWidth-1, 0)
          io.writeIM.bits.data := commandData(params.width-3, params.instrAddrWidth)
        }
        is(2.U) { // Write to register command
          io.writeReg.valid := true.B
          io.writeReg.bits.valid := true.B
          io.writeReg.bits.address.regAddr := commandData(params.width-3, params.width-2-params.regAddrWidth)
          io.writeReg.bits.address.writeIdent := 0.U // Command writes don't use write identifiers
          io.writeReg.bits.value := commandData(params.width-3-params.regAddrWidth, 0)
          io.writeReg.bits.force := true.B // Command writes bypass dependency system
        }
      }
      
      io.fromNetwork.ready := true.B
    }.elsewhen(receiveState === ReceiveStates.ReceivingData && receiveDataCanAccept) {
      // Normal packets: accept if data buffer can accept new data
      receiveDataBuffer := io.fromNetwork.bits.data
      receiveDataValid := true.B
      receiveRemainingWords := receiveRemainingWords - 1.U
      when(receiveRemainingWords === 1.U) {
        receiveState := ReceiveStates.Idle
      }
      io.fromNetwork.ready := true.B
    }
  }.otherwise {
    io.errors.unexpectedDataWord := false.B
  }
  
  // Handle writes to packet output register (register 0)
  for (i <- 0 until params.nWritePorts) {
    when(io.writeInputs(i).valid && 
         io.writeInputs(i).address.regAddr === params.packetWordOutRegAddr.U && 
         !io.writeInputs(i).force) {
      val writeIdent = io.writeInputs(i).address.writeIdent
      packetOutBuffer(writeIdent).valid := true.B
      packetOutBuffer(writeIdent).bits := io.writeInputs(i).value
    }
  }
  
  // Handle send instructions
  when(io.instr.valid && io.instr.bits.mode === PacketModes.Send && sendState === SendStates.Idle) {
    sendState := SendStates.SendingHeader
    sendRemainingWords := io.instr.bits.sendLength
    sendChannel := io.instr.bits.channel
    packetOutReadPtr := 0.U
  }
  
  // Send state machine
  io.toNetworkChannel := sendChannel
  switch(sendState) {
    is(SendStates.SendingHeader) {
      // Create and send packet header
      val header = Wire(new PacketHeader(params))
      header.length := sendRemainingWords
      header.xDest := io.instr.bits.xTarget
      header.yDest := io.instr.bits.yTarget
      header.mode := PacketHeaderModes.Normal
      header.forward := false.B
      header.isBroadcast := false.B
      header.broadcastDirection := BroadcastDirections.NE
      
      io.toNetwork.valid := true.B
      io.toNetwork.bits.data := header.asUInt
      io.toNetwork.bits.isHeader := true.B
      
      when(io.toNetwork.ready) {
        sendState := SendStates.SendingData
      }
    }
    
    is(SendStates.SendingData) {
      // Send packet data from buffer
      when(packetOutBuffer(packetOutReadPtr).valid && sendRemainingWords > 0.U) {
        io.toNetwork.valid := true.B
        io.toNetwork.bits.data := packetOutBuffer(packetOutReadPtr).bits
        io.toNetwork.bits.isHeader := false.B
        
        when(io.toNetwork.ready) {
          packetOutBuffer(packetOutReadPtr).valid := false.B
          packetOutReadPtr := packetOutReadPtr + 1.U
          sendRemainingWords := sendRemainingWords - 1.U
          when(sendRemainingWords === 1.U) {
            sendState := SendStates.Idle
          }
        }
      }
    }
  }
}

/**
 * Module generator for PacketInterface
 */
object PacketInterfaceGenerator extends fmvpu.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> PacketInterface <laneParamsFileName>")
      null
    } else {
      val params = LaneParams.fromFile(args(0))
      new PacketInterface(params)
    }
  }
}
