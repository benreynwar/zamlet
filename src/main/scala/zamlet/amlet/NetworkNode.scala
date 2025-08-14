package zamlet.amlet

import chisel3._
import chisel3.util._
import zamlet.utils.{ResetStage, DoubleBuffer}

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

  val resetBuffered = ResetStage(clock, reset)

  withReset(resetBuffered) {

    val hiBuffered = Wire(Decoupled(new FromHereNetworkWord(params)))
    val hoBuffered = Wire(Decoupled(new NetworkWord(params)))
    hiBuffered <> DoubleBuffer(io.hi, params.networkNodeParams.hiForwardBuffer, params.networkNodeParams.hiBackwardBuffer)
    io.ho <> DoubleBuffer(hoBuffered, params.networkNodeParams.hoForwardBuffer, params.networkNodeParams.hoBackwardBuffer)

  
    // Register position inputs
    val thisXReg = RegNext(io.thisX)
    val thisYReg = RegNext(io.thisY)
  
    // Create PacketSwitches for each channel
    val switches = Seq.fill(params.nChannels)(Module(new PacketSwitch(params)))
  
    // Connect registered position inputs to all switches
    switches.foreach { switch =>
      switch.io.thisX := thisXReg
      switch.io.thisY := thisYReg
    }
    
    // Default outputs
    io.headerError := false.B
    hiBuffered.ready := false.B
    hoBuffered.valid := false.B
    hoBuffered.bits := DontCare
    
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
      when (channelIdx.U === hiBuffered.bits.channel) {
        switches(channelIdx).io.hi.valid := hiBuffered.valid
        switches(channelIdx).io.hi.bits := hiBuffered.bits
      } .otherwise {
        switches(channelIdx).io.hi.valid := false.B
        switches(channelIdx).io.hi.bits := DontCare
      }
    }
    hiBuffered.ready := MuxLookup(io.hi.bits.channel, false.B)(
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
        switches(channelIdx).io.ho.ready := hoBuffered.ready
      } .otherwise {
        switches(channelIdx).io.ho.ready := false.B
      }
    }
    hoBuffered.valid := MuxLookup(connectedChannel, false.B)(
      (0 until params.nChannels).map(i => i.U -> switches(i).io.ho.valid)
    )
    hoBuffered.bits := MuxLookup(connectedChannel, switches(0).io.ho.bits)(
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
        when (hoBuffered.ready) {
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
