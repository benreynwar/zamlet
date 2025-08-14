package zamlet.amlet

import chisel3._
import chisel3.util._
import zamlet.utils._


/**
 * Send Packet Interface IO
 */
class SendPacketInterfaceIO(params: AmletParams) extends Bundle {

  // Network interface
  val toNetwork = Decoupled(new FromHereNetworkWord(params))
  
  // Instruction interface
  val instr = Flipped(Decoupled(new PacketInstr.SendResolved(params)))

  // Write inputs for packet data
  val writeInputs = Input(Vec(params.nResultPorts, Valid(new WriteResult(params))))

  // Error outputs
  val errors = Output(new SendPacketInterfaceErrors)
}

/**
 * Error outputs for SendPacketInterface
 */
class SendPacketInterfaceErrors extends Bundle {
  // Add error signals as needed
}

/**
 * Send Packet Interface Module
 * Handles packet send operations
 */
class SendPacketInterface(params: AmletParams) extends Module {
  val io = IO(new SendPacketInterfaceIO(params))
  
  val resetBuffered = ResetStage(clock, reset)

  withReset(resetBuffered) {
  
    // Packet buffer for storing payload data to the sent.
    // ---------------------------------------------------
    // Packets are populated by writing to register 0.
    // We monitor the write bus for writes to this register.
    // When we see them we place them in this packetOutBuffer.
    // write ident are guaranteed to be in consecutive order when writing to register 0.
    // The order we receive the writes in is not necssarily the correct order however
    // we can work out the correct order by looking at the write idents.
    // We store them in this buffer by write ident and then read them out in order.

    val packetOutBuffer = RegInit(VecInit(Seq.fill(params.nPacketOutIdents){
      val init = Wire(Valid(UInt(params.width.W)))
      init.valid := false.B
      init.bits := 0.U
      init
    }))
    // The next write ident that we should read from the packetOutBuffer
    val packetOutReadPtr = RegInit(1.U(log2Ceil(params.nPacketOutIdents).W))
    // Handle writes to packet output register (register 0)
    for (i <- 0 until params.nResultPorts) {
      when(io.writeInputs(i).valid && 
           io.writeInputs(i).bits.address.addr === 0.U && 
           !io.writeInputs(i).bits.force &&
           io.writeInputs(i).bits.predicate) {
        val writeIdent = io.writeInputs(i).bits.address.tag
        packetOutBuffer(writeIdent).valid := true.B
        packetOutBuffer(writeIdent).bits := io.writeInputs(i).bits.value
      }
    }

    // A stream of ordered data from the packet buffer that can be added to a packet.
    val packetOut = Wire(Decoupled(UInt(params.width.W)))
    packetOut.valid := packetOutBuffer(packetOutReadPtr).valid
    packetOut.bits := packetOutBuffer(packetOutReadPtr).bits

    // Update the state of the packet buffer when we read data.
    when (packetOut.valid && packetOut.ready) {
      packetOutBuffer(packetOutReadPtr).valid := false.B
      packetOutReadPtr := packetOutReadPtr + 1.U
    }
    
    // Buffer instructions and data to the network
    // ------------------------------------------------------

    val bufferedInstr = Wire(Decoupled(new PacketInstr.SendResolved(params)))
    val bufferInstr = Module(new DoubleBuffer(new PacketInstr.SendResolved(params)))
    bufferInstr.io.i <> io.instr
    bufferInstr.io.o <> bufferedInstr

    val bufferedToNetwork = Wire(Decoupled(new FromHereNetworkWord(params)))
    val bufferToNetwork = Module(new DoubleBuffer(new FromHereNetworkWord(params)))
    bufferToNetwork.io.i <> bufferedToNetwork
    bufferToNetwork.io.o <> io.toNetwork

    // Process the instructions
    // ------------------------

    object States extends ChiselEnum {
      val Idle = Value(0.U)
      val SendingHeader = Value(1.U)
      val SendingData = Value(2.U)
    }
    
    // Send state
    val sendState = RegInit(States.Idle)
    // How many payload words are left to send
    val sendRemainingWords = RegInit(0.U(8.W))
    val sendInstruction = Reg(new PacketInstr.SendResolved(params))


    // Send the packet to the network
    // ------------------------------
    
    bufferedToNetwork.bits.channel := sendInstruction.channel

    // default values
    packetOut.ready := false.B
    bufferedToNetwork.valid := false.B
    bufferedToNetwork.bits := DontCare
    bufferedInstr.ready := false.B

    switch(sendState) {
      is (States.Idle) {
        bufferedInstr.ready := true.B
        when(bufferedInstr.valid && bufferedInstr.bits.predicate) {
          sendState := States.SendingHeader
          sendRemainingWords := bufferedInstr.bits.length
          sendInstruction := bufferedInstr.bits
        }
      }
      is(States.SendingHeader) {
        // Create and send packet header
        val header = Wire(new PacketHeader(params))
        header.length := sendRemainingWords
        header.xDest := sendInstruction.xTarget
        header.yDest := sendInstruction.yTarget
        header.mode := MuxLookup(sendInstruction.mode.asUInt, PacketHeaderModes.Normal)(Seq(
          PacketInstr.Modes.Send.asUInt -> PacketHeaderModes.Command,
          PacketInstr.Modes.ForwardAndAppend.asUInt -> PacketHeaderModes.Append,
          PacketInstr.Modes.ReceiveForwardAndAppend.asUInt -> PacketHeaderModes.Append
        ))
        header.forward := (sendInstruction.mode === PacketInstr.Modes.SendAndForwardAgain)
        header.isBroadcast := sendInstruction.mode === PacketInstr.Modes.Broadcast
        header.appendLength := sendInstruction.appendLength
        
        bufferedToNetwork.valid := true.B
        bufferedToNetwork.bits.data := header.asUInt
        bufferedToNetwork.bits.isHeader := true.B
        
        when(bufferedToNetwork.ready) {
          sendState := States.SendingData
        }
      }

      is(States.SendingData) {
        packetOut.ready := (sendRemainingWords > 0.U) && bufferedToNetwork.ready
        // Send packet data from buffer
        bufferedToNetwork.valid := packetOut.valid && (sendRemainingWords > 0.U)
        bufferedToNetwork.bits.data := packetOut.bits
        bufferedToNetwork.bits.isHeader := false.B

        when(packetOut.valid && packetOut.ready) {
          sendRemainingWords := sendRemainingWords - 1.U
          when(sendRemainingWords === 1.U) {
            sendState := States.Idle
          }
        }
      }
    }
  }
}

/**
 * Module generator for SendPacketInterface
 */
object SendPacketInterfaceGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> SendPacketInterface <amletParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new SendPacketInterface(params)
    }
  }
}
