package fmvpu.network

import chisel3._
import chisel3.util.log2Ceil
import chisel3.util.Valid

// =============================================================================
// Memory Interface Bundles
// =============================================================================

/**
 * Read port interface with valid signals for variable latency memories
 * 
 * This interface supports memories where read latency is not fixed or known,
 * using Valid signals to indicate when data is available.
 * 
 * @param t Data type for the read data
 * @param addrWidth Width of the address bus in bits
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class ValidReadPort[T <: Data](t: T, addrWidth: Int) extends Bundle {
  /** Address input with valid signal for read requests
    * @group Signals
    */
  val address = Input(Valid(UInt(addrWidth.W)))
  
  /** Data output with valid signal indicating when data is ready
    * @group Signals
    */
  val data = Output(Valid(t))
}

/**
 * Input port interface for single-port read/write memory
 * 
 * This interface provides the input signals for a memory port that can handle
 * both read and write operations. The output data port is excluded to support
 * situations where bidirectional interfaces cannot be used.
 * 
 * @param width Data width in bits
 * @param addrWidth Address width in bits
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class ReadWriteInputPort(width: Int, addrWidth: Int) extends Bundle {
  /** Memory address for read/write operation
    * @group Signals
    */
  val address = UInt(addrWidth.W)
  
  /** Data to write (ignored for read operations)
    * @group Signals
    */
  val data = UInt(width.W)
  
  /** Enable signal for the memory operation
    * @group Signals
    */
  val enable = Bool()
  
  /** Operation type: true for write, false for read
    * @group Signals
    */
  val isWrite = Bool()
}
