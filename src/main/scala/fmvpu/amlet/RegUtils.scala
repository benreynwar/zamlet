package fmvpu.amlet

import chisel3._
import chisel3.util._

/**
 * Utility functions for register type conversions
 * 
 * T-register is a unified register type that can hold A/D/P/L registers.
 * The encoding uses the upper 2 bits to distinguish register types:
 * - 00: A-register (address)
 * - 01: D-register (data) 
 * - 10: P-register (predicate)
 * - 11: L-register (loop level)
 */
class RegUtils(params: AmletParams) {
  
  /**
   * Convert D-register address to T-register encoding
   * D-registers use encoding 01 in upper 2 bits
   */
  def dRegToTReg(dReg: UInt): UInt = {
    (1.U << (params.tRegWidth - 2)) | dReg.asUInt
  }
  
  /**
   * Convert A-register address to T-register encoding
   * A-registers use encoding 00 in upper 2 bits
   */
  def aRegToTReg(aReg: UInt): UInt = {
    (0.U << (params.tRegWidth - 2)) | aReg.asUInt
  }
  
  /**
   * Convert P-register address to T-register encoding
   * P-registers use encoding 10 in upper 2 bits
   */
  def pRegToTReg(pReg: UInt): UInt = {
    (2.U << (params.tRegWidth - 2)) | pReg.asUInt
  }
  
  /**
   * Convert L-register address to T-register encoding
   * L-registers use encoding 11 in upper 2 bits
   */
  def lRegToTReg(lReg: UInt): UInt = {
    (3.U << (params.tRegWidth - 2)) | lReg.asUInt
  }
  
  /**
   * Convert B-register address to T-register encoding
   * B-registers can point to either A-registers or D-registers
   * Upper bit of bReg indicates: 0=A-register, 1=D-register
   */
  def bRegToTReg(bReg: UInt): UInt = {
    val isAReg = !bReg(params.bRegWidth - 1)
    val regAddr = bReg(params.bRegWidth - 2, 0)
    Mux(isAReg, aRegToTReg(regAddr), dRegToTReg(regAddr))
  }
}