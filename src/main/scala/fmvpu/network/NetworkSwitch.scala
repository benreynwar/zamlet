package fmvpu.network

import chisel3._
import chisel3.util.{log2Ceil, Valid, DecoupledIO, Cat}
import fmvpu.core.FMVPUParams

/**
 * State tracking for each output port in the network switch
 * 
 * Tracks which input is currently being served and how much of the
 * current packet remains to be transmitted.
 * 
 * @param params FMVPU parameters for sizing fields
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class OutputState(params: FMVPUParams) extends Bundle {
  /** Which input direction is currently being served by this output
    * @group Signals
    */
  val input = NetworkDirection.DirectionOrHere()
  /** Whether this output is actively transmitting a packet
    * @group Signals
    */
  val active = Bool()
  /** Number of data words remaining in current packet
    * @group Signals
    */
  val remaining = UInt(log2Ceil(params.maxPacketLength+1).W)
}

object OutputState {
  /**
   * Create an initialized OutputState with safe default values
   * @param params FMVPU parameters
   * @return OutputState with active=false and other fields as DontCare
   */
  def apply(params: FMVPUParams): OutputState = {
    val state = Wire(new OutputState(params))
    state.input := DontCare
    state.active := false.B
    state.remaining := DontCare
    state
  }
}


/**
 * Packet-switched network router for 2D mesh network
 * 
 * This module implements a header-based packet switching router that:
 * - Routes packets using X-Y routing algorithm (X first, then Y)
 * - Provides round-robin arbitration between inputs competing for same output
 * - Maintains packet boundaries and flow control
 * - Converts between token-valid (network) and ready-valid (local) protocols
 * - Supports local DDM (Distributed Data Memory) access
 * 
 * The router has 4 directional ports (NORTH, SOUTH, EAST, WEST) plus local DDM.
 * Each packet starts with a header containing destination coordinates, followed
 * by data words. The router examines headers to determine output direction and
 * switches complete packets atomically.
 * 
 * @param params FMVPU parameters containing network and memory configuration
 * @groupdesc Signals The actual hardware fields of the IO Bundle
 */
class NetworkSwitch(params: FMVPUParams) extends Module {
  val io = IO(new Bundle {
    /** Input ports from four cardinal directions using token-valid protocol
      * @group Signals
      */
    val inputs = Vec(4, new PacketInterface(params.width))
    
    /** Output ports to four cardinal directions using token-valid protocol
      * @group Signals
      */
    val outputs = Vec(4, Flipped(new PacketInterface(params.width)))
    
    /** This router's location in the mesh network for routing decisions
      * @group Signals
      */
    val thisLoc = Input(new Location(params))
    
    /** Output interfaces to local FIFOs (converted from token-valid inputs)
      * @group Signals
      */
    val toFifos = Vec(4, DecoupledIO(new HeaderTag(UInt(params.width.W))))
    
    /** Input interfaces from local FIFOs (to be converted to token-valid outputs)
      * @group Signals
      */
    val fromFifos = Vec(4, Flipped(DecoupledIO(new HeaderTag(UInt(params.width.W)))))
    
    /** Input from local Distributed Data Memory
      * @group Signals
      */
    val fromDDM = Flipped(DecoupledIO(new HeaderTag(UInt(params.width.W))))
    
    /** Output to local Distributed Data Memory
      * @group Signals
      */
    val toDDM = DecoupledIO(new HeaderTag(UInt(params.width.W)))
  })


  // Combine fromFifos and fromDDM into a single Vec for easier processing
  val fromFifosAndDDM = Wire(Vec(5, Flipped(DecoupledIO(new HeaderTag(UInt(params.width.W))))))
  for (i <- 0 until 4) {
    fromFifosAndDDM(i) <> io.fromFifos(i)
  }
  fromFifosAndDDM(4) <> io.fromDDM

  // Convert ready/valid to token/valid before outputs
  val readyToToken = Seq.fill(4)(Module(new ReadyValidToTokenValid(new HeaderTag(UInt(params.width.W)), params.networkMemoryDepth)))

  // Combine outputs to directions and DDM for uniform processing
  val toReadyToTokenAndDDM = Wire(Vec(5, Flipped(DecoupledIO(new HeaderTag(UInt(params.width.W))))))
  for (i <- 0 until 4) {
    toReadyToTokenAndDDM(i) <> readyToToken(i).input
  }
  toReadyToTokenAndDDM(4) <> io.toDDM

  // Track routing directions for each input (cached for non-header words)
  val fromFifosAndDDMRegDirections = Reg(Vec(5, NetworkDirection.DirectionOrHere()))
  val fromFifosAndDDMDirections = Wire(Vec(5, NetworkDirection.DirectionOrHere()))
  
  /**
   * Compute routing direction using X-Y routing algorithm
   * 
   * Routes in X direction first (EAST/WEST), then Y direction (NORTH/SOUTH).
   * Packets always make progress toward their destination in a deterministic order.
   * 
   * @param thisLoc Current router's location in the mesh
   * @param data Header word containing destination coordinates
   * @return Direction to route packet (NORTH/SOUTH/EAST/WEST/HERE)
   */
  def getDirection(thisLoc: Location, data: UInt): UInt = {
    val header = Header.fromBits(data, params)
    val destLoc = header.dest
    val direction = Wire(UInt(3.W))
    
    // X-Y routing: route in X direction first, then Y
    when (thisLoc.x > destLoc.x) {
      direction := NetworkDirection.WEST
    }.elsewhen (thisLoc.x < destLoc.x) {
      direction := NetworkDirection.EAST
    }.otherwise {
      // X coordinates match, route in Y direction
      when (thisLoc.y > destLoc.y) {
        direction := NetworkDirection.NORTH
      }.elsewhen (thisLoc.y < destLoc.y) {
        direction := NetworkDirection.SOUTH
      }.otherwise {
        // Both coordinates match - destination is here
        direction := NetworkDirection.HERE
      }
    }
    direction
  }
  
  // Calculate routing directions for all inputs
  // For headers: compute direction from destination coordinates
  // For data: use cached direction from previous header
  for (i <- 0 until 5) {
    when (fromFifosAndDDM(i).bits.header) {
      fromFifosAndDDMRegDirections(i) := getDirection(io.thisLoc, fromFifosAndDDM(i).bits.bits)
      fromFifosAndDDMDirections(i) := getDirection(io.thisLoc, fromFifosAndDDM(i).bits.bits)
    }.otherwise {
      fromFifosAndDDMDirections(i) := fromFifosAndDDMRegDirections(i)
    }
  }

  // Convert input token-valid interfaces to ready-valid for processing
  for (srcDirection <- 0 until 4) {
    val tokenToReady = Module(new TokenValidToReadyValid(new HeaderTag(UInt(params.width.W)), params.networkMemoryDepth))
    tokenToReady.input <> io.inputs(srcDirection)
    io.toFifos(srcDirection) <> tokenToReady.output
  }


  // Output state tracking for packet switching
  val state = RegInit(VecInit(Seq.fill(5)(OutputState(params))))
  val choice = Wire(Vec(5, NetworkDirection.DirectionOrHere()))

  // Round-robin arbitration and packet switching logic for each output
  for (dstDirection <- 0 until 5) {
    val nextState = Wire(new OutputState(params))
    state(dstDirection) := nextState
    
    // Round-robin input selection starting from last served input
    val lastInput = state(dstDirection).input
    val inputOrder = (0 until 5).map(i => (lastInput + 1.U + i.U) % 5.U)
    
    // Check which inputs have valid headers targeting this output
    val validHeaders = Wire(Vec(5, Bool()))
    for (i <- 0 until 5) {
      val input = fromFifosAndDDM(i)
      validHeaders(i) := input.valid && input.bits.header &&
                        getDirection(io.thisLoc, input.bits.bits) === dstDirection.U
    }
    
    val availableHeader = validHeaders.asUInt.orR
    choice(dstDirection) := state(dstDirection).input
    
    // Select first available input in round-robin order
    for (i <- 0 until 5) {
      val inputIdx = inputOrder(i)
      when (validHeaders(inputIdx) && toReadyToTokenAndDDM(dstDirection).ready) {
        choice(dstDirection) := inputIdx
      }
    }

    // Packet switching state machine
    nextState := state(dstDirection)
    when (!state(dstDirection).active) {
      // Idle: start new packet when header arrives
      when (availableHeader) {
        nextState.input := choice(dstDirection)
        nextState.active := true.B
        nextState.remaining := Header.fromBits(fromFifosAndDDM(choice(dstDirection)).bits.bits, params).length
      }
    }.otherwise {
      // Active: continue current packet until complete
      val activeInput = fromFifosAndDDM(state(dstDirection).input)
      when (activeInput.valid && activeInput.ready && !activeInput.bits.header) {
        // Data word transferred - decrement remaining count
        when (state(dstDirection).remaining === 1.U) {
          nextState.active := false.B  // Packet complete
        }
        nextState.remaining := state(dstDirection).remaining - 1.U
      }
    }

    // Connect selected input to output
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
  // An input is ready when it's either chosen for new packet or actively transmitting
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

  // Connect converted outputs to external token-valid interfaces
  for (dstDirection <- 0 until 4) {
    readyToToken(dstDirection).output <> io.outputs(dstDirection)
  }

}
