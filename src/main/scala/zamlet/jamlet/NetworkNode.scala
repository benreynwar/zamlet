package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.LamletParams
import zamlet.utils.{ResetStage, DoubleBuffer}

/**
 * Jamlet Network Node IO
 */
class NetworkNodeIO(params: LamletParams, nChannels: Int) extends Bundle {
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

  // 'Here' interface to/from local jamlet
  val hi = Flipped(Decoupled(new NetworkWord(params)))
  val ho = Decoupled(new NetworkWord(params))

  // Error outputs
  val headerError = Output(Bool())
}

/**
 * Jamlet Network Node Module
 *
 * Handles multiple channels with a single local (hi/ho) connection.
 * nChannels parameter allows reuse for both A and B channel networks.
 */
class NetworkNode(params: LamletParams, nChannels: Int) extends Module {
  val io = IO(new NetworkNodeIO(params, nChannels))

  val resetBuffered = ResetStage(clock, reset)

  withReset(resetBuffered) {

    val hiBuffered = Wire(Decoupled(new NetworkWord(params)))
    val hoBuffered = Wire(Decoupled(new NetworkWord(params)))
    hiBuffered <> DoubleBuffer(io.hi,
      params.networkNodeParams.hiForwardBuffer, params.networkNodeParams.hiBackwardBuffer)
    io.ho <> DoubleBuffer(hoBuffered,
      params.networkNodeParams.hoForwardBuffer, params.networkNodeParams.hoBackwardBuffer)

  
    // Register position inputs
    val thisXReg = RegNext(io.thisX)
    val thisYReg = RegNext(io.thisY)
  
    // Create PacketSwitches for each channel
    val switches = Seq.fill(nChannels)(Module(new PacketSwitch(params)))
  
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
    for (i <- 0 until nChannels) {
      switches(i).io.ni <> io.ni(i)
      switches(i).io.si <> io.si(i)
      switches(i).io.ei <> io.ei(i)
      switches(i).io.wi <> io.wi(i)
      
      io.no(i) <> switches(i).io.no
      io.so(i) <> switches(i).io.so
      io.eo(i) <> switches(i).io.eo
      io.wo(i) <> switches(i).io.wo
    }

    // Connecting to hi - alternate between channels per packet
    val hiChannel = RegInit(0.U(log2Ceil(nChannels).W))
    val hiWordsRemaining = Reg(UInt(4.W))
    val hiHeader = hiBuffered.bits.data.asTypeOf(new PacketHeader(params))

    for (channelIdx <- 0 until nChannels) {
      when (channelIdx.U === hiChannel) {
        switches(channelIdx).io.hi.valid := hiBuffered.valid
        switches(channelIdx).io.hi.bits := hiBuffered.bits
      } .otherwise {
        switches(channelIdx).io.hi.valid := false.B
        switches(channelIdx).io.hi.bits := DontCare
      }
    }
    hiBuffered.ready := MuxLookup(hiChannel, false.B)(
      (0 until nChannels).map(i => i.U -> switches(i).io.hi.ready)
    )
    when (hiBuffered.valid && hiBuffered.ready) {
      when (hiBuffered.bits.isHeader) {
        hiWordsRemaining := hiHeader.length
      } .otherwise {
        hiWordsRemaining := hiWordsRemaining - 1.U
        when (hiWordsRemaining === 1.U) {
          hiChannel := (hiChannel + 1.U) % nChannels.U
        }
      }
      // Handle zero-length packets (header only)
      when (hiBuffered.bits.isHeader && hiHeader.length === 0.U) {
        hiChannel := (hiChannel + 1.U) % nChannels.U
      }
    }

    // Connecting to ho
    
    // Arbitration for outgoing connection (switches -> ho)
    // Default: all switches disconnected from ho
    for (i <- 0 until nChannels) {
      switches(i).io.ho.ready := false.B
    }

    val connstateActive = RegInit(false.B)
    val connstateChannel = Reg(UInt(log2Ceil(nChannels).W))
    val connstateWordsRemaining = Reg(UInt(4.W))

    val nextChannel = PriorityMux(
      (0 until nChannels).map { i =>
        val idx = (connstateChannel + i.U) % nChannels.U
        val switchValid = MuxLookup(idx, false.B)(
          (0 until nChannels).map(j => j.U -> switches(j).io.ho.valid)
        )
        (switchValid, idx)
      }
    )

    val connectedChannel = Wire(UInt(log2Ceil(nChannels).W))
    when (!connstateActive) {
      connectedChannel := nextChannel
    } .otherwise {
      connectedChannel := connstateChannel
    }

    // When no outgoing connection is active, look for valid switches
    for (channelIdx <- 0 until nChannels) {
      when (channelIdx.U === connectedChannel) {
        switches(channelIdx).io.ho.ready := hoBuffered.ready
      } .otherwise {
        switches(channelIdx).io.ho.ready := false.B
      }
    }
    hoBuffered.valid := MuxLookup(connectedChannel, false.B)(
      (0 until nChannels).map(i => i.U -> switches(i).io.ho.valid)
    )
    hoBuffered.bits := MuxLookup(connectedChannel, switches(0).io.ho.bits)(
      (0 until nChannels).map(i => i.U -> switches(i).io.ho.bits)
    )

    val connectedHeader = MuxLookup(connectedChannel, switches(0).io.ho.bits.data)(
      (0 until nChannels).map(i => i.U -> switches(i).io.ho.bits.data)
    ).asTypeOf(new PacketHeader(params))

    val connectedValid = MuxLookup(connectedChannel, false.B)(
      (0 until nChannels).map(i => i.U -> switches(i).io.ho.valid)
    )
    val connectedIsHeader = MuxLookup(connectedChannel, false.B)(
      (0 until nChannels).map(i => i.U -> switches(i).io.ho.bits.isHeader)
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
  }
}

/**
 * Module generator for NetworkNode
 */
object NetworkNodeGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> NetworkNode <jamletParamsFileName>")
      null
    } else {
      val params = LamletParams.fromFile(args(0))
      new NetworkNode(params, params.nAChannels)
    }
  }
}
