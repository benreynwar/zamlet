package fmvpu.core

import chisel3._
import chisel3.util.log2Ceil
import chisel3.util.Valid

/** Arithmetic and logic unit (ALU) computation instruction.
  *
  * @param params FMVPU system parameters
  * @groupdesc Signals The actual hardware fields of the Bundle
  */
class ComputeInstr(params: FMPVUParams) extends Bundle {
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
class LoadOrStoreInstr(params: FMPVUParams) extends Bundle {
  /** Operation mode: 0 = load, 1 = store
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
class LoadInstr(params: FMPVUParams) extends Bundle {
  /** @group Signals */ val reg = UInt(log2Ceil(params.nDRF).W)
  /** @group Signals */ val addr = UInt(params.ddmAddrWidth.W)
}

/** Store instruction for moving data from register file to DDM.
  *
  * @param params FMVPU system parameters
  * @groupdesc Signals The actual hardware fields of the Bundle
  */
class StoreInstr(params: FMPVUParams) extends Bundle {
  /** @group Signals */ val reg = UInt(log2Ceil(params.nDRF).W)
  /** @group Signals */ val addr = UInt(params.ddmAddrWidth.W)
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

/** Network configuration instruction for routing control.
  *
  * @param params FMVPU system parameters
  * @groupdesc Signals The actual hardware fields of the Bundle
  */
class NetworkInstr(params: FMPVUParams) extends Bundle {
  /** Configuration mode index into network configuration table
    * @group Signals
    */
  val mode = UInt(log2Ceil(params.depthNetworkConfig).W)
  
  /** Source register address
    * @group Signals
    */
  val src = UInt(log2Ceil(params.nDRF).W)
  
  /** Destination register address
    * @group Signals
    */
  val dst = UInt(log2Ceil(params.nDRF).W)
}

/** Configuration instruction for system setup.
  *
  * @param params FMVPU system parameters
  * @groupdesc Signals The actual hardware fields of the Bundle
  */
class ConfigInstr(params: FMPVUParams) extends Bundle {
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
class Instr(params: FMPVUParams) extends Bundle {
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
class Config(params: FMPVUParams) extends Bundle {
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