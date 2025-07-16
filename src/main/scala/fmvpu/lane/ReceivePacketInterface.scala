package fmvpu.lane

import chisel3._
import chisel3.util._
import fmvpu.utils._

/**
 * Receive Packet Interface IO
 */
class ReceivePacketInterfaceIO(params: LaneParams) extends Bundle {
  // Current position for routing calculations
  val thisX = Input(UInt(params.xPosWidth.W))
  val thisY = Input(UInt(params.yPosWidth.W))
  
  // Network interface
  val fromNetwork = Flipped(Decoupled(new NetworkWord(params)))
  
  // Instruction interface
  val instr = Flipped(Decoupled(new PacketInstrResolved(params)))
  
  // Forward interface
  val forward = Valid(new PacketForward(params))
  
  // Register write interface
  val writeReg = new WriteResult(params)
  
  // Instruction memory write interface
  val writeIM = Valid(new IMWrite(params))
  
  // Control outputs
  val start = Valid(UInt(params.instrAddrWidth.W))
  
  // Error outputs
  val errors = Output(new ReceivePacketInterfaceErrors)
}

/**
 * Error outputs for ReceivePacketInterface
 */
class ReceivePacketInterfaceErrors extends Bundle {
  val instrAndCommandPacket = Bool()
  val wrongInstructionMode = Bool()
}

/**
 * Receive Packet Interface Module
 * 
 * Handles coordination between incoming network packets and receive instructions:
 * 
 * PACKET TYPES:
 * - CommandPackets: Can be received without a Receive Instruction
 * - NormalPackets: Require a Receive Instruction to be processed
 * 
 * COORDINATION RULES:
 * - Do not consume Receive Instruction until we get a matching NormalPacket header
 * - Do not consume NormalPacket header until we have a Receive Instruction  
 * - Receive Instructions are consumed when entering ReceivingData state
 * - GetWord Instructions are consumed with each data word in ReceivingData state
 * 
 * FORWARDING:
 * - Forward signals sent when Receive Instruction indicates forwarding needed
 * - Only send forward signal when in Idle state
 * - Forward signal is Valid interface (no ready signal needed)
 * - Toggle field changes each time new forward data is sent (detects back-to-back forwards)
 * 
 * ERROR CONDITIONS:
 * - Wrong instruction mode for current state
 * - Command packet received while receive instruction pending
 * - Any hardware limitation that prevents proper packet processing
 */
class ReceivePacketInterface(params: LaneParams) extends Module {
  val io = IO(new ReceivePacketInterfaceIO(params))
  
  /**
   * Packet interface receive states
   */
  object States extends ChiselEnum {
    val Idle = Value(0.U)
    val ReceivingData = Value(1.U)
    val ProcessingCommand = Value(2.U)
  }
  
  // Receive state  
  val receiveState = RegInit(States.Idle)
  val receiveRemainingWords = RegInit(0.U(8.W))
  
  // Forward toggle register
  val forwardToggle = RegInit(false.B)
  
  
  // Error signals
  val errorInstrAndCommandPacket = RegInit(false.B)
  val errorWrongInstructionMode = RegInit(false.B)
  io.errors.instrAndCommandPacket := errorInstrAndCommandPacket
  io.errors.wrongInstructionMode := errorWrongInstructionMode
  
  // Default outputs
  io.writeReg.valid := false.B
  io.writeReg.address.regAddr := DontCare
  io.writeReg.address.writeIdent := DontCare
  io.writeReg.value := DontCare
  io.writeReg.force := DontCare
  io.writeIM.valid := false.B
  io.writeIM.bits := DontCare
  
  io.start.valid := false.B
  io.start.bits := DontCare
  io.forward.valid := false.B
  io.forward.bits := DontCare
  io.fromNetwork.ready := false.B
  
  
  /*
   * PACKET RECEPTION STATE MACHINE:
   * 
   * State transitions:
   * - Idle + command_header → ProcessingCommand
   * - Idle + normal_header + receive_instr (both available) → ReceivingData
   *   - Consume both header and receive instruction
   *   - Write packet length to register specified by receive instruction  
   *   - Send forward info if instruction requires forwarding
   * - ReceivingData + getword_instr + data_word → ReceivingData or Idle
   *   - Consume both GetWord instruction and data word together
   *   - Write data to register specified by GetWord instruction
   * - ProcessingCommand + command_word → ProcessingCommand or Idle
   * 
   * Forward signals: Sent when idle with forwarding receive instruction
   * Error handling: Track wrong instruction modes and unsupported cases
   */

  // Buffer data coming from the network
  val bufferedFromNetwork = Wire(Decoupled(new NetworkWord(params)))
  val bufferFromNetwork = Module(new DoubleBuffer(new NetworkWord(params)))
  bufferFromNetwork.io.i <> io.fromNetwork
  bufferFromNetwork.io.o <> bufferedFromNetwork

  // Buffer receive instructions
  val bufferedInstr = Wire(Decoupled(new PacketInstrResolved(params)))
  val bufferInstr = Module(new DoubleBuffer(new PacketInstrResolved(params)))
  bufferInstr.io.i <> io.instr
  bufferInstr.io.o <> bufferedInstr

  // Default ready signals for buffered interfaces
  bufferedFromNetwork.ready := false.B
  bufferedInstr.ready := false.B

  val receivingHeader = bufferedFromNetwork.valid && bufferedFromNetwork.bits.isHeader

  val header = bufferedFromNetwork.bits.data.asTypeOf(new PacketHeader(params))

  errorInstrAndCommandPacket := false.B
  errorWrongInstructionMode := false.B
  
  val commandType = bufferedFromNetwork.bits.data(params.width-1, params.width-2) // Top 2 bits = command type
  val commandData = bufferedFromNetwork.bits.data(params.width-3, 0)              // Bottom width-2 bits = data
  val forwardDirection = PacketRouting.calculateNextDirection(params, io.thisX, io.thisY, bufferedInstr.bits.xTarget, bufferedInstr.bits.yTarget)
  val forwardHeader = PacketRouting.createForwardHeader(params, bufferedInstr.bits.xTarget, bufferedInstr.bits.yTarget, bufferedInstr.bits.forwardAgain)
  switch(receiveState) {
    is(States.Idle) {
      // Consume masked receive instructions without executing
      when (bufferedInstr.valid && bufferedInstr.bits.mask &&
           (bufferedInstr.bits.mode === PacketModes.Receive ||
            bufferedInstr.bits.mode === PacketModes.ReceiveAndForward ||
            bufferedInstr.bits.mode === PacketModes.ReceiveForwardAndAppend)) {
        bufferedInstr.ready := true.B  // Consume but don't execute
      }
      
      // Send forward info if we have a forwarding instruction (and not masked)
      when (bufferedInstr.valid && !bufferedInstr.bits.mask &&
           (bufferedInstr.bits.mode === PacketModes.ReceiveAndForward ||
            bufferedInstr.bits.mode === PacketModes.ReceiveForwardAndAppend)) {
        io.forward.valid := true.B
        // Calculate routing direction and create header using utility functions
        
        io.forward.bits.networkDirection := forwardDirection
        io.forward.bits.header := forwardHeader.asUInt
        io.forward.bits.append := (bufferedInstr.bits.mode === PacketModes.ReceiveForwardAndAppend)
        io.forward.bits.toggle := forwardToggle
      }
      
      when (receivingHeader) {
        when(header.mode === PacketHeaderModes.Command) {
          // Command packets don't need instructions - process immediately
          bufferedFromNetwork.ready := true.B
          receiveRemainingWords := header.length
          receiveState := States.ProcessingCommand
          // Ignore any pending receive instruction for command packets
        } .otherwise {
          // Normal packets need both header and instruction (and instruction not masked)
          when (bufferedInstr.valid && !bufferedInstr.bits.mask) {
            // We have both - consume both and start receiving data
            bufferedFromNetwork.ready := true.B
            bufferedInstr.ready := true.B
            receiveRemainingWords := header.length
            receiveState := States.ReceivingData
            
            // Toggle forward signal when consuming any instruction
            forwardToggle := !forwardToggle
            
            // Error if wrong instruction mode
            when (!(bufferedInstr.bits.mode === PacketModes.Receive ||
                    bufferedInstr.bits.mode === PacketModes.ReceiveAndForward ||
                    bufferedInstr.bits.mode === PacketModes.ReceiveForwardAndAppend)) {
              errorWrongInstructionMode := true.B
            }
            
            // Write packet length to the result register specified by instruction
            io.writeReg.valid := true.B
            io.writeReg.address.regAddr := bufferedInstr.bits.result.regAddr
            io.writeReg.address.writeIdent := bufferedInstr.bits.result.writeIdent
            io.writeReg.value := header.length
            io.writeReg.force := false.B
          }
          // If no instruction available or instruction is masked, stay in Idle (don't consume header)
        }
      }
      // If no header available, stay in Idle (don't consume instruction)
    }
    is(States.ReceivingData) {
      // Consume GetWord instruction and data word together
      when (bufferedInstr.valid && bufferedFromNetwork.valid) {
        bufferedFromNetwork.ready := true.B
        bufferedInstr.ready := true.B
        
        // Error if wrong instruction mode
        when (bufferedInstr.bits.mode =/= PacketModes.GetWord) {
          errorWrongInstructionMode := true.B
        }
        
        // Only write to register if not masked
        when (!bufferedInstr.bits.mask) {
          io.writeReg.valid := true.B
          io.writeReg.value := bufferedFromNetwork.bits.data
          io.writeReg.address.regAddr := bufferedInstr.bits.result.regAddr
          io.writeReg.address.writeIdent := bufferedInstr.bits.result.writeIdent
          io.writeReg.force := false.B
        }
        
        receiveRemainingWords := receiveRemainingWords - 1.U
        when (receiveRemainingWords === 1.U) {
          receiveState := States.Idle
        }
      }
    }
    is(States.ProcessingCommand) {
      
      when (bufferedFromNetwork.valid) {
        receiveRemainingWords := receiveRemainingWords - 1.U
        when(receiveRemainingWords === 1.U) {
          receiveState := States.Idle
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
            io.writeIM.bits.data := commandData(params.instructionWidth+params.instrAddrWidth-1, params.instrAddrWidth)
          }
          is(2.U) { // Write to register command
            io.writeReg.valid := true.B
            io.writeReg.address.regAddr := commandData(params.width-3, params.width-2-params.regAddrWidth)
            io.writeReg.address.writeIdent := 0.U // Command writes don't use write identifiers
            io.writeReg.value := Cat(0.U(params.regAddrWidth.W), commandData(params.width-2-params.regAddrWidth-1, 0))
            io.writeReg.force := true.B // Command writes bypass dependency system
          }
        }
      }
      
      bufferedFromNetwork.ready := true.B
    }
  }
  
}

/**
 * Module generator for PacketInterface
 */
object ReceivePacketInterfaceGenerator extends fmvpu.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> ReceivePacketInterface <laneParamsFileName>")
      null
    } else {
      val params = LaneParams.fromFile(args(0))
      new ReceivePacketInterface(params)
    }
  }
}
