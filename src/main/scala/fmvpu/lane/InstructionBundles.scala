package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Unresolved ALU instruction - contains register references that may not be ready
 */
class ALUInstrUnresolved(params: LaneParams) extends Bundle {
  val valid = Bool()
  val mode = ALUModes()
  val src1 = new RegReadInfo(params)
  val src2 = new RegReadInfo(params) 
  val accum = new RegReadInfo(params)
  val dstAddr = new RegWithIdent(params)
  val useLocalAccum = Bool()
}

/**
 * Resolved ALU instruction - all operands are ready data values
 */
class ALUInstrResolved(params: LaneParams) extends Bundle {
  val valid = Bool()
  val mode = ALUModes()
  val src1 = UInt(params.width.W)
  val src2 = UInt(params.width.W)
  val accum = UInt(params.width.W)
  val dstAddr = new RegWithIdent(params)
  val useLocalAccum = Bool()
}

/**
 * Unresolved Load/Store instruction
 */
class LdStInstrUnresolved(params: LaneParams) extends Bundle {
  val valid = Bool()
  val mode = LdStModes()
  val baseAddress = new RegReadInfo(params)
  val offset = new RegReadInfo(params)
  val dstAddr = new RegWithIdent(params)
  val value = new RegReadInfo(params) // For stores
}

/**
 * Resolved Load/Store instruction
 */
class LdStInstrResolved(params: LaneParams) extends Bundle {
  val valid = Bool()
  val mode = LdStModes()
  val baseAddress = UInt(params.addressWidth.W)
  val offset = UInt(params.addressWidth.W)
  val dstAddr = new RegWithIdent(params)
  val value = UInt(params.width.W) // For stores
}

/**
 * Unresolved Packet instruction
 */
class PacketInstrUnresolved(params: LaneParams) extends Bundle {
  val valid = Bool()
  val mode = PacketModes()
  val target = new RegReadInfo(params)
  val result = new RegWithIdent(params) // register to put length or word in
  val sendLength = new RegReadInfo(params)
  val channel = new RegReadInfo(params)
}

/**
 * Resolved Packet instruction
 */
class PacketInstrResolved(params: LaneParams) extends Bundle {
  val valid = Bool()
  val mode = PacketModes()
  val target = UInt(params.targetWidth.W)
  val result = new RegWithIdent(params)
  val sendLength = UInt(params.packetLengthWidth.W)
  val channel = UInt(2.W)
}