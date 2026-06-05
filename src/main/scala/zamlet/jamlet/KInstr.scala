package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.{ElementWidth, LaneOrder, Ordering, ZamletParams}

/**
 * Kamlet instruction format definitions.
 *
 * KInstr is a 64-bit packed instruction format used for network communication.
 * Large values are stored in parameter memory. Most packed instruction
 * parameter references carry only the low bits; decode supplies bank bits
 * based on whether the reference is a base address, start index, or end index.
 *
 * Python reference: python/zamlet/kamlet/kinstructions.py
 * Address types: python/zamlet/addresses.py (KMAddr, RegAddr)
 */

/** KInstr constants and utilities */
object KInstr {
  val width = 64           // Total kinstr width in bits
  val opcodeWidth = 6      // Opcode field width
  val syncValueWidth = 8   // Sync value field width

  private def paramRefBankWidth(params: ZamletParams): Int = {
    require(params.log2NParams >= params.paramRefIdxWidth,
      s"log2NParams (${params.log2NParams}) must be >= paramRefIdxWidth (${params.paramRefIdxWidth})")
    params.log2NParams - params.paramRefIdxWidth
  }

  private def paramRefToIndex(params: ZamletParams, bank: Int, ref: UInt): UInt = {
    val bankWidth = paramRefBankWidth(params)
    require(bank < (1 << bankWidth),
      s"parameter reference bank $bank does not fit in $bankWidth bits")
    Cat(bank.U(bankWidth.W), ref)
  }

  def baseAddrParamIdx(params: ZamletParams, ref: UInt): UInt = {
    paramRefToIndex(params, 0, ref)
  }

  def startIndexParamIdx(params: ZamletParams, ref: UInt): UInt = {
    paramRefToIndex(params, 1, ref)
  }

  def endIndexParamIdx(params: ZamletParams, ref: UInt): UInt = {
    paramRefToIndex(params, 2, ref)
  }

  /** Cast kinstr to J2JInstr */
  def asJ2J(params: ZamletParams, kinstr: UInt): J2JInstr = {
    kinstr.asTypeOf(new J2JInstr(params))
  }

  /** Cast kinstr to IndexedInstr */
  def asIndexed(params: ZamletParams, kinstr: UInt): IndexedInstr = {
    kinstr.asTypeOf(new IndexedInstr(params))
  }

  /** Cast kinstr to WordInstr */
  def asWord(params: ZamletParams, kinstr: UInt): WordInstr = {
    kinstr.asTypeOf(new WordInstr(params))
  }

  /** Cast kinstr to LoadImmInstr */
  def asLoadImm(params: ZamletParams, kinstr: UInt): LoadImmInstr = {
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
  val Add = Value(9.U)
  val Sub = Value(10.U)
  val Mul = Value(11.U)
  val MulHigh = Value(12.U)
  val LoadIdxUnord = Value(13.U)
  val StoreIdxUnord = Value(14.U)
  val Reserved15 = Value(15.U)
  val Reserved16 = Value(16.U)
  val Reserved17 = Value(17.U)
  val Reserved18 = Value(18.U)
  val Reserved19 = Value(19.U)
  val Reserved20 = Value(20.U)
  val Reserved21 = Value(21.U)
  val Reserved22 = Value(22.U)
  val Reserved23 = Value(23.U)
  val Reserved24 = Value(24.U)
  val Reserved25 = Value(25.U)
  val Reserved26 = Value(26.U)
  val Reserved27 = Value(27.U)
  val Reserved28 = Value(28.U)
  val Reserved29 = Value(29.U)
  val Reserved30 = Value(30.U)
  val Reserved31 = Value(31.U)
  val Reserved32 = Value(32.U)
  val Reserved33 = Value(33.U)
  val Reserved34 = Value(34.U)
  val Reserved35 = Value(35.U)
  val Reserved36 = Value(36.U)
  val Reserved37 = Value(37.U)
  val Reserved38 = Value(38.U)
  val Reserved39 = Value(39.U)
  val Reserved40 = Value(40.U)
  val Reserved41 = Value(41.U)
  val Reserved42 = Value(42.U)
  val Reserved43 = Value(43.U)
  val Reserved44 = Value(44.U)
  val Reserved45 = Value(45.U)
  val Reserved46 = Value(46.U)
  val Reserved47 = Value(47.U)
  val Reserved48 = Value(48.U)
  val Reserved49 = Value(49.U)
  val Reserved50 = Value(50.U)
  val Reserved51 = Value(51.U)
  val Reserved52 = Value(52.U)
  val Reserved53 = Value(53.U)
  val Reserved54 = Value(54.U)
  val Reserved55 = Value(55.U)
  val Reserved56 = Value(56.U)
  val Reserved57 = Value(57.U)
  val Reserved58 = Value(58.U)
  val Reserved59 = Value(59.U)
  val Reserved60 = Value(60.U)
  val Reserved61 = Value(61.U)
  val Reserved62 = Value(62.U)
  val Reserved63 = Value(63.U)
}

/**
 * Kinstr bundled with resolved param memory values.
 * Used for kamlet-to-jamlet dispatch where params have been looked up.
 */
class KinstrWithParams(params: ZamletParams) extends Bundle {
  val kinstr = UInt(KInstr.width.W)
  val ordering = new Ordering
  val cacheSlot = params.cacheSlot()
  val sramWordOffset = UInt(log2Ceil(params.cacheSlotWords).W)
  val param0 = UInt(params.memAddrWidth.W)
  val param1 = UInt(params.memAddrWidth.W)
  val param2 = UInt(params.memAddrWidth.W)
}

/**
 * Base instruction shared by all kamlet instructions.
 * Bundle fields are packed MSB first, so opcode remains at bits [63:58].
 */
abstract class AbstractKInstr(params: ZamletParams) extends Bundle {
  val opcode = KInstrOpcode()
  val instrIdent = params.ident()

  def baseWidth: Int = KInstr.opcodeWidth + params.identWidth
}

abstract class AbstractLocalKInstr(params: ZamletParams) extends AbstractKInstr(params)

class KInstrBase(params: ZamletParams) extends AbstractKInstr(params) {
  val reserved = UInt((KInstr.width - baseWidth).W)
}

/**
 * SyncTrigger instruction format.
 * Used for testing the instruction receive path and sync network.
 *
 * Layout (LSB first):
 *   opcode:     opcodeWidth bits - KInstrOpcode.SyncTrigger
 *   instrIdent: identWidth bits - instruction tracking identifier
 *   syncIdent:  syncIdentWidth bits - sync network identifier
 *   value:      syncValueWidth bits - sync value
 *   reserved:   remaining bits
 */
class SyncTriggerInstr(params: ZamletParams) extends AbstractKInstr(params) {
  val syncIdent = params.syncIdent()
  val value = UInt(KInstr.syncValueWidth.W)
  val reserved = UInt((KInstr.width - baseWidth -
                       params.syncIdentWidth - KInstr.syncValueWidth).W)
}

/**
 * IdentQuery instruction format.
 * Used by Lamlet to query kamlets for their oldest active ident.
 *
 * Layout (Bundle order = MSB first):
 *   opcode:     opcodeWidth bits - KInstrOpcode.IdentQuery
 *   instrIdent: identWidth bits - instruction tracking identifier
 *   syncIdent:  syncIdentWidth bits - sync network identifier
 *   mustDrainValid: 1 bit - delay local sync participation until mustDrainSyncIdent is drained
 *   mustDrainSyncIdent: syncIdentWidth bits - sync id that must be locally inactive
 *   baseline:   identWidth bits - instruction ident to measure distance from
 *   reserved:   remaining bits
 */
class IdentQueryInstr(params: ZamletParams) extends AbstractKInstr(params) {
  val syncIdent = params.syncIdent()
  val mustDrainValid = Bool()
  val mustDrainSyncIdent = params.syncIdent()
  val baseline = params.ident()
  val reserved = UInt((KInstr.width - baseWidth -
                       params.identWidth - (2 * params.syncIdentWidth) - 1).W)
}

/**
 * A location in a jamlet (k_index + j_in_k_index).
 * Python reference: derived from KMAddr/RegAddr k_index and j_in_k_index
 */
class JamletLoc(params: ZamletParams) extends Bundle {
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
class WordInstr(params: ZamletParams) extends AbstractKInstr(params) {
  private val jamletLocWidth = log2Ceil(params.kInL) + log2Ceil(params.jInK)
  private val usedBits = baseWidth + 2 * jamletLocWidth +
                         params.rfAddrWidth + 2 * log2Ceil(params.wordBytes) +
                         params.wordBytes
  require(usedBits <= KInstr.width, s"WordInstr uses $usedBits bits but KInstr.width is ${KInstr.width}")

  val regLoc = new JamletLoc(params)
  val reg = params.rfAddr()
  val regOffsetInWord = UInt(log2Ceil(params.wordBytes).W)
  val memLoc = new JamletLoc(params)
  val memOffsetInWord = UInt(log2Ceil(params.wordBytes).W)
  val byteMask = UInt(params.wordBytes.W)
  val _padding = UInt((KInstr.width - usedBits).W)
}

/**
 * Instruction format for LoadJ2JWords / StoreJ2JWords.
 *
 * Python reference: Load/Store with k_maddr in kinstructions.py
 * - reg: the RF register (dst for load, src for store)
 */
class J2JInstr(params: ZamletParams) extends AbstractKInstr(params) {
  private val usedBits = baseWidth + params.cacheSlotWidth +
                         2 * LaneOrder.getWidth + 2 * ElementWidth.getWidth +
                         log2Ceil(params.wordBytes * params.jInL) +
                         2 * params.paramRefIdxWidth +
                         params.rfAddrWidth
  require(usedBits <= KInstr.width, s"J2JInstr uses $usedBits bits but KInstr.width is ${KInstr.width}")

  val cacheSlot = params.cacheSlot()
  val memLaneOrder = LaneOrder()
  val rfLaneOrder = LaneOrder()
  val memEw = ElementWidth()
  val rfEw = ElementWidth()
  val baseAddr = UInt(log2Ceil(params.wordBytes * params.jInL).W)
  val startIndexParamIdx = UInt(params.paramRefIdxWidth.W)
  val endIndexParamIdx = UInt(params.paramRefIdxWidth.W)
  val reg = params.rfAddr()
  val _padding = UInt((KInstr.width - usedBits).W)
}

/**
 * Instruction format for indexed operations (LoadIdxUnord / StoreIdxUnord / LoadIdxElement).
 * - reg: the RF data register (dst for load, src for store)
 */
class IndexedInstr(params: ZamletParams) extends AbstractKInstr(params) {
  private val usedBits = baseWidth + params.syncIdentWidth +
                         params.paramRefIdxWidth +
                         2 * ElementWidth.getWidth + LaneOrder.getWidth +
                         3 * params.rfAddrWidth + 1 +
                         2 * params.paramRefIdxWidth
  require(usedBits <= KInstr.width, s"IndexedInstr uses $usedBits bits but KInstr.width is ${KInstr.width}")

  val syncIdent = params.syncIdent()
  val startIndexParamIdx = UInt(params.paramRefIdxWidth.W)
  val rfEw = ElementWidth()
  val rfLaneOrder = LaneOrder()
  val reg = params.rfAddr()
  val maskReg = params.rfAddr()
  val maskEnabled = Bool()
  val baseAddrParamIdx = UInt(params.paramRefIdxWidth.W)
  val endIndexParamIdx = UInt(params.paramRefIdxWidth.W)
  // Indexed-specific fields
  val indexEw = ElementWidth()
  val indexReg = params.rfAddr()
  val _padding = UInt((KInstr.width - usedBits).W)
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
class LoadImmInstr(params: ZamletParams) extends AbstractLocalKInstr(params) {
  private val usedBits = baseWidth + log2Ceil(params.jInK) +
                         params.rfAddrWidth + log2Ceil(params.wordBytes / 4) + 4 + 32
  require(usedBits <= KInstr.width, s"LoadImmInstr uses $usedBits bits but KInstr.width is ${KInstr.width}")

  val jInKIndex = UInt(log2Ceil(params.jInK).W)
  val rfAddr = params.rfAddr()
  val section = UInt(log2Ceil(params.wordBytes / 4).W)
  val byteMask = UInt(4.W)
  val data = UInt(32.W)
  val reserved = UInt((KInstr.width - usedBits).W)
}

/**
 * WriteParam instruction format - write a compact parameter value.
 * Used to set up addresses/strides/nElements before load/store instructions.
 *
 * Layout (64 bits total):
 *   opcode:    6 bits  - KInstrOpcode.WriteParam
 *   paramIdx:  log2NParams bits - which param memory entry to write
 *   data:      remaining bits after the shared base and param index
 */
class WriteParamInstr(params: ZamletParams) extends AbstractKInstr(params) {
  private val usedBits = baseWidth + params.log2NParams + params.memAddrWidth
  require(usedBits <= KInstr.width, s"WriteParamInstr uses $usedBits bits but KInstr.width is ${KInstr.width}")

  val paramIdx = UInt(params.log2NParams.W)
  val data = UInt(params.memAddrWidth.W)
  val reserved = UInt((KInstr.width - usedBits).W)
}

/**
 * StoreScalar instruction format - store from RF to scalar memory.
 *
 * This is not a LocalExec operation: scalar stores may block on memory and are
 * handled by the JTE path.
 *
 * Layout (64 bits total):
 *   opcode:      6 bits  - KInstrOpcode.StoreScalar
 *   dataReg:     6 bits  - source RF register (vs)
 *   scalarAddrParamIdx: paramRefIdxWidth bits - low bits of scalar paddr param index
 *   ew:          4 bits  - element width for mask generation
 *   reserved:    remaining bits
 */
class StoreScalarInstr(params: ZamletParams) extends AbstractLocalKInstr(params) {
  private val usedBits = baseWidth + params.rfAddrWidth + params.paramRefIdxWidth +
    ElementWidth.getWidth
  require(usedBits <= KInstr.width, s"StoreScalarInstr uses $usedBits bits but KInstr.width is ${KInstr.width}")

  val dataReg = params.rfAddr()
  val scalarAddrParamIdx = UInt(params.paramRefIdxWidth.W)
  val ew = ElementWidth()
  val reserved = UInt((KInstr.width - usedBits).W)
}

class LocalKInstrBase(params: ZamletParams) extends AbstractLocalKInstr(params) {
  val _padding = UInt((KInstr.width - baseWidth).W)
}

abstract class AbstractLoadStoreSimpleInstr(params: ZamletParams) extends AbstractLocalKInstr(params) {
  val rfAddr = params.rfAddr()
  val baseAddrParamIdx = UInt(params.paramRefIdxWidth.W)
  val maskReg = params.rfAddr()
  val ew = ElementWidth()
  val startIndexParamIdx = UInt(params.paramRefIdxWidth.W)
  val endIndexParamIdx = UInt(params.paramRefIdxWidth.W)
  val maskEnabled = Bool()

  def loadStoreSimpleWidth: Int = baseWidth + params.rfAddrWidth +
    params.paramRefIdxWidth + params.rfAddrWidth + ElementWidth.getWidth +
    2 * params.paramRefIdxWidth + 1
}

class LoadSimpleInstr(params: ZamletParams) extends AbstractLoadStoreSimpleInstr(params) {
  val _padding = UInt((KInstr.width - loadStoreSimpleWidth).W)
}

class StoreSimpleInstr(params: ZamletParams) extends AbstractLoadStoreSimpleInstr(params) {
  val _padding = UInt((KInstr.width - loadStoreSimpleWidth).W)
}

abstract class AbstractBinaryOpInstr(params: ZamletParams) extends AbstractLocalKInstr(params) {
  val dstReg = params.rfAddr()
  val srcAReg = params.rfAddr()
  val srcBReg = params.rfAddr()
  val maskReg = params.rfAddr()
  val ew = ElementWidth()
  val startIndexParamIdx = UInt(params.paramRefIdxWidth.W)
  val endIndexParamIdx = UInt(params.paramRefIdxWidth.W)
  val isSignedA = Bool()
  val isSignedB = Bool()
  val maskEnabled = Bool()
  val useUpper = Bool()

  def binaryOpWidth: Int = baseWidth + (4 * params.rfAddrWidth) + ElementWidth.getWidth +
    2 * params.paramRefIdxWidth + 4
}

class BinaryOpInstr(params: ZamletParams) extends AbstractBinaryOpInstr(params) {
  val _padding = UInt((KInstr.width - binaryOpWidth).W)
}
