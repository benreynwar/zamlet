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

  /** Cast kinstr to LoadImmInstr */
  def asLoadImm(params: LamletParams, kinstr: UInt): LoadImmInstr = {
    kinstr.asTypeOf(new LoadImmInstr(params))
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
  val LoadImm = Value(6.U)
  val WriteParam = Value(7.U)
  val StoreScalar = Value(8.U)

  // Force 6-bit width by defining max value
  val Reserved63 = Value(63.U)
}

/** Width of parameter memory index */
object KInstrParamIdx {
  val width = 4
  val numEntries = 1 << width
}

/**
 * Kinstr bundled with resolved param memory values.
 * Used for kamlet-to-jamlet dispatch where params have been looked up.
 */
class KinstrWithParams(params: LamletParams) extends Bundle {
  val kinstr = UInt(KInstr.width.W)
  val param0 = UInt(params.memAddrWidth.W)
  val param1 = UInt(params.memAddrWidth.W)
  val param2 = UInt(params.memAddrWidth.W)
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

/**
 * LoadImm instruction format - write 32 bits of immediate data to RF.
 * Used for scalar memory loads where data is embedded in the instruction.
 *
 * To write a full word, send (wordBytes/4) LoadImm instructions, one per section.
 * For 64-bit words: 2 sections (lower=0, upper=1)
 *
 * Layout (64 bits total):
 *   opcode:    6 bits  - KInstrOpcode.LoadImm
 *   jInKIndex: log2(jInK) bits - which jamlet in this kamlet
 *   rfAddr:    6 bits  - destination word in RfSlice
 *   section:   log2(wordBytes/4) bits - which 32-bit section of the word
 *   byteMask:  4 bits  - which bytes of the 32-bit section to write
 *   data:      32 bits - data to write
 *   reserved:  remaining bits
 */
class LoadImmInstr(params: LamletParams) extends Bundle {
  private val usedBits = KInstr.opcodeWidth + log2Ceil(params.jInK) +
                         params.rfAddrWidth + log2Ceil(params.wordBytes / 4) + 4 + 32
  require(usedBits <= KInstr.width, s"LoadImmInstr uses $usedBits bits but KInstr.width is ${KInstr.width}")

  val opcode = KInstrOpcode()
  val jInKIndex = UInt(log2Ceil(params.jInK).W)
  val rfAddr = params.rfAddr()
  val section = UInt(log2Ceil(params.wordBytes / 4).W)
  val byteMask = UInt(4.W)
  val data = UInt(32.W)
  val reserved = UInt((KInstr.width - usedBits).W)
}

/**
 * WriteParam instruction format - write 48 bits to parameter memory.
 * Used to set up addresses/strides/nElements before load/store instructions.
 *
 * Layout (64 bits total):
 *   opcode:    6 bits  - KInstrOpcode.WriteParam
 *   paramIdx:  4 bits  - which param memory entry to write
 *   data:      48 bits - data to write (fits memAddrWidth)
 *   reserved:  6 bits
 */
class WriteParamInstr extends Bundle {
  private val usedBits = KInstr.opcodeWidth + KInstrParamIdx.width + 48
  require(usedBits <= KInstr.width, s"WriteParamInstr uses $usedBits bits but KInstr.width is ${KInstr.width}")

  val opcode = KInstrOpcode()
  val paramIdx = UInt(KInstrParamIdx.width.W)
  val data = UInt(48.W)
  val reserved = UInt((KInstr.width - usedBits).W)
}

/**
 * StoreScalar instruction format - store from VRF to scalar memory.
 * Used for vector stores to non-VPU memory addresses.
 *
 * The base physical address is read from param memory (baseAddrIdx).
 * For unit-stride ew=64: element i goes to addr = base + (startIndex + i) * 8
 *
 * Layout (64 bits total):
 *   opcode:      6 bits  - KInstrOpcode.StoreScalar
 *   dataReg:     6 bits  - source RF register (vs)
 *   baseAddrIdx: 4 bits  - param memory index for base paddr
 *   startIndex:  16 bits - starting element index
 *   nElements:   16 bits - number of elements to store
 *   reserved:    16 bits
 */
class StoreScalarInstr(params: LamletParams) extends Bundle {
  private val usedBits = KInstr.opcodeWidth + params.rfAddrWidth + KInstrParamIdx.width + 16 + 16
  require(usedBits <= KInstr.width, s"StoreScalarInstr uses $usedBits bits but KInstr.width is ${KInstr.width}")

  val opcode = KInstrOpcode()
  val dataReg = params.rfAddr()
  val baseAddrIdx = UInt(KInstrParamIdx.width.W)
  val startIndex = UInt(16.W)
  val nElements = UInt(16.W)
  val reserved = UInt((KInstr.width - usedBits).W)
}

