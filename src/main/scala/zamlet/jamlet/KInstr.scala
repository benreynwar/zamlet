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
  val sramWordOffset = UInt(log2Ceil(params.cacheSlotWordsPerJamlet).W)
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

class KInstrBase(params: ZamletParams) extends AbstractKInstr(params) {
  require(params.rfAddrWidth <= 6, "slotted kinstr register slots are 6 bits")
  require(params.syncIdentWidth * 2 <= 6,
    "slotted f4 stores two sync idents")
  require(LaneOrder.getWidth * 2 <= 6,
    "slotted f3 stores two lane orders")
  require(ElementWidth.getWidth * 2 <= 6,
    "slotted f5 stores two element widths")
  require(params.paramRefIdxWidth * 2 <= 6,
    "slotted f6 stores start and end param refs")
  require(params.writesetWidth + 1 <= 6,
    "slotted f7 stores writeset valid and bits")
  val f1 = UInt(6.W)
  val f2 = UInt(6.W)
  val f3 = UInt(6.W)
  val f4 = UInt(6.W)
  val f5 = UInt(6.W)
  val f6 = UInt(6.W)
  val f7 = UInt(6.W)
  val misc = UInt(8.W)

  def miscParamRef: UInt = misc(params.paramRefIdxWidth - 1, 0)
  def laneOrder: LaneOrder.Type =
    f3((2 * LaneOrder.getWidth) - 1, LaneOrder.getWidth).asTypeOf(LaneOrder())
  def laneOrderB: LaneOrder.Type =
    f3(LaneOrder.getWidth - 1, 0).asTypeOf(LaneOrder())
  def syncIdent: UInt =
    f4((2 * params.syncIdentWidth) - 1, params.syncIdentWidth)
  def syncIdentB: UInt = f4(params.syncIdentWidth - 1, 0)
  def ew: ElementWidth.Type =
    f5((2 * ElementWidth.getWidth) - 1, ElementWidth.getWidth).asTypeOf(ElementWidth())
  def ewB: ElementWidth.Type =
    f5(ElementWidth.getWidth - 1, 0).asTypeOf(ElementWidth())
  def startIndexParamIdx: UInt =
    f6((2 * params.paramRefIdxWidth) - 1, params.paramRefIdxWidth)
  def endIndexParamIdx: UInt = f6(params.paramRefIdxWidth - 1, 0)
  def writeset: Valid[UInt] = {
    val result = Wire(Valid(params.writeset()))
    result.valid := f7(params.writesetWidth)
    result.bits := f7(params.writesetWidth - 1, 0)
    result
  }
  def maskEnabled: Bool = misc(7)

  def isSyncTrigger: Bool = opcode === KInstrOpcode.SyncTrigger
  def isIdentQuery: Bool = opcode === KInstrOpcode.IdentQuery
  def isLoadJ2J: Bool = opcode === KInstrOpcode.LoadJ2J
  def isStoreJ2J: Bool = opcode === KInstrOpcode.StoreJ2J
  def isLoadSimple: Bool = opcode === KInstrOpcode.LoadSimple
  def isStoreSimple: Bool = opcode === KInstrOpcode.StoreSimple
  def isLoadImm: Bool = opcode === KInstrOpcode.LoadImm
  def isWriteParam: Bool = opcode === KInstrOpcode.WriteParam
  def isStoreScalar: Bool = opcode === KInstrOpcode.StoreScalar
  def isAlu: Bool = opcode.isOneOf(
    KInstrOpcode.Add,
    KInstrOpcode.Sub,
    KInstrOpcode.Mul,
    KInstrOpcode.MulHigh)
  def isIndexedLoad: Bool = opcode === KInstrOpcode.LoadIdxUnord
  def isIndexedStore: Bool = opcode === KInstrOpcode.StoreIdxUnord
  def isIndexed: Bool = isIndexedLoad || isIndexedStore
  def isKteSync: Bool = isSyncTrigger || isIdentQuery
  def isCacheLocal: Bool = isLoadSimple || isStoreSimple
  def isKteTransfer: Bool = isIndexed
  def isLocalBroadcast: Bool = isStoreScalar || isAlu
  def usesMask: Bool = maskEnabled && opcode.isOneOf(
    KInstrOpcode.LoadSimple,
    KInstrOpcode.StoreSimple,
    KInstrOpcode.Add,
    KInstrOpcode.Sub,
    KInstrOpcode.Mul,
    KInstrOpcode.MulHigh,
    KInstrOpcode.LoadIdxUnord,
    KInstrOpcode.StoreIdxUnord)

  def f1ReadsRf: Bool = opcode.isOneOf(
    KInstrOpcode.StoreJ2J,
    KInstrOpcode.StoreSimple,
    KInstrOpcode.StoreScalar,
    KInstrOpcode.StoreIdxUnord)
  def f1WritesRf: Bool = opcode.isOneOf(
    KInstrOpcode.LoadJ2J,
    KInstrOpcode.LoadSimple,
    KInstrOpcode.LoadImm,
    KInstrOpcode.LoadIdxUnord) || isAlu
  def f2ReadsRf: Bool = usesMask
  def f2WritesRf: Bool = false.B
  def f3ReadsRf: Bool = isAlu || opcode.isOneOf(
    KInstrOpcode.LoadIdxUnord,
    KInstrOpcode.StoreIdxUnord)
  def f3WritesRf: Bool = false.B
  def f4ReadsRf: Bool = isAlu
  def f4WritesRf: Bool = false.B

  def rfSlotAddr(slot: Int): UInt = slot match {
    case 0 => f1(params.rfAddrWidth - 1, 0)
    case 1 => f2(params.rfAddrWidth - 1, 0)
    case 2 => f3(params.rfAddrWidth - 1, 0)
    case 3 => f4(params.rfAddrWidth - 1, 0)
  }

  def rfSlotReads(slot: Int): Bool = slot match {
    case 0 => f1ReadsRf
    case 1 => f2ReadsRf
    case 2 => f3ReadsRf
    case 3 => f4ReadsRf
  }

  def rfSlotWrites(slot: Int): Bool = slot match {
    case 0 => f1WritesRf
    case 1 => f2WritesRf
    case 2 => f3WritesRf
    case 3 => f4WritesRf
  }
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
class SyncTriggerInstr(params: ZamletParams) extends KInstrBase(params) {
  def value: UInt = Cat(f1, f2(5, 4))
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
class IdentQueryInstr(params: ZamletParams) extends KInstrBase(params) {
  require(params.identWidth <= 12, "ident-query slotted baseline uses f2 and f3")

  def mustDrainValid: Bool = misc(7)
  def mustDrainSyncIdent: UInt = f1(params.syncIdentWidth - 1, 0)
  def baseline: UInt = Cat(f2, f3)(params.identWidth - 1, 0)
}

/**
 * Instruction format for LoadJ2JWords / StoreJ2JWords.
 *
 * Python reference: Load/Store with k_maddr in kinstructions.py
 * - reg: the RF register (dst for load, src for store)
 */
class J2JInstr(params: ZamletParams) extends KInstrBase(params) {
  def reg: UInt = f1(params.rfAddrWidth - 1, 0)
  def memLaneOrder: LaneOrder.Type = laneOrder
  def rfLaneOrder: LaneOrder.Type = laneOrderB
  def memEw: ElementWidth.Type = ew
  def rfEw: ElementWidth.Type = ewB
  def baseAddrParamIdx: UInt = miscParamRef
}

/**
 * Instruction format for indexed operations (LoadIdxUnord / StoreIdxUnord / LoadIdxElement).
 * - reg: the RF data register (dst for load, src for store)
 */
class IndexedInstr(params: ZamletParams) extends KInstrBase(params) {
  def reg: UInt = f1(params.rfAddrWidth - 1, 0)
  def maskReg: UInt = f2(params.rfAddrWidth - 1, 0)
  def indexReg: UInt = f3(params.rfAddrWidth - 1, 0)
  def faultSyncIdent: UInt = syncIdent
  def completionSyncIdent: UInt = syncIdentB
  def rfEw: ElementWidth.Type = ew
  def indexEw: ElementWidth.Type = ewB
  def baseAddrParamIdx: UInt = miscParamRef
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
class LoadImmInstr(params: ZamletParams) extends KInstrBase(params) {
  private val sectionWidth = log2Ceil(params.wordBytes / 4)
  require(log2Ceil(params.jInK) <= 6, "load-imm slotted f2 stores jInKIndex")
  require(sectionWidth + 4 <= 6, "load-imm slotted f3 stores section and byte mask")

  def rfAddr: UInt = f1(params.rfAddrWidth - 1, 0)
  def jInKIndex: UInt = f2(log2Ceil(params.jInK) - 1, 0)
  def section: UInt = {
    if (sectionWidth == 0) 0.U(0.W) else f3(sectionWidth + 3, 4)
  }
  def byteMask: UInt = f3(3, 0)
  def data: UInt = Cat(f4, f5, f6, f7, misc)
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
class WriteParamInstr(params: ZamletParams) extends KInstrBase(params) {
  private val dataPayloadWidth = 42 + 8 - params.log2NParams
  require(params.log2NParams <= 7, "write-param slotted misc stores param index")
  require(params.memAddrWidth <= dataPayloadWidth,
    s"WriteParamInstr data uses ${params.memAddrWidth} bits but slotted payload has $dataPayloadWidth")

  def paramIdx: UInt = misc(params.log2NParams - 1, 0)
  def data: UInt =
    Cat(f1, f2, f3, f4, f5, f6, f7, misc(7, params.log2NParams))(params.memAddrWidth - 1, 0)
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
class StoreScalarInstr(params: ZamletParams) extends KInstrBase(params) {
  require(params.paramRefIdxWidth <= 8,
    "store-scalar slotted misc stores scalar address param")

  def dataReg: UInt = f1(params.rfAddrWidth - 1, 0)
  def scalarAddrParamIdx: UInt = miscParamRef
}

abstract class AbstractLoadStoreSimpleInstr(params: ZamletParams) extends KInstrBase(params) {
  def rfAddr: UInt = f1(params.rfAddrWidth - 1, 0)
  def maskReg: UInt = f2(params.rfAddrWidth - 1, 0)
  def baseAddrParamIdx: UInt = miscParamRef
}

class LoadSimpleInstr(params: ZamletParams) extends AbstractLoadStoreSimpleInstr(params)

class StoreSimpleInstr(params: ZamletParams) extends AbstractLoadStoreSimpleInstr(params)

class BinaryOpInstr(params: ZamletParams) extends KInstrBase(params) {
  def dstReg: UInt = f1(params.rfAddrWidth - 1, 0)
  def maskReg: UInt = f2(params.rfAddrWidth - 1, 0)
  def srcAReg: UInt = f3(params.rfAddrWidth - 1, 0)
  def srcBReg: UInt = f4(params.rfAddrWidth - 1, 0)
  def isSignedA: Bool = misc(0)
  def isSignedB: Bool = misc(1)
  def useUpper: Bool = misc(2)
}
