package zamlet.network

import chisel3._
import chisel3.util._
import zamlet.{MessageTypePacketRouterParams, ZamletParams}
import zamlet.utils.DoubleBuffer

class MessageTypePacketRouterErrors extends Bundle {
  val noRoute = Bool()
  val idleBody = Bool()
  val activeHeader = Bool()
}

class MessageTypePacketRouterIO(params: ZamletParams, nOutputs: Int) extends Bundle {
  val in = Flipped(Decoupled(new NetworkWord(params)))
  val out = Vec(nOutputs, Decoupled(new NetworkWord(params)))
  val errors = Output(new MessageTypePacketRouterErrors)
}

class MessageTypePacketRouterState(outputWidth: Int) extends Bundle {
  val active = Bool()
  val drop = Bool()
  val output = UInt(outputWidth.W)
  val remaining = UInt(PacketConstants.lengthWidth)
}

class MessageTypePacketRouter(
  params: ZamletParams,
  routes: Seq[Seq[MessageType.Type]],
  routerParams: MessageTypePacketRouterParams = MessageTypePacketRouterParams(),
) extends Module {
  require(routes.nonEmpty)

  private val nOutputs = routes.length
  private val outputWidth = log2Ceil(nOutputs)

  val io = IO(new MessageTypePacketRouterIO(params, nOutputs))

  val route0StateInitial = 0.U.asTypeOf(new MessageTypePacketRouterState(outputWidth))
  val route0StateNext = Wire(new MessageTypePacketRouterState(outputWidth))
  val route0State = RegEnable(route0StateNext, route0StateInitial, true.B)
  route0StateNext := route0State

  val errors = Wire(new MessageTypePacketRouterErrors)
  errors := 0.U.asTypeOf(new MessageTypePacketRouterErrors)
  io.errors := RegNext(errors)

  val route0In = DoubleBuffer(io.in, routerParams.inputFB, routerParams.inputBB)
  val route0Out = Seq.tabulate(nOutputs) { output =>
    val out = Wire(Decoupled(new NetworkWord(params)))
    io.out(output) <> DoubleBuffer(out, routerParams.outputFB, routerParams.outputBB)
    out
  }

  val route0Header = route0In.bits.data.asTypeOf(new PacketHeader(params))
  val route0Matches = VecInit(routes.map { route =>
    route.map(messageType => route0Header.messageType === messageType)
      .foldLeft(false.B)(_ || _)
  })
  val route0HasMatch = route0Matches.asUInt.orR
  val route0HeaderHasMatch = route0In.bits.isHeader && route0HasMatch
  val route0MatchedOutput = PriorityEncoder(route0Matches)
  val route0OutputIndex =
    Mux(route0State.active, route0State.output, route0MatchedOutput)
  val route0OutputReady = MuxLookup(route0OutputIndex, false.B)(
    (0 until nOutputs).map { output =>
      output.U -> route0Out(output).ready
    })

  for (output <- 0 until nOutputs) {
    route0Out(output).valid :=
      route0In.valid &&
        !route0State.drop &&
        route0OutputIndex === output.U &&
        (route0State.active || route0HeaderHasMatch)
    route0Out(output).bits := route0In.bits
  }

  route0In.ready := Mux(
    route0State.drop,
    true.B,
    Mux(route0State.active || route0HeaderHasMatch, route0OutputReady, true.B))

  errors.noRoute :=
    route0In.fire && !route0State.active && route0In.bits.isHeader && !route0HasMatch
  errors.idleBody :=
    route0In.fire && !route0State.active && !route0In.bits.isHeader
  errors.activeHeader :=
    route0In.fire && route0State.active && route0In.bits.isHeader

  when (route0In.fire) {
    when (route0State.active) {
      route0StateNext.remaining := route0State.remaining - 1.U
      when (route0State.remaining === 1.U) {
        route0StateNext.active := false.B
        route0StateNext.drop := false.B
      }
    } .elsewhen (route0In.bits.isHeader && route0Header.length =/= 0.U) {
      route0StateNext.active := true.B
      route0StateNext.drop := !route0HasMatch
      route0StateNext.output := route0MatchedOutput
      route0StateNext.remaining := route0Header.length
    }
  }
}
