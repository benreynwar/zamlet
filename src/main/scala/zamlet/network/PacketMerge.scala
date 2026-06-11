package zamlet.network

import chisel3._
import chisel3.util._
import zamlet.{PacketMergeParams, ZamletParams}
import zamlet.utils.DoubleBuffer

class PacketMergeErrors extends Bundle {
  val idleBody = Bool()
  val activeHeader = Bool()
}

class PacketMergeIO(params: ZamletParams, nInputs: Int) extends Bundle {
  val in = Vec(nInputs, Flipped(Decoupled(new NetworkWord(params))))
  val out = Decoupled(new NetworkWord(params))
  val errors = Output(new PacketMergeErrors)
}

class PacketMergeState(inputWidth: Int) extends Bundle {
  val active = Bool()
  val input = UInt(inputWidth.W)
  val remaining = UInt(PacketConstants.lengthWidth)
}

/**
 * Fixed-priority merge for packet streams.
 *
 * A selected input owns the output until the full packet has passed, so header
 * and body words from different inputs are never interleaved.
 */
class PacketMerge(
  params: ZamletParams,
  nInputs: Int,
  mergeParams: PacketMergeParams = PacketMergeParams(),
) extends Module {
  require(nInputs > 0)

  private val inputWidth = log2Ceil(nInputs)

  val io = IO(new PacketMergeIO(params, nInputs))

  val merge0StateInitial = 0.U.asTypeOf(new PacketMergeState(inputWidth))
  val merge0StateNext = Wire(new PacketMergeState(inputWidth))
  val merge0State = RegEnable(merge0StateNext, merge0StateInitial, true.B)
  merge0StateNext := merge0State

  val errors = Wire(new PacketMergeErrors)
  errors := 0.U.asTypeOf(new PacketMergeErrors)
  io.errors := RegNext(errors)

  val merge0In = Seq.tabulate(nInputs) { input =>
    DoubleBuffer(io.in(input), mergeParams.inputFB, mergeParams.inputBB)
  }
  val merge0Out = Wire(Decoupled(new NetworkWord(params)))
  io.out <> DoubleBuffer(merge0Out, mergeParams.outputFB, mergeParams.outputBB)

  val merge0ValidInputs = VecInit(merge0In.map(_.valid))
  val merge0PriorityInput = PriorityEncoder(merge0ValidInputs)
  val merge0InputIndex =
    Mux(merge0State.active, merge0State.input, merge0PriorityInput)
  val merge0InputValid = MuxLookup(merge0InputIndex, false.B)(
    (0 until nInputs).map { input =>
      input.U -> merge0In(input).valid
    })
  val merge0InputBits = MuxLookup(merge0InputIndex, 0.U.asTypeOf(new NetworkWord(params)))(
    (0 until nInputs).map { input =>
      input.U -> merge0In(input).bits
    })
  val merge0Header = merge0InputBits.data.asTypeOf(new PacketHeader(params))

  merge0Out.valid := merge0InputValid
  merge0Out.bits := merge0InputBits

  for (input <- 0 until nInputs) {
    merge0In(input).ready := merge0Out.ready && input.U === merge0InputIndex
  }

  errors.idleBody :=
    merge0Out.fire && !merge0State.active && !merge0InputBits.isHeader
  errors.activeHeader :=
    merge0Out.fire && merge0State.active && merge0InputBits.isHeader

  when (merge0Out.fire) {
    when (merge0State.active) {
      merge0StateNext.remaining := merge0State.remaining - 1.U
      when (merge0State.remaining === 1.U) {
        merge0StateNext.active := false.B
      }
    } .elsewhen (merge0InputBits.isHeader && merge0Header.length =/= 0.U) {
      merge0StateNext.active := true.B
      merge0StateNext.input := merge0InputIndex
      merge0StateNext.remaining := merge0Header.length
    }
  }
}
