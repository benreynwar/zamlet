package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.LamletParams

/**
 * Simple round-robin arbiter for packet sources.
 *
 * Arbitrates between multiple Decoupled packet sources, outputting complete packets
 * (header + payload words) without interleaving.
 */
class PacketArbiter(params: LamletParams, nInputs: Int) extends Module {
  val io = IO(new Bundle {
    val in = Vec(nInputs, Flipped(Decoupled(new NetworkWord(params))))
    val out = Decoupled(new NetworkWord(params))
  })

  // Track which input is currently sending a packet
  val activeInput = RegInit(0.U(log2Ceil(nInputs).W))
  val inPacket = RegInit(false.B)
  val wordsRemaining = Reg(UInt(4.W))

  // Round-robin priority starting from last served + 1
  val nextPriority = RegInit(0.U(log2Ceil(nInputs).W))

  // Find next valid input with round-robin priority
  val validInputs = VecInit(io.in.map(_.valid))

  // Rotate valid bits so that nextPriority is at position 0
  val rotatedValid = Wire(Vec(nInputs, Bool()))
  for (i <- 0 until nInputs) {
    val srcIdx = (i.U +& nextPriority)(log2Ceil(nInputs) - 1, 0)
    rotatedValid(i) := validInputs(srcIdx)
  }

  // Priority encode the rotated valids
  val rotatedSelect = PriorityEncoder(rotatedValid.asUInt)
  val found = rotatedValid.asUInt.orR

  // Rotate back to get actual input index
  val selectedInput = ((rotatedSelect +& nextPriority) % nInputs.U)(log2Ceil(nInputs) - 1, 0)

  // Default: no transfer
  io.out.valid := false.B
  io.out.bits := DontCare
  for (i <- 0 until nInputs) {
    io.in(i).ready := false.B
  }

  when(inPacket) {
    // Continue current packet
    io.out.valid := io.in(activeInput).valid
    io.out.bits := io.in(activeInput).bits
    io.in(activeInput).ready := io.out.ready

    when(io.out.fire) {
      wordsRemaining := wordsRemaining - 1.U
      when(wordsRemaining === 1.U) {
        inPacket := false.B
        nextPriority := ((activeInput +& 1.U) % nInputs.U)(log2Ceil(nInputs) - 1, 0)
      }
    }
  }.otherwise {
    // Look for new packet (header)
    when(found) {
      io.out.valid := io.in(selectedInput).valid
      io.out.bits := io.in(selectedInput).bits
      io.in(selectedInput).ready := io.out.ready

      when(io.out.fire && io.in(selectedInput).bits.isHeader) {
        val header = io.in(selectedInput).bits.data.asTypeOf(new PacketHeader(params))
        activeInput := selectedInput
        wordsRemaining := header.length - 1.U
        when(header.length > 1.U) {
          inPacket := true.B
        }.otherwise {
          // Single-word packet, update priority immediately
          nextPriority := ((selectedInput +& 1.U) % nInputs.U)(log2Ceil(nInputs) - 1, 0)
        }
      }
    }
  }
}

object PacketArbiterGenerator extends zamlet.ModuleGenerator with App {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 2) {
      println("Usage: <configFile> <nInputs>")
      System.exit(1)
    }
    val params = LamletParams.fromFile(args(0))
    val nInputs = args(1).toInt
    new PacketArbiter(params, nInputs)
  }

  generate(args(0), args.drop(1))
}
