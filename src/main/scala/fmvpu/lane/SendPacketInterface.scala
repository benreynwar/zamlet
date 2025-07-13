package fmvpu.lane

import chisel3._
import chisel3.util._
import fmvpu.utils._


/**
 * Send Packet Interface IO
 */
class SendPacketInterfaceIO(params: LaneParams) extends Bundle {
  // Network interface
  val toNetwork = Decoupled(new NetworkWord(params))
  val toNetworkChannel = Output(UInt(log2Ceil(params.nChannels).W))
  
  // Instruction interface
  val instr = Flipped(Decoupled(new PacketInstrResolved(params)))

  // Write inputs for packet data
  val writeInputs = Input(Vec(params.nWritePorts, new WriteResult(params)))

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
class SendPacketInterface(params: LaneParams) extends Module {
  val io = IO(new SendPacketInterfaceIO(params))
  
  /**
   * Packet interface send states
   */
  object States extends ChiselEnum {
    val Idle = Value(0.U)
    val SendingHeader = Value(1.U)
    val SendingData = Value(2.U)
  }
  
  // Packet buffer for out-of-order sends
  val packetOutBuffer = RegInit(VecInit(Seq.fill(params.nPacketOutIdents){
    val init = Wire(Valid(UInt(params.width.W)))
    init.valid := false.B
    init.bits := 0.U
    init
  }))
  val packetOutReadPtr = RegInit(1.U(log2Ceil(params.nPacketOutIdents).W))
  
  // Send state
  val sendState = RegInit(States.Idle)
  val sendRemainingWords = RegInit(0.U(8.W))
  val sendChannel = RegInit(0.U(log2Ceil(params.nChannels).W))
  val sendX = RegInit(0.U(params.xPosWidth.W))
  val sendY = RegInit(0.U(params.yPosWidth.W))
  
  // Buffer send instructions
  val bufferedInstr = Wire(Decoupled(new PacketInstrResolved(params)))
  val bufferInstr = Module(new DoubleBuffer(new PacketInstrResolved(params)))
  bufferInstr.io.i <> io.instr
  bufferInstr.io.o <> bufferedInstr

  // Buffer network output
  val bufferedToNetwork = Wire(Decoupled(new NetworkWord(params)))
  val bufferToNetwork = Module(new DoubleBuffer(new NetworkWord(params)))
  bufferToNetwork.io.i <> bufferedToNetwork
  bufferToNetwork.io.o <> io.toNetwork

  // Default ready signals for buffered interfaces
  bufferedInstr.ready := false.B
  bufferedToNetwork.valid := false.B
  bufferedToNetwork.bits := DontCare
  
  
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
  when(bufferedInstr.valid) {
    bufferedInstr.ready := true.B  // Consume the instruction
    sendState := States.SendingHeader
    sendRemainingWords := bufferedInstr.bits.sendLength
    sendChannel := bufferedInstr.bits.channel
    sendX := bufferedInstr.bits.xTarget
    sendY := bufferedInstr.bits.yTarget
  }
  
  // Send state machine
  io.toNetworkChannel := sendChannel
  switch(sendState) {
    is(States.SendingHeader) {
      // Create and send packet header
      val header = Wire(new PacketHeader(params))
      header.length := sendRemainingWords
      header.xDest := sendX
      header.yDest := sendY
      header.mode := PacketHeaderModes.Normal
      header.forward := false.B
      header.isBroadcast := false.B
      header.broadcastDirection := BroadcastDirections.NE
      
      bufferedToNetwork.valid := true.B
      bufferedToNetwork.bits.data := header.asUInt
      bufferedToNetwork.bits.isHeader := true.B
      
      when(bufferedToNetwork.ready) {
        sendState := States.SendingData
      }
    }
    
    is(States.SendingData) {
      // Send packet data from buffer
      when(packetOutBuffer(packetOutReadPtr).valid && sendRemainingWords > 0.U) {
        bufferedToNetwork.valid := true.B
        bufferedToNetwork.bits.data := packetOutBuffer(packetOutReadPtr).bits
        bufferedToNetwork.bits.isHeader := false.B
        
        when(bufferedToNetwork.ready) {
          packetOutBuffer(packetOutReadPtr).valid := false.B
          packetOutReadPtr := packetOutReadPtr + 1.U
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
object SendPacketInterfaceGenerator extends fmvpu.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> SendPacketInterface <laneParamsFileName>")
      null
    } else {
      val params = LaneParams.fromFile(args(0))
      new SendPacketInterface(params)
    }
  }
}
