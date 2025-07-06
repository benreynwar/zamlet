package fmvpu.core

import chisel3._
import chisel3.util.log2Ceil
import chisel3.util.Valid

/** Arithmetic and logic unit (ALU) computation instruction.
  *
  * @param params FMVPU system parameters
  * @groupdesc Signals The actual hardware fields of the Bundle
  */
class ComputeInstr(params: FMVPUParams) extends Bundle {
  /** Operation mode
    * @group Signals
    */
  val mode = UInt(4.W)
  
  /** Source register 1 address
    * @group Signals
    */
  val src1 = UInt(log2Ceil(params.nDRF).W)
  
  /** Source register 2 address
    * @group Signals
    */
  val src2 = UInt(log2Ceil(params.nDRF).W)
  
  /** Destination register address
    * @group Signals
    */
  val dst = UInt(log2Ceil(params.nDRF).W)
}

/** Memory access instruction for load or store operations.
  *
  * @param params FMVPU system parameters
  * @groupdesc Signals The actual hardware fields of the Bundle
  */
class LoadOrStoreInstr(params: FMVPUParams) extends Bundle {
  /** Operation mode: 0 = store, 1 = load
    * @group Signals
    */
  val mode = UInt(1.W)
  
  /** Register address for load/store operation
    * @group Signals
    */
  val reg = UInt(log2Ceil(params.nDRF).W)
  
  /** Memory address for load/store operation
    * @group Signals
    */
  val addr = UInt(params.ddmAddrWidth.W)
}

/** Load instruction for moving data from DDM to register file.
  *
  * @param params FMVPU system parameters
  * @groupdesc Signals The actual hardware fields of the Bundle
  */
class LoadInstr(params: FMVPUParams) extends Bundle {
  /** @group Signals */ val reg = UInt(log2Ceil(params.nDRF).W)
  /** @group Signals */ val addr = UInt(params.ddmAddrWidth.W)
}

/** Store instruction for moving data from register file to DDM.
  *
  * @param params FMVPU system parameters
  * @groupdesc Signals The actual hardware fields of the Bundle
  */
class StoreInstr(params: FMVPUParams) extends Bundle {
  /** @group Signals */ val reg = UInt(log2Ceil(params.nDRF).W)
  /** @group Signals */ val addr = UInt(params.ddmAddrWidth.W)
}

/**
 * Send/Receive instruction for DDM-Network communication with TDM support
 * @param params FMVPU system parameters
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class SendReceiveInstr(params: FMVPUParams) extends Bundle {
  /** Operation mode: 0 = Send (DDM to network), 1 = Receive (network to DDM)
    * @group Signals
    */
  val mode = UInt(1.W)
  
  /** Number of data words to transfer
    * @group Signals
    */
  val length = UInt(params.ddmAddrWidth.W)
  
  /** Source address in local DDM for Send operations (unused for Receive)
    * @group Signals
    */
  val srcAddr = UInt(params.ddmAddrWidth.W)
  
  /** Destination address: remote location for Send operations, local DDM for Receive operations
    * @group Signals
    */
  val dstAddr = UInt((params.ddmAddrWidth + 1).W)
  
  /** What channel a Send instruction will send the packet over.
    * @group Signals
    */
  val channel = UInt(log2Ceil(params.nChannels).W)

  /** For a Receive instruction what 'ident' the packet will be
   *  tagged with.
    * @group Signals
    */
  val ident = UInt(params.networkIdentWidth.W)
  
  /** Destination X coordinate for packet generation (mode 0)
    * @group Signals
    */
  val destX = UInt(log2Ceil(params.nColumns).W)
  
  /** Destination Y coordinate for packet generation (mode 0)
    * @group Signals
    */
  val destY = UInt(log2Ceil(params.nRows).W)
  
  /** Use sender's X coordinate as destination X (mode 0)
    * @group Signals
    */
  val useSameX = Bool()
  
  /** Use sender's Y coordinate as destination Y (mode 0)
    * @group Signals
    */
  val useSameY = Bool()
}

class SendReceiveInstrResponse(params: FMVPUParams) extends Bundle {
  /** Indicates that a Send or Receive instruction has completed.
    * @group Signals
    */
  val mode = UInt(1.W)
  val ident = UInt(params.networkIdentWidth.W)
}

/** Network instruction union for routing control and slot configuration.
  *
  * This is a union where fields are interpreted based on instrType:
  * - instrType = 0: Permutation instruction (uses mode, src, dst)  
  * - instrType = 1: Set slow control slot (uses slot field)
  *
  * @param params FMVPU system parameters
  * @groupdesc Signals The actual hardware fields of the Bundle
  */
class NetworkInstr(params: FMVPUParams) extends Bundle {
  /** Instruction type: 0 = permutation, 1 = set slow control slot
    * @group Signals
    */
  val instrType = UInt(1.W)
  
  /** Union data field - interpretation depends on instrType
    * For permutation (instrType=0): Cat(dst, src, mode)
    * For set slot (instrType=1): slot
    * @group Signals
    */
  val data = UInt(scala.math.max(
    log2Ceil(params.depthNetworkConfig) + 2 * log2Ceil(params.nDRF),
    log2Ceil(params.nSlowNetworkControlSlots)
  ).W)
  
  // Helper methods to extract fields based on instruction type
  def mode = data(log2Ceil(params.nFastNetworkControlSlots) - 1, 0)
  def src = data(log2Ceil(params.depthNetworkConfig) + log2Ceil(params.nDRF) - 1, log2Ceil(params.depthNetworkConfig))
  def dst = data(log2Ceil(params.depthNetworkConfig) + 2 * log2Ceil(params.nDRF) - 1, log2Ceil(params.depthNetworkConfig) + log2Ceil(params.nDRF))
  def slot = data(log2Ceil(params.nSlowNetworkControlSlots) - 1, 0)
}

/** Configuration instruction for system setup.
  *
  * @param params FMVPU system parameters
  * @groupdesc Signals The actual hardware fields of the Bundle
  */
class ConfigInstr(params: FMVPUParams) extends Bundle {
  /** Source register address
    * @group Signals
    */
  val src = UInt(log2Ceil(params.nDRF).W)
  
  /** Destination register address
    * @group Signals
    */
  val dst = UInt(log2Ceil(params.nDRF).W)
}

/** Complete instruction bundle containing all instruction types.
  *
  * This bundle groups all possible instruction types that can be executed
  * by a lane. Each instruction type is wrapped in a Valid wrapper to indicate
  * whether that instruction is active in the current cycle.
  *
  * @param params FMVPU system parameters
  * @groupdesc Signals The actual hardware fields of the Bundle
  */
class Instr(params: FMVPUParams) extends Bundle {
  /** Arithmetic/logic computation instruction (when valid)
    * @group Signals
    */
  val compute = Valid(new ComputeInstr(params))
  
  /** Memory load/store instruction (when valid)
    * @group Signals
    */
  val loadstore = Valid(new LoadOrStoreInstr(params))
  
  /** Network configuration instruction (when valid)
    * @group Signals
    */
  val network = Valid(new NetworkInstr(params))
  
  /** Send/receive instruction for DDM-network communication (when valid)
    * @group Signals
    */
  val sendreceive = Valid(new SendReceiveInstr(params))
}

/** Network configuration control signals.
  *
  * This bundle contains configuration parameters that control network
  * behavior and timing characteristics.
  *
  * @param params FMVPU system parameters
  * @groupdesc Signals The actual hardware fields of the Bundle
  */
class Config(params: FMVPUParams) extends Bundle {
  /** Configuration valid signal - indicates configuration is active
    * @group Signals
    */
  val configValid = Bool()
  
  /** Packet mode enable - true for packet switching, false for circuit switching
    * @group Signals
    */
  val configIsPacketMode = Bool()
  
  /** Network delay configuration in clock cycles
    * @group Signals
    */
  val configDelay = UInt(log2Ceil(params.networkMemoryDepth + 1).W)
}
