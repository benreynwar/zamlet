package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Register address combined with write identifier for dependency tracking
 */
class RegWithIdent(params: LaneParams) extends Bundle {
  val regAddr = UInt(params.regAddrWidth.W)
  val writeIdent = UInt(params.writeIdentWidth.W)
}

/**
 * Register read information containing either resolved data or unresolved register reference
 */
class RegReadInfo(params: LaneParams) extends Bundle {
  /** True if this contains resolved data, false if it contains register address + write ident */
  val resolved = Bool()
  /** Either immediate data (if resolved) or packed (regAddr, writeIdent) (if unresolved) */
  val value = UInt(params.width.W)
  
  /** Extract immediate data (only valid when resolved = true) */
  def getData: UInt = value
  
  /** Extract register address + write identifier (only valid when resolved = false) */
  def getRegWithIdent: RegWithIdent = {
    val result = Wire(new RegWithIdent(params))
    result.regAddr := value(params.regAddrWidth - 1, 0)
    result.writeIdent := value(params.regAddrWidth + params.writeIdentWidth - 1, params.regAddrWidth)
    result
  }
  
  /** Create RegReadInfo with immediate data */
  def setData(data: UInt): Unit = {
    resolved := true.B
    value := data
  }
  
  /** Create RegReadInfo with register reference */
  def setRegRef(regAddr: UInt, writeIdent: UInt): Unit = {
    resolved := false.B
    value := Cat(writeIdent, regAddr)
  }
}