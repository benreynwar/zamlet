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
  val io = IO(new Bundle {
    val inputs = Vec(4, Vec(params.nBuses, Input(Valid(UInt(params.width.W)))))
    val outputs = Vec(4, Vec(params.nBuses, Output(Valid(UInt(params.width.W)))))
    val toDRF = Output(Valid(UInt(params.width.W)))
    val fromDRF = Input(Valid(UInt(params.width.W)))
    val toDDM = Output(Valid(UInt(params.width.W)))
    val fromDDM = Input(Valid(UInt(params.width.W)))
    val control = Input(new NetworkNodeControl(params))
  })

  val nsToCrossbar = Wire(Vec(params.nBuses + 2, Valid(UInt(params.width.W))))
  val weToCrossbar = Wire(Vec(params.nBuses + 2, Valid(UInt(params.width.W))))
  val nsweToCrossbar = Wire(Vec(2 * params.nBuses, Valid(UInt(params.width.W))))
  for (i <- 0 until params.nBuses) {
    nsToCrossbar(i) := Mux(io.control.nsInputSel(i), io.inputs(1)(i), io.inputs(0)(i))
    weToCrossbar(i) := Mux(io.control.weInputSel(i), io.inputs(3)(i), io.inputs(2)(i))
    nsweToCrossbar(i) := nsToCrossbar(i)
    nsweToCrossbar(i + params.nBuses) := weToCrossbar(i)
  }
  nsToCrossbar(params.nBuses) := io.fromDRF
  nsToCrossbar(params.nBuses + 1) := io.fromDDM
  weToCrossbar(params.nBuses) := io.fromDRF
  weToCrossbar(params.nBuses + 1) := io.fromDDM

  val nsFromCrossbar = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))))
  val weFromCrossbar = Wire(Vec(params.nBuses, Valid(UInt(params.width.W))))
  for (i <- 0 until params.nBuses) {
    nsFromCrossbar(i) := nsToCrossbar(io.control.nsCrossbarSel(i))
    weFromCrossbar(i) := weToCrossbar(io.control.weCrossbarSel(i))
  }

  val fromDRFSel = Wire(Valid(UInt(params.width.W)))
  val fromDDMSel = Wire(Valid(UInt(params.width.W)))
  fromDRFSel := nsweToCrossbar(io.control.drfSel)
  fromDDMSel := nsweToCrossbar(io.control.ddmSel)

  for (i <- 0 until params.nBuses) {
    io.outputs(0)(i) := nsFromCrossbar(i)
    io.outputs(1)(i) := nsFromCrossbar(i)
    io.outputs(2)(i) := weFromCrossbar(i)
    io.outputs(3)(i) := weFromCrossbar(i)
  }

  io.toDRF := RegNext(fromDRFSel)
  io.toDDM := RegNext(fromDDMSel)
}
