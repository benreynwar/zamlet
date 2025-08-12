package zamlet.amlet

import chisel3._
import chisel3.util._
import zamlet.utils.{WriteAccessOut, ReadAccessOut}

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

  /**
   * Check if B-register points to an A-register
   * Upper bit = 0 indicates A-register
   */
  def bRegIsA(bReg: UInt): Bool = {
    !bReg(params.bRegWidth - 1)
  }

  /**
   * Extract A-register address from B-register
   * Returns the lower bits as A-register index
   */
  def bRegToA(bReg: UInt): UInt = {
    bReg(params.aRegWidth - 1, 0)
  }

  /**
   * Extract D-register address from B-register
   * Returns the lower bits as D-register index
   */
  def bRegToD(bReg: UInt): UInt = {
    bReg(params.dRegWidth - 1, 0)
  }

  /**
   * Convert WriteResult to A-register result format
   */
  def toAResult(writeResult: Valid[WriteResult]): Valid[ATaggedSource] = {
    val result = Wire(Valid(new ATaggedSource(params)))
    result.valid := writeResult.valid
    result.bits.value := writeResult.bits.value(params.aWidth - 1, 0)
    result.bits.resolved := writeResult.valid
    result.bits.addr := writeResult.bits.address.addr(params.aRegWidth - 1, 0)
    result.bits.tag := writeResult.bits.address.tag
    result
  }

  /**
   * Convert WriteResult to D-register result format
   */
  def toDResult(writeResult: Valid[WriteResult]): Valid[DTaggedSource] = {
    val result = Wire(Valid(new DTaggedSource(params)))
    result.valid := writeResult.valid
    result.bits.value := writeResult.bits.value
    result.bits.resolved := writeResult.valid
    result.bits.addr := writeResult.bits.address.addr(params.dRegWidth - 1, 0)
    result.bits.tag := writeResult.bits.address.tag
    result
  }

  /**
   * Create B-register write target from B-register address and write ports
   */
  def toBWrite(bReg: UInt, aWrite: WriteAccessOut, dWrite: WriteAccessOut): BTaggedReg = {
    val result = Wire(new BTaggedReg(params))
    when (bRegIsA(bReg)) {
      result.addr := bReg
      result.tag := aWrite.tag
    } .otherwise {
      result.addr := bReg
      result.tag := dWrite.tag
    }
    result
  }

  /**
   * Create B-register read source from B-register address and read ports
   */
  def toBRead(bReg: UInt, aRead: ReadAccessOut, dRead: ReadAccessOut): BTaggedSource = {
    val result = Wire(new BTaggedSource(params))
    when (bRegIsA(bReg)) {
      result.value := aRead.value(params.aWidth - 1, 0)
      result.resolved := aRead.resolved
      result.addr := bReg
      result.tag := aRead.tag
    } .otherwise {
      result.value := dRead.value
      result.resolved := dRead.resolved
      result.addr := bReg
      result.tag := dRead.tag
    }
    result
  }

  /**
   * Convert WriteAccessOut to ATaggedReg
   */
  def writeAccessToATaggedReg(writeAccess: WriteAccessOut): ATaggedReg = {
    val result = Wire(new ATaggedReg(params))
    result.addr := writeAccess.addr
    result.tag := writeAccess.tag
    result
  }

  /**
   * Convert WriteAccessOut to DTaggedReg
   */
  def writeAccessToDTaggedReg(writeAccess: WriteAccessOut): DTaggedReg = {
    val result = Wire(new DTaggedReg(params))
    result.addr := writeAccess.addr
    result.tag := writeAccess.tag
    result
  }

  /**
   * Convert ReadAccessOut to ATaggedSource
   */
  def readAccessToATaggedSource(readAccess: ReadAccessOut): ATaggedSource = {
    val result = Wire(new ATaggedSource(params))
    result.addr := readAccess.addr
    result.tag := readAccess.tag
    result.value := readAccess.value(params.aWidth - 1, 0)
    result.resolved := readAccess.resolved
    result
  }

  /**
   * Convert ReadAccessOut to DTaggedSource
   */
  def readAccessToDTaggedSource(readAccess: ReadAccessOut): DTaggedSource = {
    val result = Wire(new DTaggedSource(params))
    result.addr := readAccess.addr
    result.tag := readAccess.tag
    result.value := readAccess.value
    result.resolved := readAccess.resolved
    result
  }
}