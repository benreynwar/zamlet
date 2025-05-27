package fvpu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid

import scala.io.Source

import fvpu.ModuleGenerator


class NetworkNodeControl(params: FVPUParams) extends Bundle {
  val nsInputSel =  Vec(params.nBuses, Bool());
  val weInputSel =  Vec(params.nBuses, Bool());
  val nsCrossbarSel = Vec(params.nBuses, UInt(log2Ceil(params.nBuses+2).W));
  val weCrossbarSel = Vec(params.nBuses, UInt(log2Ceil(params.nBuses+2).W));
  val drfSel = UInt(log2Ceil(params.nBuses*2).W);
  val ddmSel = UInt(log2Ceil(params.nBuses*2).W);
  val nOutputDelays = Vec(params.nBuses, UInt(log2Ceil(params.networkMemoryDepth+1).W));
  val sOutputDelays = Vec(params.nBuses, UInt(log2Ceil(params.networkMemoryDepth+1).W));
  val wOutputDelays = Vec(params.nBuses, UInt(log2Ceil(params.networkMemoryDepth+1).W));
  val eOutputDelays = Vec(params.nBuses, UInt(log2Ceil(params.networkMemoryDepth+1).W));
  }

class NetworkNode(params: FVPUParams) extends Module {
  val inputs = IO(Vec(4, Vec(params.nBuses, new Bus(params.width))))
  val outputs = IO(Vec(4, Vec(params.nBuses, Flipped(new Bus(params.width)))))
  val toDRF = IO(Output(Valid(UInt(params.width.W))))
  val fromDRF = IO(Input(Valid(UInt(params.width.W))))
  val toDDM = IO(Output(Valid(UInt(params.width.W))))
  val fromDDM = IO(Input(Valid(UInt(params.width.W))))
  val control = IO(Input(new NetworkNodeControl(params)))
  val thisLoc = IO(Input(new Location(params)))

  // Just here to define modules
  val withHeaderTemplate = new HeaderTag(UInt(params.width.W))

  val configValid = IO(Input(Bool()))
  val configIsPacketMode = IO(Input(Bool()))
  val configDelay = IO(Input(UInt(log2Ceil(params.networkMemoryDepth+1).W)))


  val isPacketMode = RegInit(true.B)

  when (configValid) {
    isPacketMode := configIsPacketMode
  }

  val crossbar = Module(new NetworkCrossbar(params))
  // TODO: Connect crossbar inputs properly
  crossbar.fromDRF := fromDRF
  toDRF := crossbar.toDRF
  crossbar.fromDDM := fromDDM
  toDDM := crossbar.toDDM
  crossbar.control := control

  for (busIndex <- 0 until params.nBuses) {
    val switch = Module(new NetworkSwitch(params))
    switch.thisLoc := thisLoc

    for (direction <- 0 until 4) {
      // If we're in packet mode the inputs go to the switch
      // otherwise they go to the crossbar.
      when (isPacketMode) {
        switch.inputs(direction) <> inputs(direction)(busIndex)
        crossbar.inputs(direction)(busIndex).valid := false.B
        crossbar.inputs(direction)(busIndex).bits := DontCare
      }.otherwise {
        switch.inputs(direction).valid := false.B
        switch.inputs(direction).bits := DontCare
        inputs(direction)(busIndex).token := false.B
        crossbar.inputs(direction)(busIndex) := inputs(direction)(busIndex).toValid()
      }

      val fifoOrDelay = Module(new FifoOrDelay(withHeaderTemplate, params.networkMemoryDepth))
      fifoOrDelay.configValid := configValid
      fifoOrDelay.configIsFifo := configIsPacketMode
      fifoOrDelay.configDelay := configDelay

      // If we're in packet mode then the memory inputs come from the switch
      // otherwise the inputs come from the crossbar
      when (isPacketMode) {
        fifoOrDelay.input <> switch.toFifos(direction)
      }.otherwise {
        fifoOrDelay.input.valid := crossbar.outputs(direction)(busIndex).valid
        fifoOrDelay.input.bits.bits := crossbar.outputs(direction)(busIndex).bits
        fifoOrDelay.input.bits.header := false.B
        switch.toFifos(direction).ready := false.B
      }

      // If we're in packet mode then the memory outputs go the switch
      // otherwise they go into the pre-output mux.
      // If we're in packet mode then the pre-output mux comes from the switch

      val toOutputs = Wire(new Bus(params.width))
      when (isPacketMode) {
        switch.fromFifos(direction) <> fifoOrDelay.output
        toOutputs <> switch.outputs(direction)
      }.otherwise {
        toOutputs.valid := fifoOrDelay.output.valid
        toOutputs.bits.bits := fifoOrDelay.output.bits.bits
        toOutputs.bits.header := fifoOrDelay.output.bits.header
        fifoOrDelay.output.ready := toOutputs.token
        switch.fromFifos(direction).valid := false.B
        switch.fromFifos(direction).bits := DontCare
        switch.outputs(direction).token := false.B
      }
      
      // Register the outputs.
      outputs(direction)(busIndex).valid := RegNext(toOutputs.valid)
      outputs(direction)(busIndex).bits := RegNext(toOutputs.bits)
      toOutputs.token := RegNext(outputs(direction)(busIndex).token)

    }
  }

}


object NetworkNodeGenerator extends ModuleGenerator {

  override def makeModule(args: Seq[String]): Module = {
    // Parse arguments
    if (args.length < 1) {
      println("Usage: <command> <outputDir> NetworkNode <paramsFileName>")
      return null
    }
    val params = FVPUParams.fromFile(args(0));
    return new NetworkNode(params);
  }

}
