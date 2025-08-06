package zamlet.amlet

import chisel3._
import chisel3.util._

/**
 * Connection state bundle
 */
class ConnectionState(params: AmletParams) extends Bundle {
  val active = Bool()
  val channel = UInt(log2Ceil(params.nChannels).W)
  val remainingWords = UInt(8.W)
}

/**
 * Amlet Network Node IO
 */
class NetworkNodeIO(params: AmletParams) extends Bundle {
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
  
  // 'Here' interface to/from local amlet
  val hi = Flipped(Decoupled(new FromHereNetworkWord(params)))
  val ho = Decoupled(new NetworkWord(params))
  
  // Forward interface
  val forward = Flipped(Valid(new PacketForward(params)))
  
  // Error outputs
  val headerError = Output(Bool())
}

/**
 * Amlet Network Node Module
 */
class NetworkNode(params: AmletParams) extends Module {
  val io = IO(new NetworkNodeIO(params))
  
  // Create PacketSwitches for each channel
  val switches = Seq.fill(params.nChannels)(Module(new PacketSwitch(params)))
  
  // Connect position inputs to all switches
  switches.foreach { switch =>
    switch.io.thisX := io.thisX
    switch.io.thisY := io.thisY
  }
  
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

  // Connecting to hi.
  for (channelIdx <- 0 until params.nChannels) {
    when (channelIdx.U === io.hi.bits.channel) {
      switches(channelIdx).io.hi.valid := io.hi.valid
      switches(channelIdx).io.hi.bits := io.hi.bits
    } .otherwise {
      switches(channelIdx).io.hi.valid := false.B
      switches(channelIdx).io.hi.bits := DontCare
    }
  }
  io.hi.ready := MuxLookup(io.hi.bits.channel, false.B)(
    (0 until params.nChannels).map(i => i.U -> switches(i).io.hi.ready)
  )

  // Connecting to ho
  
  // Arbitration for outgoing connection (switches -> ho)
  // Default: all switches disconnected from ho
  for (i <- 0 until params.nChannels) {
    switches(i).io.ho.ready := false.B
  }

  val connstateActive = RegInit(false.B)
  val connstateChannel = Reg(UInt(log2Ceil(params.nChannels).W))
  val connstateWordsRemaining = Reg(UInt(params.packetLengthWidth.W))
  
  val nextChannel = PriorityMux(
    (0 until params.nChannels).map { i =>
      val idx = (connstateChannel + i.U) % params.nChannels.U
      val switchValid = MuxLookup(idx, false.B)(
        (0 until params.nChannels).map(j => j.U -> switches(j).io.ho.valid)
      )
      (switchValid, idx)
    }
  )

  val connectedChannel = Wire(UInt(log2Ceil(params.nChannels).W))
  when (!connstateActive) {
    connectedChannel := nextChannel
  } .otherwise {
    connectedChannel := connstateChannel
  }

  // When no outgoing connection is active, look for valid switches
  for (channelIdx <- 0 until params.nChannels) {
    when (channelIdx.U === connectedChannel) {
      switches(channelIdx).io.ho.ready := io.ho.ready
    } .otherwise {
      switches(channelIdx).io.ho.ready := false.B
    }
  }
  io.ho.valid := MuxLookup(connectedChannel, false.B)(
    (0 until params.nChannels).map(i => i.U -> switches(i).io.ho.valid)
  )
  io.ho.bits := MuxLookup(connectedChannel, switches(0).io.ho.bits)(
    (0 until params.nChannels).map(i => i.U -> switches(i).io.ho.bits)
  )

  val connectedHeader = MuxLookup(connectedChannel, switches(0).io.ho.bits.data)(
    (0 until params.nChannels).map(i => i.U -> switches(i).io.ho.bits.data)
  ).asTypeOf(new PacketHeader(params))

  val connectedValid = MuxLookup(connectedChannel, false.B)(
    (0 until params.nChannels).map(i => i.U -> switches(i).io.ho.valid)
  )
  val connectedIsHeader = MuxLookup(connectedChannel, false.B)(
    (0 until params.nChannels).map(i => i.U -> switches(i).io.ho.bits.isHeader)
  )

  when (connectedValid) {
    when (connectedIsHeader) {
      io.headerError := connstateActive
      connstateWordsRemaining := connectedHeader.length
      when (connectedHeader.length > 0.U) {
        connstateActive := true.B
      } .otherwise {
        connstateActive := false.B
      }
    } .otherwise {
      io.headerError := !connstateActive
      when (io.ho.ready) {
        connstateWordsRemaining := connstateWordsRemaining - 1.U
      }
      when (connstateWordsRemaining === 1.U) {
        connstateActive := false.B
      }
    }
  }
  
  // Connect forward to all switches
  switches.foreach { switch =>
    switch.io.forward.valid := io.forward.valid
    switch.io.forward.bits := io.forward.bits
  }
}

/**
 * Module generator for NetworkNode
 */
object NetworkNodeGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> NetworkNode <amletParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new NetworkNode(params)
    }
  }
}