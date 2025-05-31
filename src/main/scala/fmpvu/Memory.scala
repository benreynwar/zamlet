package fmpvu

import chisel3._
import chisel3.util.log2Ceil
import chisel3.util.Valid
import chisel3.util.DecoupledIO

import fmpvu.ModuleGenerator

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

// =============================================================================
// Flow Control Interfaces
// =============================================================================

/**
 * Token-based valid interface for flow control
 * 
 * This interface is similar to ReadyValid but uses tokens for backpressure control.
 * The sender receives tokens and can send one cycle of data for each token received.
 * This approach simplifies pipelining compared to ReadyValid but requires a buffer
 * at the receiver equal to the pipeline latency for full throughput.
 * 
 * @param t Data type for the payload
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class TokenValid[T <: Data](t: T) extends Bundle {
  /** Indicates when data is valid
    * @group Signals
    */
  val valid = Input(Bool())
  
  /** Data payload
    * @group Signals
    */
  val bits = Input(t)
  
  /** Token signal for flow control (sender can send when this is true)
    * @group Signals
    */
  val token = Output(Bool())
}

/**
 * Bus interface with header/data packets and token flow control
 * 
 * This extends TokenValid with header tagging support for packet-based communication.
 * 
 * @param width Data width in bits
 * @groupdesc Methods Utility methods for interface conversion
 */
class Bus(width: Int) extends TokenValid(new HeaderTag(UInt(width.W))) {

  /** Convert to a simple Valid interface, extracting just the data
    * @group Methods
    */
  def toValid(): Valid[UInt] = {
    val validSignal = Wire(Valid(UInt(width.W)))
    validSignal.valid := valid
    validSignal.bits := bits.bits
    validSignal
  }

  /** Initialize from a Valid interface, setting header to false
    * @group Methods
    */
  def fromValid(validSignal: Valid[UInt]): Unit = {
    valid := validSignal.valid
    token := false.B
    bits.header := false.B
    bits.bits := validSignal.bits
  }
}

/**
 * Data wrapper with header bit for packet identification
 * 
 * This bundle adds a header bit to any data type, allowing packets to be
 * marked as headers or regular data.
 * 
 * @param t Data type to be wrapped
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class HeaderTag[T <: Data](t: T) extends Bundle {
  /** Header bit: true for header packets, false for data packets
    * @group Signals
    */
  val header = Bool()
  
  /** Actual data payload
    * @group Signals
    */
  val bits = t
}

// =============================================================================
// Flow Control Converters
// =============================================================================

/**
 * Error signals for TokenValidToReadyValid converter
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class TokenValidToReadyValidErrors extends Bundle {
  /** Error: output not ready when input is valid (overflow)
    * @group Signals
    */
  val overflow = Bool()
  
  /** Error: received more data than tokens were sent (flow control violation)
    * @group Signals
    */
  val flowControlViolation = Bool()
}

class TokenValidToReadyValid[T <: Data](t: T, nTokens: Int) extends Module {
  val input = IO(new TokenValid(t))
  val output = IO(DecoupledIO(t))
  val errors = IO(Output(new TokenValidToReadyValidErrors))

  // Token counter tracks available receive capacity
  val receiveTokens = RegInit(nTokens.U(log2Ceil(nTokens + 1).W))

  // Error detection
  errors.overflow := input.valid && !output.ready
  errors.flowControlViolation := input.valid && (receiveTokens === nTokens.U)
  output.valid := input.valid
  output.bits := input.bits

  // Send tokens to transmitter when we have receive capacity available
  input.token := receiveTokens > 0.U
  when(input.token && input.valid) {
    // Token sent and data received: no net change
  }.elsewhen(input.token) {
    // Token sent but no data received: decrease available capacity
    receiveTokens := receiveTokens - 1.U
  }.elsewhen(input.valid) {
    // Data received but no token sent: increase count
    receiveTokens := receiveTokens + 1.U
  }
}

class ReadyValidToTokenValid[T <: Data](t: T, nTokens: Int) extends Module {
  val input = IO(Flipped(DecoupledIO(t)))
  val output = IO(Flipped(new TokenValid(t)))
  val errorUnexpectedToken = IO(Output(Bool()))

  val txTokens = RegInit(0.U(log2Ceil(nTokens+1).W))

  errorUnexpectedToken := false.B

  output.bits := input.bits
  output.valid := (txTokens > 0.U) && input.valid

  input.ready := (txTokens > 0.U)

  when (output.token && output.valid) {
    // Token received and data sent: no net change in capacity
  }.elsewhen (output.token) {
    // Token received but no data sent: increase send capacity
    when (txTokens === nTokens.U) {
      // Error: received token when already at maximum capacity
      errorUnexpectedToken := true.B
    }.otherwise {
      txTokens := txTokens + 1.U
    }
  }.elsewhen (output.valid) {
    // Data sent but no token received: decrease send capacity
    txTokens := txTokens - 1.U
  }
}

// =============================================================================
// ReadyValid Multiplexers and Routers
// =============================================================================

/**
 * Two-input ReadyValid multiplexer with enable control
 * 
 * Selects between two ReadyValid inputs based on a select signal.
 * When enabled, connects the selected input to the output while
 * providing backpressure only to the selected input.
 * When disabled, all inputs are not ready and output is invalid.
 * 
 * @param t Data type for the payload
 * @groupdesc Signals The actual hardware fields of the IO Bundle
 */
class ReadyValid2Mux[T <: Data](t: T) extends Module {
  /** First ReadyValid input
    * @group Signals
    */
  val inputA = IO(Flipped(DecoupledIO(t)))
  
  /** Second ReadyValid input
    * @group Signals
    */
  val inputB = IO(Flipped(DecoupledIO(t)))
  
  /** ReadyValid output
    * @group Signals
    */
  val output = IO(DecoupledIO(t))
  
  /** Input selection: true for inputA, false for inputB
    * @group Signals
    */
  val sel = IO(Input(Bool()))
  
  /** Enable signal for the multiplexer
    * @group Signals
    */
  val enable = IO(Input(Bool()))

  when(enable) {
    // Route ready signal only to selected input
    inputA.ready := sel && output.ready
    inputB.ready := (!sel) && output.ready
    
    // Route selected input to output
    output.valid := Mux(sel, inputA.valid, inputB.valid)
    output.bits := Mux(sel, inputA.bits, inputB.bits)
  }.otherwise {
    // When disabled, no inputs are ready and output is invalid
    inputA.ready := false.B
    inputB.ready := false.B
    output.valid := false.B
    output.bits := DontCare
  }
}

/**
 * ReadyValid splitter with select-based routing
 * 
 * Routes a single ReadyValid input to one of two outputs based on
 * a select signal. The unselected output is always invalid.
 * Backpressure from the selected output is passed through to the input.
 * 
 * @param t Data type for the payload
 * @groupdesc Signals The actual hardware fields of the IO Bundle
 */
class ReadyValidSplit[T <: Data](t: T) extends Module {
  /** ReadyValid input
    * @group Signals
    */
  val input = IO(Flipped(DecoupledIO(t)))
  
  /** First ReadyValid output
    * @group Signals
    */
  val outputA = IO(DecoupledIO(t))
  
  /** Second ReadyValid output
    * @group Signals
    */
  val outputB = IO(DecoupledIO(t))
  
  /** Output selection: true for outputA, false for outputB
    * @group Signals
    */
  val sel = IO(Input(Bool()))

  when(sel) {
    // Route input to outputA
    input <> outputA
    outputB.valid := false.B
    outputB.bits := DontCare
  }.otherwise {
    // Route input to outputB
    input <> outputB
    outputA.valid := false.B
    outputA.bits := DontCare
  }
}

/**
 * Utility object for creating ReadyValid splitters inline
 * 
 * Provides a convenient apply method to split a ReadyValid stream
 * into two outputs without instantiating a separate module.
 */
object MuxSplitReadyValid {
  /**
   * Split a ReadyValid input into two outputs based on select signal
   * 
   * @param t Data type for the payload
   * @param input ReadyValid input to be split
   * @param sel Output selection: true for outputA, false for outputB
   * @return Tuple of (outputA, outputB) ReadyValid interfaces
   */
  def apply[T <: Data](t: T, input: DecoupledIO[T], sel: Bool): (DecoupledIO[T], DecoupledIO[T]) = {
    val outputA = Wire(DecoupledIO(t))
    val outputB = Wire(DecoupledIO(t))
    
    when(sel) {
      // Route input to outputA
      outputA <> input
      outputB.valid := false.B
      outputB.bits := DontCare
    }.otherwise {
      // Route input to outputB
      outputB <> input
      outputA.valid := false.B
      outputA.bits := DontCare
    }
    
    (outputA, outputB)
  }
}

/**
 * N-input ReadyValid multiplexer with enable control
 * 
 * Selects one of N ReadyValid inputs based on a select signal.
 * When enabled, connects the selected input to the output while
 * providing backpressure only to the selected input.
 * When disabled, all inputs are not ready and output is invalid.
 * 
 * @param t Data type for the payload
 * @param nInputs Number of input ports
 * @groupdesc Signals The actual hardware fields of the IO Bundle
 */
class ReadyValidMux[T <: Data](t: T, nInputs: Int) extends Module {
  /** Vector of ReadyValid inputs
    * @group Signals
    */
  val inputs = IO(Vec(nInputs, Flipped(DecoupledIO(t))))
  
  /** ReadyValid output
    * @group Signals
    */
  val output = IO(DecoupledIO(t))
  
  /** Input selection index
    * @group Signals
    */
  val sel = IO(Input(UInt(log2Ceil(nInputs).W)))
  
  /** Enable signal for the multiplexer
    * @group Signals
    */
  val enable = IO(Input(Bool()))

  when(enable) {
    // Route ready signal only to selected input
    for (i <- 0 until nInputs) {
      inputs(i).ready := (sel === i.U) && output.ready
    }
    
    // Route selected input to output
    output.valid := inputs(sel).valid
    output.bits := inputs(sel).bits
  }.otherwise {
    // When disabled, no inputs are ready and output is invalid
    for (i <- 0 until nInputs) {
      inputs(i).ready := false.B
    }
    output.valid := false.B
    output.bits := DontCare
  }
}

// =============================================================================
// Valid Signal Multiplexers
// =============================================================================

/**
 * N-input Valid signal multiplexer with conflict detection
 * 
 * This module takes multiple Valid inputs and produces a single Valid output.
 * The output is valid only when exactly one input is valid. If zero inputs
 * are valid, the output is invalid. If multiple inputs are valid simultaneously,
 * the output is invalid and an error is asserted.
 * 
 * @param gen Data type for the payload
 * @param nInputs Number of input Valid signals
 * @groupdesc Signals The actual hardware fields of the IO Bundle
 */
class ValidMux[T <: Data](gen: T, nInputs: Int) extends Module {
  val io = IO(new Bundle {
    /** Vector of Valid input signals
      * @group Signals
      */
    val inputs = Input(Vec(nInputs, Valid(gen)))
    
    /** Valid output signal (valid only when exactly one input is valid)
      * @group Signals
      */
    val output = Output(Valid(gen))
    
    /** Error signal indicating multiple simultaneous valid inputs
      * @group Signals
      */
    val error = Output(Bool())
  })

  val nInputsA = (nInputs + 1) / 2
  val nInputsB = nInputs - nInputsA

  if (nInputs == 1) {
    io.output := io.inputs(0)
    io.error := false.B
  } else {
    val validMuxA = Module(new ValidMux(gen, nInputsA))
    val validMuxB = Module(new ValidMux(gen, nInputsB))
    for (i <- 0 until nInputsA) {
      validMuxA.io.inputs(i) := io.inputs(i)
    }
    for (i <- 0 until nInputsB) {
      validMuxB.io.inputs(i) := io.inputs(i + nInputsA)
    }
    val aIntermed = validMuxA.io.output
    val aError = validMuxA.io.error
    val bIntermed = validMuxB.io.output
    val bError = validMuxB.io.error
    when (aIntermed.valid && bIntermed.valid) {
      io.output.valid := false.B
      io.output.bits := DontCare
      io.error := true.B
    }.elsewhen (aIntermed.valid) {
      io.output.valid := true.B
      io.output.bits := aIntermed.bits
      io.error := aError || bError
    }.elsewhen (bIntermed.valid) {
      io.output.valid := true.B
      io.output.bits := bIntermed.bits
      io.error := aError || bError
    }.otherwise {
      io.output.valid := false.B
      io.output.bits := DontCare
      io.error := aError || bError
    }
  }
}
