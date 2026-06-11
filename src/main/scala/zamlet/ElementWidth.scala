package zamlet

import chisel3._
import chisel3.util._

object WidthFormat extends ChiselEnum {
  val wf1 = Value(0.U)
  val wf2 = Value(1.U)
  val wf4 = Value(2.U)
  val wf8 = Value(3.U)
  val wf16 = Value(4.U)
  val wf32 = Value(5.U)
  val wf64 = Value(6.U)
  val wf128 = Value(7.U)
  val wf256 = Value(8.U)
  val wf512 = Value(9.U)
  val wf1024Invalid = Value(10.U)
  val wf2048Invalid = Value(11.U)
  val wf4096Invalid = Value(12.U)
  val wf8192Invalid = Value(13.U)
  val wf16384Invalid = Value(14.U)
  val wf32768Invalid = Value(15.U)
}

object ElementWidth extends ChiselEnum {
  val ew1 = Value(0.U)
  val ew2Invalid = Value(1.U)
  val ew4Invalid = Value(2.U)
  val ew8 = Value(3.U)
  val ew16 = Value(4.U)
  val ew32 = Value(5.U)
  val ew64 = Value(6.U)
  val ew128 = Value(7.U)
}

object WidthHelpers {

  def wfBits(wf: WidthFormat.Type): UInt = {
    val result = WireDefault(UInt(10.W), 0.U)
    switch(wf) {
      is(WidthFormat.wf1) { result := 1.U }
      is(WidthFormat.wf8) { result := 8.U }
      is(WidthFormat.wf16) { result := 16.U }
      is(WidthFormat.wf32) { result := 32.U }
      is(WidthFormat.wf64) { result := 64.U }
      is(WidthFormat.wf128) { result := 128.U }
      is(WidthFormat.wf256) { result := 256.U }
      is(WidthFormat.wf512) { result := 512.U }
    }
    result
  }

  def wfLog2Bits(wf: WidthFormat.Type): UInt = {
    val result = WireDefault(UInt(4.W), 0.U)
    switch(wf) {
      is(WidthFormat.wf1) { result := 0.U }
      is(WidthFormat.wf8) { result := 3.U }
      is(WidthFormat.wf16) { result := 4.U }
      is(WidthFormat.wf32) { result := 5.U }
      is(WidthFormat.wf64) { result := 6.U }
      is(WidthFormat.wf128) { result := 7.U }
      is(WidthFormat.wf256) { result := 8.U }
      is(WidthFormat.wf512) { result := 9.U }
    }
    result
  }

  def ewBits(ew: ElementWidth.Type): UInt = {
    val result = WireDefault(UInt(10.W), 0.U)
    switch(ew) {
      is(ElementWidth.ew1) { result := 1.U }
      is(ElementWidth.ew8) { result := 8.U }
      is(ElementWidth.ew16) { result := 16.U }
      is(ElementWidth.ew32) { result := 32.U }
      is(ElementWidth.ew64) { result := 64.U }
      is(ElementWidth.ew128) { result := 128.U }
    }
    result
  }

  def ewLog2Bits(ew: ElementWidth.Type): UInt = {
    val result = WireDefault(UInt(4.W), 0.U)
    switch(ew) {
      is(ElementWidth.ew1) { result := 0.U }
      is(ElementWidth.ew8) { result := 3.U }
      is(ElementWidth.ew16) { result := 4.U }
      is(ElementWidth.ew32) { result := 5.U }
      is(ElementWidth.ew64) { result := 6.U }
      is(ElementWidth.ew128) { result := 7.U }
    }
    result
  }

  def ewToSimple(ew: ElementWidth.Type): SimpleElementWidth.Type = {
    val result = Wire(SimpleElementWidth())
    result := DontCare
    switch(ew) {
      is(ElementWidth.ew8) { result := SimpleElementWidth.ew8 }
      is(ElementWidth.ew16) { result := SimpleElementWidth.ew16 }
      is(ElementWidth.ew32) { result := SimpleElementWidth.ew32 }
      is(ElementWidth.ew64) { result := SimpleElementWidth.ew64 }
    }
    result
  }

  def compatible(ewA: ElementWidth.Type, ewB: ElementWidth.Type, wfA: WidthFormat.Type, wfB: WidthFormat.Type): Bool = {
      (wfLog2Bits(wfA) >= ewLog2Bits(ewA)) &&
      (wfLog2Bits(wfB) >= ewLog2Bits(ewB)) &&
      (wfLog2Bits(wfA) - ewLog2Bits(ewA) === wfLog2Bits(wfB) - ewLog2Bits(ewB))
  }
}
