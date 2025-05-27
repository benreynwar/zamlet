package fvpu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import chisel3.util.DecoupledIO
import chisel3.util.Queue

import scala.io.Source

import fvpu.ModuleGenerator

object NetworkDirection extends ChiselEnum {
  val north, south, west, east = Value

  def nextDirection(current: NetworkDirection.Type): NetworkDirection.Type = {
    val result = Wire(NetworkDirection())
    when (current === NetworkDirection.north) {
      result := NetworkDirection.south
    }.elsewhen (current === NetworkDirection.south) {
      result := NetworkDirection.west
    }.elsewhen (current === NetworkDirection.west) {
      result := NetworkDirection.east
    }.otherwise {
      result := NetworkDirection.north
    }
    result
  }
}

class DirectionOrHere extends Bundle {
  val isHere = Bool()
  val dir = NetworkDirection()
}

class Location(params: FVPUParams) extends Bundle {
  val x = UInt(log2Ceil(params.nColumns).W)
  val y = UInt(log2Ceil(params.nRows).W)
}

class OutputState(params: FVPUParams) extends Bundle {
  val input = NetworkDirection()
  val active = Bool()
  val remaining = UInt(log2Ceil(params.maxPacketLength+1).W)

  // These are the default values after reset.
  // TODO: Fix this to conform to normal Chisel style.
  def defaultInit(): Unit = {
    input := DontCare
    active := false.B
    remaining := DontCare
  }
}

class Header(params: FVPUParams) extends Bundle {
  val dest = new Location(params)
  val address = UInt(log2Ceil(params.ddmAddrWidth).W)
  val length = UInt(log2Ceil(params.maxPacketLength).W)
}

object Header {
  def fromBits(bits: UInt, params: FVPUParams): Header = {
    val header = Wire(new Header(params))
    val reducedBits = bits(header.getWidth-1, 0)
    header := reducedBits.asTypeOf(header)
    header
  }
}

class NetworkSwitch(params: FVPUParams) extends Module {
  // This is a component of the network node that is responsible for implementing the
  // header based packet switching.

  val inputs = IO(Vec(4, new Bus(params.width)))
  val outputs = IO(Vec(4, Flipped(new Bus(params.width))))

  val thisLoc = IO(Input(new Location(params)))

  val toFifos = IO(Vec(4, DecoupledIO(new HeaderTag(UInt(params.width.W)))))
  val fromFifos = IO(Vec(4, Flipped(DecoupledIO(new HeaderTag(UInt(params.width.W))))))


  val fromFifosDirections = Wire(Vec(4, new DirectionOrHere))
  val fromFifosLengths = Wire(Vec(4, UInt(log2Ceil(params.maxPacketLength).W)))
  
  // This works out what direction to route something based on the header.
  def getDirection(thisLoc: Location, header: UInt): DirectionOrHere = {
    val result = Wire(new DirectionOrHere)
    val destLoc = Wire(new Location(params))
    
    destLoc.x := header(log2Ceil(params.nColumns)-1, 0)
    destLoc.y := header(log2Ceil(params.nColumns)+log2Ceil(params.nRows)-1, log2Ceil(params.nColumns))
    
    when (thisLoc.x > destLoc.x) {
      result.isHere := false.B
      result.dir := NetworkDirection.west
    }.elsewhen (thisLoc.x < destLoc.x) {
      result.isHere := false.B
      result.dir := NetworkDirection.east
    }.otherwise {
      when (thisLoc.y > destLoc.y) {
        result.isHere := false.B
        result.dir := NetworkDirection.north
      }.elsewhen (thisLoc.y < destLoc.y) {
        result.isHere := false.B
        result.dir := NetworkDirection.south
      }.otherwise {
        result.isHere := true.B
        result.dir := DontCare
      }
    }
    result
  }
  
  for (srcDirection <- 0 until 4) {
    val tokenToReady = Module(new TokenValidToReadyValid(new HeaderTag(UInt(params.width.W)), params.networkMemoryDepth))
    tokenToReady.input <> inputs(srcDirection)
    toFifos(srcDirection) <> tokenToReady.output
    fromFifosDirections(srcDirection) := getDirection(thisLoc, fromFifos(srcDirection).bits.bits)
    fromFifosLengths(srcDirection) := Header.fromBits(fromFifos(srcDirection).bits.bits, params).length
  }

  for (dstDirection <- 0 until 4) {

    val nextState = Wire(new OutputState(params))
    dontTouch(nextState)
    val state = RegNext(nextState)
    
    val readyToToken = Module(new ReadyValidToTokenValid(new HeaderTag(UInt(params.width.W)), params.networkMemoryDepth))

    val fourthChoice = state.input
    val firstChoice = NetworkDirection.nextDirection(fourthChoice)
    val secondChoice = NetworkDirection.nextDirection(firstChoice)
    val thirdChoice = NetworkDirection.nextDirection(secondChoice)
    val first = fromFifos(firstChoice.asUInt)
    val second = fromFifos(secondChoice.asUInt)
    val third = fromFifos(thirdChoice.asUInt)
    val fourth = fromFifos(fourthChoice.asUInt)
    val choice = Wire(NetworkDirection())
    dontTouch(choice)
    val availableHeader = Wire(Bool())
    dontTouch(availableHeader)
    // Look to see if any of the inputs have headers.
    when (first.valid && first.bits.header && fromFifosDirections(firstChoice.asUInt).dir.asUInt === dstDirection.U) {
      choice := firstChoice
      availableHeader := true.B
    }.elsewhen (second.valid && second.bits.header && fromFifosDirections(secondChoice.asUInt).dir.asUInt === dstDirection.U) {
      choice := secondChoice
      availableHeader := true.B
    }.elsewhen (third.valid && third.bits.header && fromFifosDirections(thirdChoice.asUInt).dir.asUInt === dstDirection.U) {
      choice := thirdChoice
      availableHeader := true.B
    }.elsewhen (fourth.valid && fourth.bits.header && fromFifosDirections(fourthChoice.asUInt).dir.asUInt === dstDirection.U) {
      choice := fourthChoice
      availableHeader := true.B
    }.otherwise {
      choice := state.input
      availableHeader := false.B
    }

    nextState := state
    when (!state.active) {
      nextState.input := choice
      nextState.active := availableHeader
      nextState.remaining := Header.fromBits(fromFifos(choice.asUInt).bits.bits, params).length
      readyToToken.input.valid := false.B
      readyToToken.input.bits := DontCare
    }.otherwise {
      val transfer = fromFifos(state.input.asUInt)
      // Whether we finish depends on whether the transfer is ready.
      when (transfer.valid && transfer.ready) {
        when (!transfer.bits.header) {
          when (state.remaining === 1.U) {
            nextState.active := false.B
          }
          nextState.remaining := state.remaining - 1.U
        }
      }
    }

    val mux = Module(new ReadyValidMux(new HeaderTag(UInt(params.width.W)), 4))
    mux.inputs <> fromFifos
    mux.sel := Mux(state.active, state.input.asUInt, choice.asUInt)
    mux.enable := (state.active || availableHeader)

    readyToToken.input <> mux.output
    readyToToken.output <> outputs(dstDirection)

  }

}
