package zamlet.jamlet

import chisel3._
import chisel3.util._

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
class WitemEntry(params: JamletParams) extends Bundle {
  val valid = Bool()
  val instrIdent = params.ident()
  val witemType = WitemType()
  val state = WitemEntryState()

  // State for each tag (one per byte in word)
  val tagStates = Vec(params.wordBytes, new WitemTagState)

  // Selection and scheduling
  val readyForS1 = Bool()
  val priority = UInt(log2Ceil(params.witemTableDepth + 1).W)
}

/** Witem creation from kamlet */
class WitemCreate(params: JamletParams) extends Bundle {
  val instrIdent = params.ident()
  val witemType = WitemType()
  val cacheIsAvail = Bool()
}

/** Request for witem instruction parameters */
class WitemInfoReq(params: JamletParams) extends Bundle {
  val instrIdent = params.ident()
}

/** Response with witem instruction parameters */
class WitemInfoResp(params: JamletParams) extends Bundle {
  val cacheSlot = params.cacheSlot()
  val memWordOrder = WordOrder()
  val rfWordOrder = WordOrder()
  val memEwCode = EwCode()
  val rfEwCode = EwCode()
  val baseAddr = params.memAddr()
  val startIndex = params.elementIndex()
  val nElements = params.elementIndex()
  val stride = SInt(params.memAddrWidth.W)
  val srcReg = params.rfAddr()
  val dstReg = params.rfAddr()
  val maskReg = params.rfAddr()
  val indexReg = params.rfAddr()
  val maskEnabled = Bool()
  val needsSync = Bool()
}

/** Witem src state update from RxCh0 */
class WitemSrcUpdate(params: JamletParams) extends Bundle {
  val instrIdent = params.ident()
  val tag = UInt(log2Ceil(params.wordBytes).W)
  val newState = WitemSendState()
}

/** Witem dst state update from RxCh1 */
class WitemDstUpdate(params: JamletParams) extends Bundle {
  val instrIdent = params.ident()
  val tag = UInt(log2Ceil(params.wordBytes).W)
  val newState = WitemRecvState()
}

/** Witem fault ready signal to KamletWitemTable */
class WitemFaultReady(params: JamletParams) extends Bundle {
  val instrIdent = params.ident()
  val hasFault = Bool()
  val minFaultElement = params.elementIndex()
}

/** Witem fault sync complete from KamletWitemTable */
class WitemFaultSync(params: JamletParams) extends Bundle {
  val instrIdent = params.ident()
  val hasFault = Bool()
  val globalMinFault = params.elementIndex()
}

/** Witem completion sync complete from KamletWitemTable */
class WitemCompletionSync(params: JamletParams) extends Bundle {
  val instrIdent = params.ident()
}

/** SRAM read/write request */
class SramReq(params: JamletParams) extends Bundle {
  val addr = UInt(params.sramAddrWidth.W)
  val isWrite = Bool()
  val writeData = params.word()
}

/** SRAM read response */
class SramResp(params: JamletParams) extends Bundle {
  val readData = params.word()
}

/** RF read/write request */
class RfReq(params: JamletParams) extends Bundle {
  val addr = params.rfAddr()
  val isWrite = Bool()
  val writeData = params.word()
}

/** RF read response */
class RfResp(params: JamletParams) extends Bundle {
  val readData = params.word()
}

/** TLB request */
class TlbReq(params: JamletParams) extends Bundle {
  val vaddr = params.memAddr()
  val isWrite = Bool()
}

/** TLB response */
class TlbResp(params: JamletParams) extends Bundle {
  val paddr = params.memAddr()
  val isVpu = Bool()
  val memEwCode = EwCode()
  val memWordOrder = WordOrder()
  val fault = Bool()
}
