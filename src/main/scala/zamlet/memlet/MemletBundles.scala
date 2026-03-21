package zamlet.memlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.network.MessageType

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
  val slotIdx = UInt(log2Ceil(params.nMemletGatheringSlots).W)
  val ident = UInt(params.identWidth.W)
  val sramAddr = UInt(params.sramAddrWidth.W)
  val sourceX = UInt(params.xPosWidth.W)
  val sourceY = UInt(params.yPosWidth.W)
  val writeAddr = UInt(params.wordWidth.W)
  val readAddr = UInt(params.wordWidth.W)
  val writes = Bool()
  val reads = Bool()
}

// Per-slice gathering data read (Decoupled req in, Decoupled resp out)
class GatheringDataReadSliceReq(params: ZamletParams) extends Bundle {
  val slotIdx = UInt(log2Ceil(params.nMemletGatheringSlots).W)
  val wordIdx = UInt(log2Ceil(params.memletLocalWords).W)
}

// Gathering data read request (MemoryEngine → Memlet top, includes routerIdx)
class GatheringDataReadReq(params: ZamletParams) extends Bundle {
  val routerIdx = UInt(log2Ceil(params.nMemletRouters).W)
  val slotIdx = UInt(log2Ceil(params.nMemletGatheringSlots).W)
  val wordIdx = UInt(log2Ceil(params.memletLocalWords).W)
}

// Response buffer data write (MemoryEngine → slice)
class ResponseDataWrite(params: ZamletParams) extends Bundle {
  val slotIdx = UInt(log2Ceil(params.nResponseBufferSlots).W)
  val localDataIdx = UInt(log2Ceil(params.memletLocalWords).W)
  val data = UInt(params.wordWidth.W)
}

// AXI4 channel bundles (no diplomacy)
class AXI4AddrChannel(addrBits: Int, idBits: Int) extends Bundle {
  val id = UInt(idBits.W)
  val addr = UInt(addrBits.W)
  val len = UInt(8.W)
  val size = UInt(3.W)
  val burst = UInt(2.W)
}

class AXI4WriteDataChannel(dataBits: Int) extends Bundle {
  val data = UInt(dataBits.W)
  val strb = UInt((dataBits / 8).W)
  val last = Bool()
}

class AXI4WriteRespChannel(idBits: Int) extends Bundle {
  val id = UInt(idBits.W)
  val resp = UInt(2.W)
}

class AXI4ReadDataChannel(dataBits: Int, idBits: Int) extends Bundle {
  val id = UInt(idBits.W)
  val data = UInt(dataBits.W)
  val resp = UInt(2.W)
  val last = Bool()
}

class AXI4MasterIO(addrBits: Int, dataBits: Int, idBits: Int) extends Bundle {
  val aw = Decoupled(new AXI4AddrChannel(addrBits, idBits))
  val w = Decoupled(new AXI4WriteDataChannel(dataBits))
  val b = Flipped(Decoupled(new AXI4WriteRespChannel(idBits)))
  val ar = Decoupled(new AXI4AddrChannel(addrBits, idBits))
  val r = Flipped(Decoupled(new AXI4ReadDataChannel(dataBits, idBits)))
}
