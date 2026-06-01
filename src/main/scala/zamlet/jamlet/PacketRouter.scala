package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.network.{MessageType, NetworkWord, PacketHeader}

class PacketRouterErrors extends Bundle {
  val badMessageType = Bool()
}

class PacketRouterIO(params: ZamletParams, nOutputs: Int) extends Bundle {
  val in = Flipped(Decoupled(new NetworkWord(params)))
  val out = Vec(nOutputs, Decoupled(new NetworkWord(params)))
  val errors = Output(new PacketRouterErrors())
}

class PacketRouter(
    params: ZamletParams,
    outputMessageTypes: Seq[Seq[MessageType.Type]]
) extends Module {
  require(outputMessageTypes.nonEmpty, "PacketRouter needs at least one output")

  val io = IO(new PacketRouterIO(params, outputMessageTypes.length))

  val routeWidth = log2Ceil(outputMessageTypes.length).max(1)
  val header = io.in.bits.data.asTypeOf(new PacketHeader(params))
  val bodyWordsRemaining = RegInit(0.U(params.messageLengthWidth.W))
  val savedRoute = RegInit(0.U(routeWidth.W))
  val savedRouteValid = RegInit(false.B)

  val routeMatches = VecInit(outputMessageTypes.map { messageTypes =>
    if (messageTypes.isEmpty) {
      false.B
    } else {
      messageTypes.map(header.messageType === _).reduce(_ || _)
    }
  })
  val headerRoute = PriorityEncoder(routeMatches)
  val headerRouteValid = routeMatches.asUInt.orR
  val inHeader = bodyWordsRemaining === 0.U
  val route = Mux(inHeader, headerRoute, savedRoute)
  val routeValid = Mux(inHeader, headerRouteValid, savedRouteValid)
  val badHeader = io.in.valid && inHeader && !headerRouteValid
  val errorsNext = Wire(new PacketRouterErrors())

  errorsNext.badMessageType := badHeader
  io.errors := RegNext(errorsNext)
  io.in.ready := Mux(routeValid, io.out(route).ready, true.B)

  for (i <- outputMessageTypes.indices) {
    io.out(i).valid := io.in.valid && routeValid && route === i.U
    io.out(i).bits := io.in.bits
  }

  when(io.in.fire) {
    when(inHeader) {
      savedRoute := headerRoute
      savedRouteValid := headerRouteValid
      bodyWordsRemaining := header.length
    } .otherwise {
      bodyWordsRemaining := bodyWordsRemaining - 1.U
    }
  }
}
