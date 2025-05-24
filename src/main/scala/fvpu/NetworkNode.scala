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
  val nOutputDelays = Vec(params.nBuses, UInt(log2Ceil(params.maxNetworkOutputDelay).W));
  val sOutputDelays = Vec(params.nBuses, UInt(log2Ceil(params.maxNetworkOutputDelay).W));
  val wOutputDelays = Vec(params.nBuses, UInt(log2Ceil(params.maxNetworkOutputDelay).W));
  val eOutputDelays = Vec(params.nBuses, UInt(log2Ceil(params.maxNetworkOutputDelay).W));
  val nOutputDrive = Vec(params.nBuses, Bool());
  val sOutputDrive = Vec(params.nBuses, Bool());
  val wOutputDrive = Vec(params.nBuses, Bool());
  val eOutputDrive = Vec(params.nBuses, Bool());
  }

class NetworkNode(params: FVPUParams) extends Module {
  val nI = IO(Input(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val nO = IO(Output(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val sI = IO(Input(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val sO = IO(Output(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val eI = IO(Input(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val eO = IO(Output(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val wI = IO(Input(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val wO = IO(Output(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val toDRF = IO(Output(Valid(UInt(params.width.W))));
  val fromDRF = IO(Input(Valid(UInt(params.width.W))));
  val toDDM = IO(Output(Valid(UInt(params.width.W))));
  val fromDDM = IO(Input(Valid(UInt(params.width.W))));
  val control = IO(Input(new NetworkNodeControl(params)));

  val allI = Wire(Vec(params.nBuses, Vec(4, Valid(UInt(params.width.W)))));
  for (i <- 0 until params.nBuses) {
    // Connect each direction: North(0), South(1), West(3), East(4)
    allI(i)(0) := nI(i)
    allI(i)(1) := sI(i)
    allI(i)(2) := wI(i)
    allI(i)(3) := eI(i)
  }

  val nsToCrossbar = Wire(Vec(params.nBuses+2, Valid(UInt(params.width.W))));
  val weToCrossbar = Wire(Vec(params.nBuses+2, Valid(UInt(params.width.W))));
  val nsweToCrossbar = Wire(Vec(2*params.nBuses, Valid(UInt(params.width.W))));
  for (i <- 0 until params.nBuses) {
    nsToCrossbar(i) := Mux(control.nsInputSel(i), sI(i), nI(i));
    weToCrossbar(i) := Mux(control.weInputSel(i), eI(i), wI(i));
    nsweToCrossbar(i) := nsToCrossbar(i);
    nsweToCrossbar(i+params.nBuses) := weToCrossbar(i);
  }
  nsToCrossbar(params.nBuses) := fromDRF;
  nsToCrossbar(params.nBuses+1) := fromDDM;
  weToCrossbar(params.nBuses) := fromDRF;
  weToCrossbar(params.nBuses+1) := fromDDM;

  val nsFromCrossbar = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))));
  val weFromCrossbar = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))));
  for (i <- 0 until params.nBuses) {
    nsFromCrossbar(i) := nsToCrossbar(control.nsCrossbarSel(i));
    weFromCrossbar(i) := weToCrossbar(control.weCrossbarSel(i));
  }

  val fromDRFSel = Wire(Valid(UInt(params.width.W)));
  val fromDDMSel = Wire(Valid(UInt(params.width.W)));
  fromDRFSel := nsweToCrossbar(control.drfSel);
  fromDDMSel := nsweToCrossbar(control.ddmSel);

  val nDelayed = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))));
  val sDelayed = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))));
  val wDelayed = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))));
  val eDelayed = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))));
  for (i <- 0 until params.nBuses) {
    val nAdjustableDelay = Module(new AdjustableDelay(params.maxNetworkOutputDelay, params.width));
    nAdjustableDelay.delay := control.nOutputDelays(i);
    nAdjustableDelay.input := nsFromCrossbar(i);
    nDelayed(i) := nAdjustableDelay.output;
    
    val sAdjustableDelay = Module(new AdjustableDelay(params.maxNetworkOutputDelay, params.width));
    sAdjustableDelay.delay := control.sOutputDelays(i);
    sAdjustableDelay.input := nsFromCrossbar(i);
    sDelayed(i) := sAdjustableDelay.output;
    
    val wAdjustableDelay = Module(new AdjustableDelay(params.maxNetworkOutputDelay, params.width));
    wAdjustableDelay.delay := control.wOutputDelays(i);
    wAdjustableDelay.input := weFromCrossbar(i);
    wDelayed(i) := wAdjustableDelay.output;
    
    val eAdjustableDelay = Module(new AdjustableDelay(params.maxNetworkOutputDelay, params.width));
    eAdjustableDelay.delay := control.eOutputDelays(i);
    eAdjustableDelay.input := weFromCrossbar(i);
    eDelayed(i) := eAdjustableDelay.output;
  }

  val nFromOutputMux = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))));
  val sFromOutputMux = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))));
  val wFromOutputMux = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))));
  val eFromOutputMux = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))));
  dontTouch(nFromOutputMux);
  dontTouch(sFromOutputMux);
  dontTouch(wFromOutputMux);
  dontTouch(eFromOutputMux);
  for (i <- 0 until params.nBuses) {
    nFromOutputMux(i) := Mux(control.nOutputDrive(i), nDelayed(i), sI(i));
    sFromOutputMux(i) := Mux(control.sOutputDrive(i), sDelayed(i), nI(i));
    wFromOutputMux(i) := Mux(control.wOutputDrive(i), wDelayed(i), eI(i));
    eFromOutputMux(i) := Mux(control.eOutputDrive(i), eDelayed(i), wI(i));
  }

  nO := RegNext(nFromOutputMux);
  sO := RegNext(sFromOutputMux);
  wO := RegNext(wFromOutputMux);
  eO := RegNext(eFromOutputMux);

  toDRF := RegNext(fromDRFSel);
  toDDM := RegNext(fromDDMSel);

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
