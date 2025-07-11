package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Connection state bundle
 */
class ConnectionState(params: LaneParams) extends Bundle {
  val active = Bool()
  val channel = UInt(log2Ceil(params.nChannels).W)
  val remainingWords = UInt(8.W)
}

/**
 * Lane Network Node IO
 */
class LaneNetworkNodeIO(params: LaneParams) extends Bundle {
  val nChannels = params.nChannels
  
  // Current position
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
  
  // 'Here' interface to/from local lane
  val hi = Flipped(Decoupled(new NetworkWord(params)))
  val ho = Decoupled(new NetworkWord(params))
  
  // Forward interface
  val forward = Flipped(Decoupled(new PacketForward(params)))
  
  // Error outputs
  val headerError = Output(Bool())
}

/**
 * Lane Network Node Module
 */
class LaneNetworkNode(params: LaneParams) extends Module {
  val io = IO(new LaneNetworkNodeIO(params))
  
  // Create PacketSwitches for each channel
  val switches = Seq.fill(params.nChannels)(Module(new PacketSwitch(params)))
  
  // Connect position inputs to all switches
  switches.foreach { switch =>
    switch.io.thisX := io.thisX
    switch.io.thisY := io.thisY
  }
  
  // Connection state as specified in network_node.txt
  val connectionIn = RegInit(0.U.asTypeOf(new ConnectionState(params)))
  val connectionOut = RegInit(0.U.asTypeOf(new ConnectionState(params)))
  
  // Default outputs
  io.headerError := false.B
  io.hi.ready := false.B
  io.ho.valid := false.B
  io.ho.bits := DontCare
  
  // Connect network interfaces directly to switches
  for (i <- 0 until params.nChannels) {
    switches(i).io.ni <> io.ni(i)
    switches(i).io.si <> io.si(i)
    switches(i).io.ei <> io.ei(i)
    switches(i).io.wi <> io.wi(i)
    
    io.no(i) <> switches(i).io.no
    io.so(i) <> switches(i).io.so
    io.eo(i) <> switches(i).io.eo
    io.wo(i) <> switches(i).io.wo
  }
  
  // Arbitration for incoming connection (hi -> switches)
  // Default: all switches disconnected from hi
  for (i <- 0 until params.nChannels) {
    switches(i).io.hi.valid := false.B
    switches(i).io.hi.bits := DontCare
  }
  
  // When no connection is active, look for ready switches with priority arbitration
  when (!connectionIn.active) {
    val startIdx = Mux(connectionIn.channel === (params.nChannels-1).U, 0.U, connectionIn.channel + 1.U)
    val readyMask = VecInit(switches.map(_.io.hi.ready))
    val anyReady = readyMask.asUInt.orR
    
    when (anyReady && io.hi.valid) {
      // Find next ready channel starting from startIdx
      val nextChannel = PriorityMux(
        (0 until params.nChannels).map { i =>
          val idx = (startIdx + i.U) % params.nChannels.U
          (readyMask(idx), idx)
        }
      )
      connectionIn.active := true.B
      connectionIn.channel := nextChannel
      // Extract packet length from header when isHeader is true
      val header = io.hi.bits.data.asTypeOf(new PacketHeader(params))
      connectionIn.remainingWords := Mux(io.hi.bits.isHeader, header.length, 1.U)
      
      // Signal error if first word is not a header
      io.headerError := !io.hi.bits.isHeader
    }
  }
  
  // Route hi to switches based on connection state
  for (i <- 0 until params.nChannels) {
    when (connectionIn.active && connectionIn.channel === i.U) {
      switches(i).io.hi <> io.hi
    } .otherwise {
      switches(i).io.hi.valid := false.B
      switches(i).io.hi.bits := DontCare
    }
  }
  
  // Set hi.ready when no connection is active
  when (!connectionIn.active) {
    io.hi.ready := false.B
  }
  
  // Count down remaining words when connection is active
  when (connectionIn.active && io.hi.fire) {
    connectionIn.remainingWords := connectionIn.remainingWords - 1.U
    when (connectionIn.remainingWords === 1.U) {
      connectionIn.active := false.B
    }
  }
  
  // Arbitration for outgoing connection (switches -> ho)
  // Default: all switches disconnected from ho
  for (i <- 0 until params.nChannels) {
    switches(i).io.ho.ready := false.B
  }
  
  // When no outgoing connection is active, look for valid switches
  when (!connectionOut.active) {
    val startIdx = Mux(connectionOut.channel === (params.nChannels-1).U, 0.U, connectionOut.channel + 1.U)
    val validMask = VecInit(switches.map(_.io.ho.valid))
    val anyValid = validMask.asUInt.orR
    
    when (anyValid && io.ho.ready) {
      // Find next valid channel starting from startIdx
      val nextChannel = PriorityMux(
        (0 until params.nChannels).map { i =>
          val idx = (startIdx + i.U) % params.nChannels.U
          (validMask(idx), idx)
        }
      )
      connectionOut.active := true.B
      connectionOut.channel := nextChannel
      // Extract packet length from header - use MuxLookup to get the right switch
      val selectedSwitchBits = MuxLookup(nextChannel, switches(0).io.ho.bits)(
        (0 until params.nChannels).map(i => i.U -> switches(i).io.ho.bits)
      )
      val header = selectedSwitchBits.data.asTypeOf(new PacketHeader(params))
      connectionOut.remainingWords := Mux(selectedSwitchBits.isHeader, header.length, 1.U)
    }
  }
  
  // Route switches to ho based on connection state
  for (i <- 0 until params.nChannels) {
    when (connectionOut.active && connectionOut.channel === i.U) {
      io.ho <> switches(i).io.ho
    } .otherwise {
      switches(i).io.ho.ready := false.B
    }
  }
  
  // Set ho outputs when no connection is active
  when (!connectionOut.active) {
    io.ho.valid := false.B
    io.ho.bits := DontCare
  }
  
  // Count down remaining words when connection is active
  when (connectionOut.active && io.ho.fire) {
    connectionOut.remainingWords := connectionOut.remainingWords - 1.U
    when (connectionOut.remainingWords === 1.U) {
      connectionOut.active := false.B
    }
  }
  
  // Connect forward to all switches
  switches.foreach { switch =>
    switch.io.forward.valid := io.forward.valid
    switch.io.forward.bits := io.forward.bits
  }
  
  // Forward ready is OR of all switch ready signals
  io.forward.ready := switches.map(_.io.forward.ready).reduce(_ || _)
}

/**
 * Module generator for LaneNetworkNode
 */
object LaneNetworkNodeGenerator extends fmvpu.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> LaneNetworkNode <laneParamsFileName>")
      null
    } else {
      val params = LaneParams.fromFile(args(0))
      new LaneNetworkNode(params)
    }
  }
}