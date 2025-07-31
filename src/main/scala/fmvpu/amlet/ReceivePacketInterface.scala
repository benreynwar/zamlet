package fmvpu.amlet

import chisel3._
import chisel3.util._
import fmvpu.utils._

/**
 * Receive Packet Interface IO
 */
class ReceivePacketInterfaceIO(params: AmletParams) extends Bundle {
  // Current position for routing calculations
  val thisX = Input(UInt(params.xPosWidth.W))
  val thisY = Input(UInt(params.yPosWidth.W))
  
  // Network interface
  val fromNetwork = Flipped(Decoupled(new NetworkWord(params)))
  
  // Instruction interface
  val instr = Flipped(Decoupled(new PacketInstr.ReceiveResolved(params)))
  
  // Forward interface
  val forward = Valid(new PacketForward(params))
  
  // Result interface
  val result = Valid(new WriteResult(params))
  val resultPredicate = Valid(new PredicateResult(params))
  
  // Instruction memory write interface
  val writeControl = Valid(new ControlWrite(params))

  // Control outputs
  val start = Valid(UInt(16.W)) // instrAddrWidth equivalent
  
  // Error outputs
  val errors = Output(new ReceivePacketInterfaceErrors)
}

/**
 * Error outputs for ReceivePacketInterface
 */
class ReceivePacketInterfaceErrors extends Bundle {
  val instrAndCommandPacket = Bool()
  val wrongInstructionMode = Bool()
  val imWriteCountExceedsPacket = Bool()
  val unexpectedHeader = Bool()
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
class ReceivePacketInterface(params: AmletParams) extends Module {
  val io = IO(new ReceivePacketInterfaceIO(params))
  
  /**
   * Packet interface receive states
   */
  object States extends ChiselEnum {
    val Idle = Value(0.U)
    val ReceivingData = Value(1.U)
    val ProcessingCommand = Value(2.U)
    val ProcessingIMWrites = Value(3.U)
    val ProcessingRegWrite = Value(4.U)
  }
  
  // Receive state  
  val receiveState = RegInit(States.Idle)
  val receiveRemainingWords = RegInit(0.U(8.W))
  
  // IM write state
  val imWriteAddress = RegInit(0.U(16.W))
  val imWriteCount = RegInit(0.U(8.W))
  
  // Register write command state
  val regWriteAddress = RegInit(0.U(params.regWidth.W))
  
  // Forward toggle register
  val forwardToggle = RegInit(false.B)
  
  
  // Error signals
  val errorInstrAndCommandPacket = RegInit(false.B)
  val errorWrongInstructionMode = RegInit(false.B)
  val errorIMWriteCountExceedsPacket = RegInit(false.B)
  val errorUnexpectedHeader = RegInit(false.B)
  io.errors.instrAndCommandPacket := errorInstrAndCommandPacket
  io.errors.wrongInstructionMode := errorWrongInstructionMode
  io.errors.imWriteCountExceedsPacket := errorIMWriteCountExceedsPacket
  io.errors.unexpectedHeader := errorUnexpectedHeader
  
  // Default outputs
  io.result.valid := false.B
  io.result.bits.address.addr := DontCare
  io.result.bits.address.tag := DontCare
  io.result.bits.value := DontCare
  io.result.bits.force := DontCare
  io.resultPredicate.valid := false.B
  io.resultPredicate.bits.address.addr := DontCare
  io.resultPredicate.bits.address.tag := DontCare  
  io.resultPredicate.bits.value := DontCare
  io.writeControl.valid := false.B
  io.writeControl.bits := DontCare
  
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
  val bufferedInstr = Wire(Decoupled(new PacketInstr.ReceiveResolved(params)))
  val bufferInstr = Module(new DoubleBuffer(new PacketInstr.ReceiveResolved(params)))
  bufferInstr.io.i <> io.instr
  bufferInstr.io.o <> bufferedInstr

  // Default ready signals for buffered interfaces
  bufferedFromNetwork.ready := false.B
  bufferedInstr.ready := false.B

  val receivingHeader = bufferedFromNetwork.valid && bufferedFromNetwork.bits.isHeader

  val header = bufferedFromNetwork.bits.data.asTypeOf(new PacketHeader(params))

  errorInstrAndCommandPacket := false.B
  errorWrongInstructionMode := false.B
  errorIMWriteCountExceedsPacket := false.B

  val commandType = bufferedFromNetwork.bits.data(params.width-1, params.width-2) // Top 2 bits = command type
  val commandData = bufferedFromNetwork.bits.data(params.width-3, 0)              // Bottom width-2 bits = data
  val forwardDirection = PacketRouting.calculateNextDirection(params, io.thisX, io.thisY, bufferedInstr.bits.xTarget, bufferedInstr.bits.yTarget)

  errorUnexpectedHeader := receivingHeader
  switch(receiveState) {
    is(States.Idle) {
      errorUnexpectedHeader := false.B
      // Send forward info if we have a forwarding instruction
      when (bufferedInstr.valid &&
           (bufferedInstr.bits.mode === PacketInstr.Modes.ReceiveAndForward ||
            bufferedInstr.bits.mode === PacketInstr.Modes.ReceiveForwardAndAppend)) {
        io.forward.valid := true.B
        // Calculate routing direction and create header using utility functions
        
        io.forward.bits.networkDirection := forwardDirection
        io.forward.bits.xDest := bufferedInstr.bits.xTarget
        io.forward.bits.yDest := bufferedInstr.bits.yTarget
        io.forward.bits.forward := bufferedInstr.bits.forwardContinuously
        io.forward.bits.append := bufferedInstr.bits.shouldAppend
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
          when (bufferedInstr.valid) {
            // We have both - consume both and start receiving data
            bufferedFromNetwork.ready := true.B
            bufferedInstr.ready := true.B
            receiveRemainingWords := header.length
            when (header.length > 0.U) {
              receiveState := States.ReceivingData
            }
            
            // Toggle forward signal when consuming any instruction
            forwardToggle := !forwardToggle
            
            // Error if wrong instruction mode
            when (!(bufferedInstr.bits.mode === PacketInstr.Modes.Receive ||
                    bufferedInstr.bits.mode === PacketInstr.Modes.ReceiveAndForward ||
                    bufferedInstr.bits.mode === PacketInstr.Modes.ReceiveForwardAndAppend)) {
              errorWrongInstructionMode := true.B
            }
            
            // Write packet length to the result register specified by instruction
            io.result.valid := true.B
            io.result.bits.address.addr := bufferedInstr.bits.result.addr
            io.result.bits.address.tag := bufferedInstr.bits.result.tag
            io.result.bits.value := header.length
            io.result.bits.force := false.B
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
        when (bufferedInstr.bits.mode =/= PacketInstr.Modes.GetWord) {
          errorWrongInstructionMode := true.B
        }
        
        // Write to register
        io.result.valid := true.B
        io.result.bits.value := bufferedFromNetwork.bits.data
        io.result.bits.address.addr := bufferedInstr.bits.result.addr
        io.result.bits.address.tag := bufferedInstr.bits.result.tag
        io.result.bits.force := false.B
        
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
            io.start.bits := commandData(15, 0) // instrAddrWidth equivalent
          }
          is(1.U) { // Write to instruction memory command setup
            val requestedCount = commandData(23, 16) // Count in next 8 bits
            imWriteAddress := commandData(15, 0) // Address in lower 16 bits
            imWriteCount := requestedCount
            
            // Check if IM write count exceeds remaining packet words
            when(requestedCount > (receiveRemainingWords - 1.U)) {
              errorIMWriteCountExceedsPacket := true.B
            }
            
            when(requestedCount > 0.U) {
              receiveState := States.ProcessingIMWrites
            }
          }
          is(2.U) { // Write to register command header
            // Store the register address and transition to ProcessingRegWrite state
            regWriteAddress := commandData(params.regWidth-1, 0)
            receiveState := States.ProcessingRegWrite
          }
        }
      }
      
      bufferedFromNetwork.ready := true.B
    }
    is(States.ProcessingIMWrites) {
      when (bufferedFromNetwork.valid) {
        // Write data to instruction memory
        io.writeControl.valid := true.B
        io.writeControl.bits.mode := ControlWriteMode.InstructionMemory
        io.writeControl.bits.address := imWriteAddress
        io.writeControl.bits.data := bufferedFromNetwork.bits.data
        
        // Update state for next write
        imWriteAddress := imWriteAddress + 1.U
        imWriteCount := imWriteCount - 1.U
        receiveRemainingWords := receiveRemainingWords - 1.U
        
        // Check if we're done with IM writes
        when(imWriteCount === 1.U) {
          // If there are still words in the command packet, go back to ProcessingCommand
          when(receiveRemainingWords > 1.U) {
            receiveState := States.ProcessingCommand
          } .otherwise {
            receiveState := States.Idle
          }
        }
      }
      
      bufferedFromNetwork.ready := true.B
    }
    is(States.ProcessingRegWrite) {
      when (bufferedFromNetwork.valid) {
        // Decode register type from upper 2 bits: 00=A, 01=D, 10=P, 11=G
        val regType = regWriteAddress(params.regWidth-1, params.regWidth-2)
        val regIndex = regWriteAddress(params.regWidth-3, 0)
        
        // Route write based on register type
        switch(regType) {
          is(0.U) { // A registers (00)
            io.result.valid := true.B
            io.result.bits.address.addr := regIndex
            io.result.bits.address.tag := 0.U // Command writes don't use write identifiers
            io.result.bits.value := bufferedFromNetwork.bits.data
            io.result.bits.force := true.B // Command writes bypass dependency system
          }
          is(1.U) { // D registers (01)
            io.result.valid := true.B
            io.result.bits.address.addr := regIndex | (1.U << (params.bRegWidth-1)) // Set D-register bit
            io.result.bits.address.tag := 0.U
            io.result.bits.value := bufferedFromNetwork.bits.data
            io.result.bits.force := true.B
          }
          is(2.U) { // P registers (10)
            io.resultPredicate.valid := true.B
            io.resultPredicate.bits.address.addr := regIndex
            io.resultPredicate.bits.address.tag := 0.U
            io.resultPredicate.bits.value := bufferedFromNetwork.bits.data(0) // P registers are 1-bit
          }
          is(3.U) { // G registers (11)
            io.writeControl.valid := true.B
            io.writeControl.bits.mode := ControlWriteMode.GlobalRegister
            io.writeControl.bits.address := regIndex(params.gRegWidth-1, 0)
            io.writeControl.bits.data := bufferedFromNetwork.bits.data
          }
        }
        
        // Update state
        receiveRemainingWords := receiveRemainingWords - 1.U
        when(receiveRemainingWords === 1.U) {
          receiveState := States.Idle
        } .otherwise {
          receiveState := States.ProcessingCommand
        }
      }
      
      bufferedFromNetwork.ready := true.B
    }
  }
  
}

/**
 * Module generator for ReceivePacketInterface
 */
object ReceivePacketInterfaceGenerator extends fmvpu.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> ReceivePacketInterface <amletParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new ReceivePacketInterface(params)
    }
  }
}
