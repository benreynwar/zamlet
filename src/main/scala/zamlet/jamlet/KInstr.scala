package zamlet.jamlet

import chisel3._
import chisel3.util._

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

/** Width of opcode field */
object KInstrOpcode {
  val width = 6
}

/** Width of parameter memory index */
object KInstrParamIdx {
  val width = 4
}

/**
 * Base instruction with opcode. Cast to specific type based on opcode.
 */
class KInstrBase extends Bundle {
  val opcode = UInt(KInstrOpcode.width.W)
}

/**
 * A location in a jamlet (k_index + j_in_k_index).
 * Python reference: derived from KMAddr/RegAddr k_index and j_in_k_index
 */
class JamletLoc(params: JamletParams) extends Bundle {
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
class WordInstr(params: JamletParams) extends Bundle {
  val opcode = UInt(KInstrOpcode.width.W)
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
class J2JInstr(params: JamletParams) extends Bundle {
  val opcode = UInt(KInstrOpcode.width.W)
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
class StridedInstr(params: JamletParams) extends Bundle {
  // Common fields (must match IndexedInstr layout)
  val opcode = UInt(KInstrOpcode.width.W)
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
class IndexedInstr(params: JamletParams) extends Bundle {
  // Common fields (must match StridedInstr layout)
  val opcode = UInt(KInstrOpcode.width.W)
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

object KInstr {
  val width = 64

  /** Cast kinstr to J2JInstr */
  def asJ2J(params: JamletParams, kinstr: UInt): J2JInstr = {
    kinstr.asTypeOf(new J2JInstr(params))
  }

  /** Cast kinstr to StridedInstr */
  def asStrided(params: JamletParams, kinstr: UInt): StridedInstr = {
    kinstr.asTypeOf(new StridedInstr(params))
  }

  /** Cast kinstr to IndexedInstr */
  def asIndexed(params: JamletParams, kinstr: UInt): IndexedInstr = {
    kinstr.asTypeOf(new IndexedInstr(params))
  }

  /** Cast kinstr to WordInstr */
  def asWord(params: JamletParams, kinstr: UInt): WordInstr = {
    kinstr.asTypeOf(new WordInstr(params))
  }
}
