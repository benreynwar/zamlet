package fmpvu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid

import scala.io.Source

import fmpvu.ModuleGenerator


class NetworkCrossbar(params: FMPVUParams) extends Module {
  val inputs = IO(Vec(4, Vec(params.nBuses, Input(Valid(UInt(params.width.W))))))
  val outputs = IO(Vec(4, Vec(params.nBuses, Output(Valid(UInt(params.width.W))))))
  val toDRF = IO(Output(Valid(UInt(params.width.W))));
  val fromDRF = IO(Input(Valid(UInt(params.width.W))));
  val toDDM = IO(Output(Valid(UInt(params.width.W))));
  val fromDDM = IO(Input(Valid(UInt(params.width.W))));
  val control = IO(Input(new NetworkNodeControl(params)));

  val nsToCrossbar = Wire(Vec(params.nBuses+2, Valid(UInt(params.width.W))))
  val weToCrossbar = Wire(Vec(params.nBuses+2, Valid(UInt(params.width.W))))
  val nsweToCrossbar = Wire(Vec(2*params.nBuses, Valid(UInt(params.width.W))))
  for (i <- 0 until params.nBuses) {
    nsToCrossbar(i) := Mux(control.nsInputSel(i), inputs(1)(i), inputs(0)(i))
    weToCrossbar(i) := Mux(control.weInputSel(i), inputs(3)(i), inputs(2)(i))
    nsweToCrossbar(i) := nsToCrossbar(i)
    nsweToCrossbar(i+params.nBuses) := weToCrossbar(i)
  }
  nsToCrossbar(params.nBuses) := fromDRF
  nsToCrossbar(params.nBuses+1) := fromDDM
  weToCrossbar(params.nBuses) := fromDRF
  weToCrossbar(params.nBuses+1) := fromDDM

  val nsFromCrossbar = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))))
  val weFromCrossbar = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))))
  for (i <- 0 until params.nBuses) {
    nsFromCrossbar(i) := nsToCrossbar(control.nsCrossbarSel(i))
    weFromCrossbar(i) := weToCrossbar(control.weCrossbarSel(i))
  }

  val fromDRFSel = Wire(Valid(UInt(params.width.W)))
  val fromDDMSel = Wire(Valid(UInt(params.width.W)))
  fromDRFSel := nsweToCrossbar(control.drfSel)
  fromDDMSel := nsweToCrossbar(control.ddmSel)

  for (i <- 0 until params.nBuses) {
    outputs(0)(i) := nsFromCrossbar(i)
    outputs(1)(i) := nsFromCrossbar(i)
    outputs(2)(i) := weFromCrossbar(i)
    outputs(3)(i) := weFromCrossbar(i)
  }

  toDRF := RegNext(fromDRFSel)
  toDDM := RegNext(fromDDMSel)

}
