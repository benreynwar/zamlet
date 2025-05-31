package fmvpu.core

import chisel3._
import chisel3.util.log2Ceil
import chisel3.util.Valid

class ComputeInstr(params: FMPVUParams) extends Bundle {
  val mode = UInt(4.W)
  val src1 = UInt(log2Ceil(params.nDRF).W)
  val src2 = UInt(log2Ceil(params.nDRF).W)
  val dst = UInt(log2Ceil(params.nDRF).W)
}

class LoadOrStoreInstr(params: FMPVUParams) extends Bundle {
  val mode = UInt(1.W)
  val reg = UInt(log2Ceil(params.nDRF).W)
  val addr = UInt(params.ddmAddrWidth.W)
}

class LoadInstr(params: FMPVUParams) extends Bundle {
  val reg = UInt(log2Ceil(params.nDRF).W)
  val addr = UInt(params.ddmAddrWidth.W)
}

class StoreInstr(params: FMPVUParams) extends Bundle {
  val reg = UInt(log2Ceil(params.nDRF).W)
  val addr = UInt(params.ddmAddrWidth.W)
}

/**
 * Send/Receive instruction for DDM-Network communication with TDM support
 * @param params FMPVU system parameters
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class SendReceiveInstr(params: FMPVUParams) extends Bundle {
  /** Operation mode: 0 = Send (DDM to network), 1 = Receive (network to DDM)
    * @group Signals
    */
  val mode = UInt(1.W)
  
  /** Number of data words to transfer
    * @group Signals
    */
  val length = UInt(params.ddmAddrWidth.W)
  
  /** Starting address in DDM for the transfer
    * @group Signals
    */
  val addr = UInt(params.ddmAddrWidth.W)
  
  /** Time slot offset - number of cycles to wait before using first assigned slot
    * @group Signals
    */
  val slotOffset = UInt(params.ddmAddrWidth.W)
  
  /** Time slot spacing - interval between assigned network time slots for this node
    * @group Signals
    */
  val slotSpacing = UInt(params.ddmAddrWidth.W)
}

class NetworkInstr(params: FMPVUParams) extends Bundle {
  val mode = UInt(log2Ceil(params.depthNetworkConfig).W)
  val src = UInt(log2Ceil(params.nDRF).W)
  val dst = UInt(log2Ceil(params.nDRF).W)
}

class ConfigInstr(params: FMPVUParams) extends Bundle {
  val src = UInt(log2Ceil(params.nDRF).W)
  val dst = UInt(log2Ceil(params.nDRF).W)
}

// When a mode is read it specifies how the network should be configured on each clock cycle.

class Instr(params: FMPVUParams) extends Bundle {
  val compute = Valid(new ComputeInstr(params))
  val loadstore = Valid(new LoadOrStoreInstr(params))
  val network = Valid(new NetworkInstr(params))
  val sendreceive = Valid(new SendReceiveInstr(params))
}

class Config(params: FMPVUParams) extends Bundle {
  val configValid = Bool()
  val configIsPacketMode = Bool()
  val configDelay = UInt(log2Ceil(params.networkMemoryDepth + 1).W)
}