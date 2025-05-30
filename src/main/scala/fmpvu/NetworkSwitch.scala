package fmpvu

import chisel3._
import chisel3.util.{log2Ceil, Valid, DecoupledIO, Cat}

object NetworkDirection {
  // Direction constants
  val NORTH = 0.U(3.W)
  val SOUTH = 1.U(3.W)  
  val WEST = 2.U(3.W)
  val EAST = 3.U(3.W)
  val HERE = 4.U(3.W)

  // Type aliases for clarity
  type Direction = UInt  // 2 bits for NORTH, SOUTH, WEST, EAST (0-3)
  type DirectionOrHere = UInt  // 3 bits for directions including HERE (0-4)

  def Direction(): UInt = UInt(2.W)
  def DirectionOrHere(): UInt = UInt(3.W)

  def nextDirection(current: UInt): UInt = {
    val result = Wire(UInt(3.W))
    when (current === NORTH) {
      result := SOUTH
    }.elsewhen (current === SOUTH) {
      result := WEST
    }.elsewhen (current === WEST) {
      result := EAST
    }.elsewhen (current === EAST) {
      result := HERE
    }.elsewhen (current === HERE) {
      result := NORTH
    }.otherwise {
      result := NORTH  // Default for invalid
    }
    result
  }
}

class Location(params: FMPVUParams) extends Bundle {
  val x = UInt(log2Ceil(params.nColumns).W)
  val y = UInt(log2Ceil(params.nRows).W)
}

class OutputState(params: FMPVUParams) extends Bundle {
  val input = NetworkDirection.DirectionOrHere()
  val active = Bool()
  val remaining = UInt(log2Ceil(params.maxPacketLength+1).W)
}

object OutputState {
  def apply(params: FMPVUParams): OutputState = {
    val state = Wire(new OutputState(params))
    state.input := DontCare
    state.active := false.B
    state.remaining := DontCare
    state
  }
}

class Header(params: FMPVUParams) extends Bundle {
  val dest = new Location(params)
  val address = UInt(params.ddmAddrWidth.W)
  val length = UInt(log2Ceil(params.maxPacketLength).W)
}

object Header {
  def fromBits(bits: UInt, params: FMPVUParams): Header = {
    val header = Wire(new Header(params))
    val headerWidth = header.getWidth
    val bitsWidth = bits.getWidth
    
    if (bitsWidth >= headerWidth) {
      header := bits(headerWidth-1, 0).asTypeOf(header)
    } else {
      val paddedBits = Cat(0.U((headerWidth - bitsWidth).W), bits)
      header := paddedBits.asTypeOf(header)
    }
    header
  }
}

class NetworkSwitch(params: FMPVUParams) extends Module {
  // This is a component of the network node that is responsible for implementing the
  // header based packet switching.

  val inputs = IO(Vec(4, new Bus(params.width)))
  val outputs = IO(Vec(4, Flipped(new Bus(params.width))))

  val thisLoc = IO(Input(new Location(params)))

  val toFifos = IO(Vec(4, DecoupledIO(new HeaderTag(UInt(params.width.W)))))
  val fromFifos = IO(Vec(4, Flipped(DecoupledIO(new HeaderTag(UInt(params.width.W))))))
  val fromDDM = IO(Flipped(DecoupledIO(new HeaderTag(UInt(params.width.W)))))
  val toDDM = IO(DecoupledIO(new HeaderTag(UInt(params.width.W))))


  // Combine fromFifos and fromDDM into a single Vec for easier processing
  val fromFifosAndDDM = Wire(Vec(5, Flipped(DecoupledIO(new HeaderTag(UInt(params.width.W))))))
  for (i <- 0 until 4) {
    fromFifosAndDDM(i) <> fromFifos(i)
  }
  fromFifosAndDDM(4) <> fromDDM

  // Convert ready/valid to token/valid before outputs
  val readyToToken = Seq.fill(4)(Module(new ReadyValidToTokenValid(new HeaderTag(UInt(params.width.W)), params.networkMemoryDepth)))

  // Combined the signals that can go to either the DDM or the directional outputs.
  // Makes expressing routing logic simpler.
  val toReadyToTokenAndDDM = Wire(Vec(5, Flipped(DecoupledIO(new HeaderTag(UInt(params.width.W))))))
  for (i <- 0 until 4) {
    toReadyToTokenAndDDM(i) <> readyToToken(i).input
  }
  toReadyToTokenAndDDM(4) <> toDDM

  val fromFifosAndDDMRegDirections = Reg(Vec(5, NetworkDirection.DirectionOrHere()))
  val fromFifosAndDDMDirections = Wire(Vec(5, NetworkDirection.DirectionOrHere()))
  
  // Routes packets based on X-Y routing algorithm
  // Routes in X direction first, then Y direction
  def getDirection(thisLoc: Location, data: UInt): UInt = {
    val result = Wire(UInt(3.W))
    val header = Header.fromBits(data, params)
    val destLoc = header.dest
    
    // X-Y routing: route in X direction first, then Y
    when (thisLoc.x > destLoc.x) {
      result := NetworkDirection.WEST
    }.elsewhen (thisLoc.x < destLoc.x) {
      result := NetworkDirection.EAST
    }.otherwise {
      // X coordinates match, route in Y direction
      when (thisLoc.y > destLoc.y) {
        result := NetworkDirection.NORTH
      }.elsewhen (thisLoc.y < destLoc.y) {
        result := NetworkDirection.SOUTH
      }.otherwise {
        // Both coordinates match - destination is here
        result := NetworkDirection.HERE
      }
    }
    result
  }
  
  // Calculate routing directions and packet lengths for all inputs
  for (i <- 0 until 5) {
    when (fromFifosAndDDM(i).bits.header) {
      fromFifosAndDDMRegDirections(i) := getDirection(thisLoc, fromFifosAndDDM(i).bits.bits)
      fromFifosAndDDMDirections(i) := getDirection(thisLoc, fromFifosAndDDM(i).bits.bits)
    }.otherwise {
      fromFifosAndDDMDirections(i) := fromFifosAndDDMRegDirections(i);
    }
  }

  // Convert input token-valid interfaces to ready-valid for processing
  for (srcDirection <- 0 until 4) {
    val tokenToReady = Module(new TokenValidToReadyValid(new HeaderTag(UInt(params.width.W)), params.networkMemoryDepth))
    tokenToReady.input <> inputs(srcDirection)
    toFifos(srcDirection) <> tokenToReady.output
  }


  // Output state for each destination (4 directions + DDM)
  val state = RegInit(VecInit(Seq.fill(5)(OutputState(params))))
  val choice = Wire(Vec(5, NetworkDirection.DirectionOrHere()))

  // Round-robin arbitration and packet switching logic for each output
  for (dstDirection <- 0 until 5) {
    val nextState = Wire(new OutputState(params))
    state(dstDirection) := nextState
    
    // Round-robin input selection starting from last served input
    val lastInput = state(dstDirection).input
    val inputOrder = (0 until 5).map(i => (lastInput + 1.U + i.U) % 5.U)
    
    // Check which inputs have valid headers for this output
    val validHeaders = Wire(Vec(5, Bool()))
    for (i <- 0 until 5) {
      val input = fromFifosAndDDM(i)
      validHeaders(i) := input.valid && input.bits.header && 
                        getDirection(thisLoc, input.bits.bits) === dstDirection.U
    }
    
    // Find first valid input in round-robin order
    val availableHeader = Wire(Bool())
    availableHeader := validHeaders.asUInt.orR
    choice(dstDirection) := state(dstDirection).input
    
    // Priority encoder for round-robin selection
    for (i <- 0 until 5) {
      val inputIdx = inputOrder(i)
      when (validHeaders(inputIdx) && toReadyToTokenAndDDM(inputIdx).ready) {
        choice(dstDirection) := inputIdx
      }
    }

    // State machine: idle -> active (on header) -> idle (when packet complete)
    nextState := state(dstDirection)
    when (!state(dstDirection).active) {
      // Start new packet if header available
      when (availableHeader) {
        nextState.input := choice(dstDirection)
        nextState.active := true.B
        nextState.remaining := Header.fromBits(fromFifosAndDDM(choice(dstDirection)).bits.bits, params).length
      }
    }.otherwise {
      // Continue active packet
      val activeInput = fromFifosAndDDM(state(dstDirection).input)
      when (activeInput.valid && activeInput.ready) {
        when (!activeInput.bits.header) {
          // Data transfer - decrement remaining count
          when (state(dstDirection).remaining === 1.U) {
            nextState.active := false.B
          }
          nextState.remaining := state(dstDirection).remaining - 1.U
        }
      }
    }

    // Connect active input to output
    when (state(dstDirection).active || availableHeader) {
      val selectedInput = Mux(state(dstDirection).active, 
                              state(dstDirection).input, 
                              choice(dstDirection))
      toReadyToTokenAndDDM(dstDirection).valid := fromFifosAndDDM(selectedInput).valid
      toReadyToTokenAndDDM(dstDirection).bits := fromFifosAndDDM(selectedInput).bits
    }.otherwise {
      toReadyToTokenAndDDM(dstDirection).valid := false.B
      toReadyToTokenAndDDM(dstDirection).bits := DontCare
    }

  }


  // Connect input ready signals based on arbitration results
  for (srcDirection <- 0 until 5) {
    val dstDirection = fromFifosAndDDMDirections(srcDirection)
    val isChosen = choice(dstDirection) === srcDirection.U
    val isActive = state(dstDirection).active && (state(dstDirection).input === srcDirection.U)
    
    when ((!state(dstDirection).active && isChosen) || isActive) {
      fromFifosAndDDM(srcDirection).ready := toReadyToTokenAndDDM(dstDirection).ready
    }.otherwise {
      fromFifosAndDDM(srcDirection).ready := false.B
    }
  }

  for (dstDirection <- 0 until 4) {
    readyToToken(dstDirection).output <> outputs(dstDirection)
  }

}
