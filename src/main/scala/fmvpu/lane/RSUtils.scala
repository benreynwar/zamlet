package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Utility functions for reservation stations
 */
object RSUtils {
  /**
   * Updates a RegReadInfo with write results if addresses match
   * 
   * @param regInfo The register read info to potentially update
   * @param writeInputs Vector of write results to check against
   * @param params Lane parameters for configuration
   * @return Updated RegReadInfo with resolved dependency if match found
   */
  def updateRegReadInfo(regInfo: RegReadInfo, writeInputs: Vec[WriteResult], params: LaneParams): RegReadInfo = {
    val result = Wire(new RegReadInfo(params))
    val regRef = regInfo.getRegWithIdent
    
    // Start with original regInfo
    result := regInfo
    
    // Check each write port for a match
    for (j <- 0 until params.nWritePorts) {
      when (!regInfo.resolved && writeInputs(j).valid && 
            regRef.regAddr === writeInputs(j).address.regAddr &&
            regRef.writeIdent === writeInputs(j).address.writeIdent) {
        // Address matches - resolve this dependency
        result.resolved := true.B
        result.value := writeInputs(j).value
      }
    }
    
    result
  }
}