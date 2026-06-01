package zamlet


import chisel3._
import chisel3.util._

object SimpleElementWidth extends ChiselEnum {
  val ew8 = Value(0.U)
  val ew16 = Value(1.U)
  val ew32 = Value(2.U)
  val ew64 = Value(3.U)
}

object Utils {

  def ewLog2Bits(ew: SimpleElementWidth.Type): UInt = {
    val result = WireDefault(UInt(3.W), 0.U)
    switch(ew) {
      is(SimpleElementWidth.ew8) { result := 3.U }
      is(SimpleElementWidth.ew16) { result := 4.U }
      is(SimpleElementWidth.ew32) { result := 5.U }
      is(SimpleElementWidth.ew64) { result := 6.U }
    }
    result
  }

  def ewBits(ew: SimpleElementWidth.Type): UInt = {
    val result = WireDefault(UInt(7.W), 0.U)
    switch(ew) {
      is(SimpleElementWidth.ew8) { result := 8.U }
      is(SimpleElementWidth.ew16) { result := 16.U }
      is(SimpleElementWidth.ew32) { result := 32.U }
      is(SimpleElementWidth.ew64) { result := 64.U }
    }
    result
  }

  def maskLow(data: UInt, nBits: UInt): UInt = {
    val mask = (1.U((data.getWidth + 1).W) << nBits) - 1.U
    data & mask(data.getWidth - 1, 0)
  }

  def getElement(data: UInt, ew: SimpleElementWidth.Type, index: UInt): UInt = {
    // `data` is a word treated as a vector of elements
    // `ew` an enum representing the element width
    // `index` is the index of the element we with to retrieve
    val log2EW = ewLog2Bits(ew)
    val bitsEW = ewBits(ew)
    val log2NElements = log2Ceil(data.getWidth).U - log2EW
    val reducedIndex = maskLow(index, log2NElements)
    val shiftedData = data >> (reducedIndex << log2EW)
    val maskedData = maskLow(shiftedData, bitsEW)
    maskedData
  }
}
