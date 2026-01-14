package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.LamletParams

/** Send-side protocol state for a tag */
object WitemSendState extends ChiselEnum {
  val Initial = Value(0.U)
  val NeedToSend = Value(1.U)
  val WaitingInCaseFault = Value(2.U)
  val WaitingForResponse = Value(3.U)
  val Complete = Value(4.U)
}

/** Receive-side protocol state for a tag */
object WitemRecvState extends ChiselEnum {
  val WaitingForRequest = Value(0.U)
  val NeedToAskForResend = Value(1.U)
  val Complete = Value(2.U)
}

/** Protocol state for a single tag (byte position) */
class WitemTagState extends Bundle {
  val srcState = WitemSendState()
  val dstState = WitemRecvState()
}

/** Element width code: 0=1, 1=8, 2=16, 3=32, 4=64 bits */
object EwCode extends ChiselEnum {
  val Ew1 = Value(0.U)
  val Ew8 = Value(1.U)
  val Ew16 = Value(2.U)
  val Ew32 = Value(3.U)
  val Ew64 = Value(4.U)
}

/** Word order: how jamlet (x,y) maps to vword index */
object WordOrder extends ChiselEnum {
  val Standard = Value(0.U)
}

/** Witem entry lifecycle state */
object WitemEntryState extends ChiselEnum {
  val WaitingForCache = Value(0.U)
  val Active = Value(1.U)
  val WaitingForFaultSync = Value(2.U)
  val WaitingForCompletionSync = Value(3.U)
  val Complete = Value(4.U)
}

/** Witem type enumeration */
object WitemType extends ChiselEnum {
  val LoadJ2JWords = Value(0.U)
  val StoreJ2JWords = Value(1.U)
  val LoadWordSrc = Value(2.U)
  val StoreWordSrc = Value(3.U)
  val LoadStride = Value(4.U)
  val StoreStride = Value(5.U)
  val LoadIdxUnord = Value(6.U)
  val StoreIdxUnord = Value(7.U)
  val LoadIdxElement = Value(8.U)
}

/** Entry in the WitemMonitor table */
class WitemEntry(params: LamletParams) extends Bundle {
  val valid = Bool()
  val instrIdent = params.ident()
  val witemType = WitemType()
  val state = WitemEntryState()

  // State for each tag (one per byte in word)
  val tagStates = Vec(params.wordBytes, new WitemTagState)

  // Selection and scheduling
  val readyForS1 = Bool()
  val priority = UInt(log2Ceil(params.witemTableDepth).W)

  // Fault tracking for strided/indexed operations
  val hasFault = Bool()
  val minFaultElement = params.elementIndex()
}

/** Witem creation from kamlet */
class WitemCreate(params: LamletParams) extends Bundle {
  val instrIdent = params.ident()
  val witemType = WitemType()
  val cacheIsAvail = Bool()
}

/** Request for witem instruction parameters */
class WitemInfoReq(params: LamletParams) extends Bundle {
  val instrIdent = params.ident()
}

/** Response with witem instruction parameters */
class WitemInfoResp(params: LamletParams) extends Bundle {
  // Raw instruction (cast to WordInstr/J2JInstr/StridedInstr/IndexedInstr based on witem type)
  val kinstr = UInt(KInstr.width.W)

  // Resolved values from param memory lookup (for instructions that use indices)
  val baseAddr = params.memAddr()
  val strideBytes = SInt(params.memAddrWidth.W)
  val nElements = params.elementIndex()
}

/** Witem src state update from RxCh0 */
class WitemSrcUpdate(params: LamletParams) extends Bundle {
  val instrIdent = params.ident()
  val tag = UInt(log2Ceil(params.wordBytes).W)
  val newState = WitemSendState()
}

/** Witem dst state update from RxCh1 */
class WitemDstUpdate(params: LamletParams) extends Bundle {
  val instrIdent = params.ident()
  val tag = UInt(log2Ceil(params.wordBytes).W)
  val newState = WitemRecvState()
}

/** Witem fault ready signal to KamletWitemTable */
class WitemFaultReady(params: LamletParams) extends Bundle {
  val instrIdent = params.ident()
  val hasFault = Bool()
  val minFaultElement = params.elementIndex()
}

/** Witem fault sync complete from KamletWitemTable */
class WitemFaultSync(params: LamletParams) extends Bundle {
  val instrIdent = params.ident()
  val hasFault = Bool()
  val globalMinFault = params.elementIndex()
}

/** Witem completion sync complete from KamletWitemTable */
class WitemCompletionSync(params: LamletParams) extends Bundle {
  val instrIdent = params.ident()
}

/** SRAM read/write request */
class SramReq(params: LamletParams) extends Bundle {
  val addr = UInt(params.sramAddrWidth.W)
  val isWrite = Bool()
  val writeData = params.word()
}

/** SRAM read response */
class SramResp(params: LamletParams) extends Bundle {
  val readData = params.word()
}

/** RF read/write request */
class RfReq(params: LamletParams) extends Bundle {
  val addr = params.rfAddr()
  val isWrite = Bool()
  val writeData = params.word()
}

/** RF read response */
class RfResp(params: LamletParams) extends Bundle {
  val readData = params.word()
}

/** TLB request */
class TlbReq(params: LamletParams) extends Bundle {
  val vaddr = params.memAddr()
  val isWrite = Bool()
}

/** TLB response */
class TlbResp(params: LamletParams) extends Bundle {
  val paddr = params.memAddr()
  val isVpu = Bool()
  val memEwCode = EwCode()
  val memWordOrder = WordOrder()
  val fault = Bool()
}

/** WitemMonitor error signals */
class WitemMonitorErrors extends Bundle {
  val noFreeSlot = Bool()
  val priorityOverflow = Bool()
  val invalidEw = Bool()
}
