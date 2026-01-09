package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.LamletParams

/**
 * Kamlet instruction format definitions.
 *
 * KInstr is a 64-bit packed instruction format used for network communication.
 * Large values (addresses, strides, nElements) are stored in a parameter memory
 * and referenced by 4-bit indices.
 *
 * Python reference: python/zamlet/kamlet/kinstructions.py
 * Address types: python/zamlet/addresses.py (KMAddr, RegAddr)
 */

/** KInstr constants and utilities */
object KInstr {
  val width = 64           // Total kinstr width in bits
  val opcodeWidth = 6      // Opcode field width
  val syncIdentWidth = 8   // Sync ident field width
  val syncValueWidth = 8   // Sync value field width

  /** Cast kinstr to J2JInstr */
  def asJ2J(params: LamletParams, kinstr: UInt): J2JInstr = {
    kinstr.asTypeOf(new J2JInstr(params))
  }

  /** Cast kinstr to StridedInstr */
  def asStrided(params: LamletParams, kinstr: UInt): StridedInstr = {
    kinstr.asTypeOf(new StridedInstr(params))
  }

  /** Cast kinstr to IndexedInstr */
  def asIndexed(params: LamletParams, kinstr: UInt): IndexedInstr = {
    kinstr.asTypeOf(new IndexedInstr(params))
  }

  /** Cast kinstr to WordInstr */
  def asWord(params: LamletParams, kinstr: UInt): WordInstr = {
    kinstr.asTypeOf(new WordInstr(params))
  }
}

/** KInstr opcode enumeration (6 bits) */
object KInstrOpcode extends ChiselEnum {
  val SyncTrigger = Value(0.U)
  val IdentQuery = Value(1.U)
  val LoadJ2J = Value(2.U)
  val StoreJ2J = Value(3.U)
  val LoadSimple = Value(4.U)
  val StoreSimple = Value(5.U)

  // Force 6-bit width by defining max value
  val Reserved63 = Value(63.U)
}

/** Width of parameter memory index */
object KInstrParamIdx {
  val width = 4
}

/**
 * Base instruction with opcode. Cast to specific type based on opcode.
 * Includes padding so opcode extracts from correct MSB position [63:58].
 */
class KInstrBase extends Bundle {
  val opcode = KInstrOpcode()
  val reserved = UInt((KInstr.width - KInstr.opcodeWidth).W)
}

/**
 * SyncTrigger instruction format.
 * Used for testing the instruction receive path and sync network.
 *
 * Layout (LSB first):
 *   [5:0]   opcode (= SyncTrigger)
 *   [13:6]  syncIdent
 *   [21:14] value
 *   [63:22] reserved
 */
class SyncTriggerInstr extends Bundle {
  val opcode = KInstrOpcode()
  val syncIdent = UInt(KInstr.syncIdentWidth.W)
  val value = UInt(KInstr.syncValueWidth.W)
  val reserved = UInt((KInstr.width - KInstr.opcodeWidth -
                       KInstr.syncIdentWidth - KInstr.syncValueWidth).W)
}

/**
 * IdentQuery instruction format.
 * Used by Lamlet to query kamlets for their oldest active ident.
 *
 * Layout (Bundle order = MSB first):
 *   opcode:     bits [63:58]  (6 bits)
 *   baseline:   bits [57:50]  (8 bits) - ident to measure distance from
 *   syncIdent:  bits [49:42]  (8 bits) - sync network identifier
 *   reserved:   bits [41:0]   (42 bits)
 */
class IdentQueryInstr extends Bundle {
  val opcode = KInstrOpcode()
  val baseline = UInt(KInstr.syncIdentWidth.W)
  val syncIdent = UInt(KInstr.syncIdentWidth.W)
  val reserved = UInt((KInstr.width - KInstr.opcodeWidth -
                       KInstr.syncIdentWidth - KInstr.syncIdentWidth).W)
}

/**
 * A location in a jamlet (k_index + j_in_k_index).
 * Python reference: derived from KMAddr/RegAddr k_index and j_in_k_index
 */
class JamletLoc(params: LamletParams) extends Bundle {
  val kIndex = UInt(log2Ceil(params.kInL).W)
  val jInKIndex = UInt(log2Ceil(params.jInK).W)
}

/**
 * Instruction format for LoadWord / StoreWord.
 *
 * Python reference: LoadWord/StoreWord in kinstructions.py
 * - regLoc: jamlet with the register file side
 * - memLoc: jamlet with the memory/cache side
 * Data flows mem→reg for load, reg→mem for store.
 */
class WordInstr(params: LamletParams) extends Bundle {
  val opcode = KInstrOpcode()
  val regLoc = new JamletLoc(params)
  val reg = params.rfAddr()
  val regOffsetInWord = UInt(log2Ceil(params.wordBytes).W)
  val memLoc = new JamletLoc(params)
  val memOffsetInWord = UInt(log2Ceil(params.wordBytes).W)
  val byteMask = UInt(params.wordBytes.W)
}

/**
 * Instruction format for LoadJ2JWords / StoreJ2JWords.
 *
 * Python reference: Load/Store with k_maddr in kinstructions.py
 * - reg: the RF register (dst for load, src for store)
 */
class J2JInstr(params: LamletParams) extends Bundle {
  val opcode = KInstrOpcode()
  val cacheSlot = params.cacheSlot()
  val memWordOrder = WordOrder()
  val rfWordOrder = WordOrder()
  val memEw = EwCode()
  val rfEw = EwCode()
  val baseBitAddr = UInt(log2Ceil(params.wordWidth * params.jInL).W)
  val startIndex = params.elementIndex()
  val nElementsIdx = UInt(KInstrParamIdx.width.W)
  val reg = params.rfAddr()
}

/**
 * Instruction format for strided operations (LoadStride / StoreStride).
 *
 * Python reference: Load/Store with stride_bytes in kinstructions.py
 * - reg: the RF data register (dst for load, src for store)
 *
 * Common fields (same position as IndexedInstr): opcode, startIndex, rfEw,
 * rfWordOrder, reg, maskReg, maskEnabled, baseAddrIdx, nElementsIdx
 */
class StridedInstr(params: LamletParams) extends Bundle {
  // Common fields (must match IndexedInstr layout)
  val opcode = KInstrOpcode()
  val startIndex = params.elementIndex()
  val rfEw = EwCode()
  val rfWordOrder = WordOrder()
  val reg = params.rfAddr()
  val maskReg = params.rfAddr()
  val maskEnabled = Bool()
  val baseAddrIdx = UInt(KInstrParamIdx.width.W)
  val nElementsIdx = UInt(KInstrParamIdx.width.W)
  // Strided-specific fields
  val strideBytesIdx = UInt(KInstrParamIdx.width.W)
}

/**
 * Instruction format for indexed operations (LoadIdxUnord / StoreIdxUnord / LoadIdxElement).
 * - reg: the RF data register (dst for load, src for store)
 *
 * Common fields (same position as StridedInstr): opcode, startIndex, rfEw,
 * rfWordOrder, reg, maskReg, maskEnabled, baseAddrIdx, nElementsIdx
 */
class IndexedInstr(params: LamletParams) extends Bundle {
  // Common fields (must match StridedInstr layout)
  val opcode = KInstrOpcode()
  val startIndex = params.elementIndex()
  val rfEw = EwCode()
  val rfWordOrder = WordOrder()
  val reg = params.rfAddr()
  val maskReg = params.rfAddr()
  val maskEnabled = Bool()
  val baseAddrIdx = UInt(KInstrParamIdx.width.W)
  val nElementsIdx = UInt(KInstrParamIdx.width.W)
  // Indexed-specific fields
  val indexEw = EwCode()
  val indexReg = params.rfAddr()
}

