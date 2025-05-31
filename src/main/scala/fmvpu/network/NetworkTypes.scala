package fmvpu.network

import chisel3._
import chisel3.util.log2Ceil
import fmvpu.core.FMPVUParams

/**
 * Network routing direction constants and utilities
 * 
 * Defines the four cardinal directions plus a local "HERE" destination
 * for packet routing in a 2D mesh network. Uses X-Y routing where
 * packets first route in the X direction, then Y direction.
 */
object NetworkDirection {
  /** North direction (decreasing Y coordinate) */
  val NORTH = 0.U(3.W)
  /** South direction (increasing Y coordinate) */
  val SOUTH = 1.U(3.W)  
  /** West direction (decreasing X coordinate) */
  val WEST = 2.U(3.W)
  /** East direction (increasing X coordinate) */
  val EAST = 3.U(3.W)
  /** Local destination (packet has reached its target) */
  val HERE = 4.U(3.W)

  /** Type for cardinal directions only (2 bits, values 0-3) */
  type Direction = UInt
  /** Type for directions including local destination (3 bits, values 0-4) */
  type DirectionOrHere = UInt

  /** Create a Direction type (2 bits) */
  def Direction(): UInt = UInt(2.W)
  /** Create a DirectionOrHere type (3 bits) */
  def DirectionOrHere(): UInt = UInt(3.W)

  /**
   * Round-robin direction iterator for arbitration
   * @param current Current direction
   * @return Next direction in sequence: NORTH -> SOUTH -> WEST -> EAST -> HERE -> NORTH
   */
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
      result := NORTH  // Default for invalid values
    }
    result
  }
}

/**
 * 2D coordinate location in the mesh network
 * @param params FMPVU parameters containing grid dimensions
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class Location(params: FMPVUParams) extends Bundle {
  /** X coordinate (column) in the mesh network
    * @group Signals
    */
  val x = UInt(log2Ceil(params.nColumns).W)
  /** Y coordinate (row) in the mesh network
    * @group Signals
    */
  val y = UInt(log2Ceil(params.nRows).W)
}

/**
 * Packet header containing routing and memory access information
 * 
 * The header is transmitted as the first word of each packet and contains
 * all information needed for routing and memory access.
 * 
 * @param params FMPVU parameters for sizing fields
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class Header(params: FMPVUParams) extends Bundle {
  /** Destination location in the mesh network
    * @group Signals
    */
  val dest = new Location(params)
  /** Memory address for DDM access at destination
    * @group Signals
    */
  val address = UInt(params.ddmAddrWidth.W)
  /** Number of data words following this header
    * @group Signals
    */
  val length = UInt(log2Ceil(params.maxPacketLength).W)
}

object Header {
  /**
   * Parse a header from raw bits
   * 
   * Requires input bits to be at least as wide as the header.
   * Will truncate if input is wider than needed.
   * 
   * @param bits Raw bits to parse as header (must be >= header width)
   * @param params FMPVU parameters for header sizing
   * @return Parsed Header bundle
   */
  def fromBits(bits: UInt, params: FMPVUParams): Header = {
    val header = Wire(new Header(params))
    val headerWidth = header.getWidth
    val bitsWidth = bits.getWidth
    
    require(bitsWidth >= headerWidth, s"Input bits ($bitsWidth) must be at least header width ($headerWidth)")
    header := bits(headerWidth-1, 0).asTypeOf(header)
    header
  }
}