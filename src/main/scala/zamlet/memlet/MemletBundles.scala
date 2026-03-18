package zamlet.memlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.MessageType

object MemletResponseType extends ChiselEnum {
  val ReadLine = Value(0.U)
  val WlrlRead = Value(1.U)
}

// Inter-slice propagation: ident allocation (outward from slice 0)
class IdentAllocEvent(params: ZamletParams) extends Bundle {
  val slotIdx = UInt(log2Ceil(params.nMemletGatheringSlots).W)
  val ident = UInt(params.identWidth.W)
}

// Inter-slice propagation: all local jamlets arrived (inward toward slice 0)
// Sent once per slot when all of a slice's local jamlets have sent data.
// Slice 0 counts these per slot to determine allArrived.

// Inter-slice propagation: response buffer metadata (outward from slice 0)
// Shared wires: isSendable=false for Allocate, isSendable=true for Sendable.
// ident/sramAddr/responseType are don't-care when isSendable=true.
class ResponseMetaEvent(params: ZamletParams) extends Bundle {
  val isSendable = Bool()
  val slotIdx = UInt(log2Ceil(params.nResponseBufferSlots).W)
  val ident = UInt(params.identWidth.W)
  val sramAddr = UInt(params.sramAddrWidth.W)
  val responseType = MemletResponseType()
}

// Read line queue entry (slice 0 → MemoryEngine)
class ReadLineEntry(params: ZamletParams) extends Bundle {
  val ident = UInt(params.identWidth.W)
  val sramAddr = UInt(params.sramAddrWidth.W)
  val memAddr = UInt(params.wordWidth.W)
}

// Gathering slot metadata (authoritative, at slice 0)
class GatheringSlotMeta(params: ZamletParams) extends Bundle {
  val ident = UInt(params.identWidth.W)
  val sramAddr = UInt(params.sramAddrWidth.W)
  val writeAddr = UInt(params.wordWidth.W)
  val readAddr = UInt(params.wordWidth.W)
  val needsRead = Bool()
}

// Gathering slot data read port (from slice's perspective)
class GatheringDataReadPort(params: ZamletParams) extends Bundle {
  val slotIdx = Input(UInt(log2Ceil(params.nMemletGatheringSlots).W))
  val wordIdx = Input(UInt(log2Ceil(params.memletLocalWords).W))
  val data = Output(UInt(params.wordWidth.W))
}

// Gathering slot metadata read port (from slice 0's perspective)
class GatheringMetaReadPort(params: ZamletParams) extends Bundle {
  val slotIdx = Input(UInt(log2Ceil(params.nMemletGatheringSlots).W))
  val meta = Output(new GatheringSlotMeta(params))
}

// Response buffer data write (MemoryEngine → slice)
class ResponseDataWrite(params: ZamletParams) extends Bundle {
  val slotIdx = UInt(log2Ceil(params.nResponseBufferSlots).W)
  val localDataIdx = UInt(log2Ceil(params.memletLocalWords).W)
  val data = UInt(params.wordWidth.W)
}

// WriteLineResp entry (MemoryEngine → slice 0)
class WriteLineRespEntry(params: ZamletParams) extends Bundle {
  val ident = UInt(params.identWidth.W)
}

// Drop queue entry
class DropEntry(params: ZamletParams) extends Bundle {
  val messageType = MessageType()
  val ident = UInt(params.identWidth.W)
  val targetX = UInt(params.xPosWidth.W)
  val targetY = UInt(params.yPosWidth.W)
}
