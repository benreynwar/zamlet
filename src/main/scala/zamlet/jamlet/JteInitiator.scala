package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.utils.DoubleBuffer
import zamlet.utils.ValidBuffer
import zamlet.Ordering
import zamlet.WidthFormat
import zamlet.ElementWidth
import zamlet.LaneOrder
import zamlet.WidthHelpers
import zamlet.Utils
import zamlet.network.{INetworkWord, JteIHeader, MessageType, NetworkWord, SendType}

object TransferMode extends ChiselEnum {
  val StrideLoad, StrideStore, IndexLoad, IndexStore, RegGather = Value
}

object JteInitiatorState extends ChiselEnum {
  val Initial = Value(0.U)
  val Dropped = Value(1.U)
  val WaitingForFault = Value(2.U)
  val RequestSent = Value(3.U)
  val Complete = Value(4.U)
  val WaitingForTlb = Value(5.U)
  val EarlyTlbAvailable = Value(6.U)
}

// When the EW > 64 we send an instruction for each word and
// offset the baseAddr and dataReg to put the word in the right place.

class JteInitiatorInput(params: ZamletParams) extends Bundle {
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val mode = TransferMode()
  val baseAddr = params.memAddr()
  val stride = params.memAddr() // Also holds slide offset
  val startIndex = params.elementIndex()
  val endIndex = params.elementIndex()
  val dataReg = params.rfAddr()
  val indexReg = params.rfAddr()
  val maskReg = params.rfAddr()
  val maskEnabled = Bool()
  // Lane order of the register file
  val rfLaneOrder = LaneOrder()
  // WF/EW of the data in the register file
  val rfDataWF = WidthFormat()
  val rfDataEW = ElementWidth()
  // EW of the indices in the register file
  // It is assumed that the EW/WF ratio is the same in the data and index.
  val rfIndexEW = ElementWidth()
  val initiator = Vec(params.wordBytes, JteInitiatorState())
}

class JteInitiatorCommit(params: ZamletParams) extends Bundle {
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val initiator = Vec(params.wordBytes, JteInitiatorState())
}

class JteInitiatorAB(params: ZamletParams) extends Bundle {
  val input = new JteInitiatorInput(params)
  val indexUse = Bool()
  val dataUse = Bool()
  val maskUse = Bool()
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val startInner = UInt(3.W)
  val finalInner = UInt(3.W)
  val startOuter = UInt(3.W)
  val finalOuter = UInt(3.W)
  val log2Ratio = UInt(3.W)
  val log2RFIndexEB = UInt(3.W)
  val log2RFDataEB = UInt(3.W)
  val passOffset = UInt((params.log2JInL + params.wordBytes).W)
  val noLocalElements = Bool()
}

class JteInitiatorAIO(params: ZamletParams) extends Bundle {
  val laneIndex = Input(UInt(params.log2JInL.W))
  val input = Flipped(Decoupled(new JteInitiatorInput(params)))
  val ab = Decoupled(new JteInitiatorAB(params))
}

class JteInitiatorA(params: ZamletParams) extends Module {
  val io = IO(new JteInitiatorAIO(params))

  val input = io.input.bits

  val log2DataEW = WidthHelpers.ewLog2Bits(input.rfDataEW)
  val log2IndexEW = WidthHelpers.ewLog2Bits(input.rfIndexEW)
  val log2Ratio = WidthHelpers.wfLog2Bits(input.rfDataWF) - log2DataEW
  val passOffset = io.laneIndex << log2Ratio

  // Which lane is the startIndex in
  // This is given by the bits [bLog2Ratio, bLog2Ratio + log2JInL)
  // bLog2Ratio is 0 to 6  (ew matches is 0,  log2(512/8) is 6)
  val startLane = (input.startIndex(params.log2JInL+6-1, 0) >> log2Ratio)(params.log2JInL-1, 0)

  // The lowest bLog2Ratio bits determine the inner loop index
  // if we are the start index is in this lane
  val startInner = Wire(UInt(3.W))
  when (io.laneIndex === startLane) {
    // If we are the starting lane then we start in the middle of the inner loop
    startInner := input.startIndex(3, 0) & ((1.U << log2Ratio)-1.U)
  } .otherwise {
    startInner := 0.U
  }

  // startIndex has width log2JInL + 6
  // The 6 is 3 (for 8 elements in 64 bit word) + 3 (for LMUL max is 8)
  val startOuter = Wire(UInt(3.W))
  val startOuterOverflow = Wire(Bool())
  when (io.laneIndex >= startLane) {
    startOuter := input.startIndex >> (params.log2JInL.U + log2Ratio)
    startOuterOverflow := false.B
  } .otherwise {
    startOuter := (input.startIndex >> (params.log2JInL.U +  log2Ratio)) + 1.U
    startOuterOverflow := (startOuter === 0.U)
  }

  val finalIndex = input.endIndex - 1.U
  val finalLane = (finalIndex(params.log2JInL+6-1, 0) >> log2Ratio)(params.log2JInL-1, 0)
  val finalInner = Wire(UInt(3.W))
  when (io.laneIndex === finalLane) {
    finalInner := finalIndex(3, 0) & ((1.U << log2Ratio)-1.U)
  } .otherwise {
    finalInner := (1.U << log2Ratio)-1.U
  }
  val finalOuter = Wire(UInt(3.W))
  val finalOuterOverflow = Wire(Bool())
  when (io.laneIndex > finalLane) {
    finalOuter := (finalIndex >> (params.log2JInL.U + log2Ratio)) - 1.U
    finalOuterOverflow := (finalOuter === ((1 << 3) - 1).U)
  } .otherwise {
    finalOuter := finalIndex >> (params.log2JInL.U +  log2Ratio)
    finalOuterOverflow := false.B
  }

  val noLocalElements = startOuterOverflow || finalOuterOverflow || (finalOuter < startOuter)

  val indexUse = (input.mode === TransferMode.IndexLoad || input.mode === TransferMode.IndexStore) && !noLocalElements
  val dataUse = (input.mode === TransferMode.IndexStore || input.mode === TransferMode.StrideStore) && !noLocalElements
  val maskUse = io.input.bits.maskEnabled && !noLocalElements

  io.ab.valid := io.input.valid
  io.input.ready := io.ab.ready

  io.ab.bits.input := input
  io.ab.bits.indexUse := indexUse
  io.ab.bits.dataUse := dataUse
  io.ab.bits.maskUse := maskUse
  io.ab.bits.startInner := startInner
  io.ab.bits.finalInner := finalInner
  io.ab.bits.startOuter := startOuter
  io.ab.bits.finalOuter := finalOuter
  io.ab.bits.log2Ratio := log2Ratio
  io.ab.bits.log2RFIndexEB := log2IndexEW - 3.U
  io.ab.bits.log2RFDataEB := log2DataEW - 3.U
  io.ab.bits.passOffset := passOffset
  io.ab.bits.noLocalElements := noLocalElements

  io.ab.bits.teIndex := io.input.bits.teIndex
}

class JteInitiatorZIO(params: ZamletParams) extends Bundle {
  val za = Flipped(Decoupled(new JteInitiatorAB(params)))
  val ab = Decoupled(new JteInitiatorAB(params))
  val rfMaskReq = Decoupled(params.rfAddr())
  val rfDataReq = Decoupled(params.rfAddr())
}

class JteInitiatorZ(params: ZamletParams) extends Module {
  val io = IO(new JteInitiatorZIO(params))

  val maskNotBlocking = io.rfMaskReq.ready || !io.za.bits.maskUse
  val dataNotBlocking = io.rfDataReq.ready || !io.za.bits.dataUse

  io.rfMaskReq.valid := io.za.valid && io.ab.ready && dataNotBlocking && io.za.bits.maskUse
  io.rfMaskReq.bits := io.za.bits.input.maskReg
  io.rfDataReq.valid := io.za.valid && io.ab.ready && maskNotBlocking && io.za.bits.dataUse
  io.rfDataReq.bits := io.za.bits.input.dataReg

  io.ab.valid := io.za.valid && maskNotBlocking && dataNotBlocking
  io.za.ready := io.ab.ready && maskNotBlocking && dataNotBlocking
  io.ab.bits := io.za.bits
}

class JteInitiatorBC(params: ZamletParams) extends Bundle {
  val input = new JteInitiatorInput(params)
  val indexUse = Bool()
  val dataUse = Bool()
  val maskUse = Bool()
  val indexEnabled = Bool()
  val dataEnabled = Bool()
  val maskEnabled = Bool()
  val elementIndex = UInt(params.elementIndexWidth.W)
  val active = Bool()
  val count = UInt(6.W)
  val srcOffset = UInt((params.log2WordWidth - 3).W)
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val last = Bool()
}

class JteInitiatorBIO(params: ZamletParams) extends Bundle {
  val ab = Flipped(Decoupled(new JteInitiatorAB(params)))
  val bc = Decoupled(new JteInitiatorBC(params))
  val rfIndexReq = Decoupled(params.rfAddr())
}

class JteInitiatorB(params: ZamletParams) extends Module {
  val io = IO(new JteInitiatorBIO(params))

  val fire = io.bc.valid && io.bc.ready

  // Increment the middle loop
  val firstInnerNext = Wire(Bool())
  val firstInner = RegEnable(firstInnerNext, true.B, fire)
  val countInner = Wire(UInt(6.W))
  val countInnerPrevious = RegEnable(countInner, fire)

  // Increment the outer loop
  val firstOuterNext = Wire(Bool())
  val firstOuter = RegEnable(firstOuterNext, true.B, fire)
  val countOuter = Wire(UInt(6.W))
  firstOuterNext := ((countOuter === io.ab.bits.finalOuter) && firstInnerNext) || io.ab.bits.noLocalElements
  val countOuterPrevious = RegEnable(countOuter, fire)
  when (firstOuter) {
    countOuter := io.ab.bits.startOuter
  } .elsewhen (firstInner) {
    countOuter := countOuterPrevious + 1.U
  } .otherwise {
    countOuter := countOuterPrevious
  }
  countInner := Mux(firstInner, Mux(firstOuter, io.ab.bits.startInner, 0.U), countInnerPrevious + 1.U)
  val finalInnerForOuter = Mux(
    countOuter === io.ab.bits.finalOuter,
    io.ab.bits.finalInner,
    (1.U << io.ab.bits.log2Ratio) - 1.U,
  )
  firstInnerNext := (countInner === finalInnerForOuter) || io.ab.bits.noLocalElements

  val last = ((countInner === io.ab.bits.finalInner) && (countOuter === io.ab.bits.finalOuter)) || io.ab.bits.noLocalElements

  val elementIndex = (countOuter << (params.log2JInL.U + io.ab.bits.log2Ratio)) + io.ab.bits.passOffset + countInner
  val srcOffset = (countInner + (countOuter << io.ab.bits.log2Ratio)) << io.ab.bits.log2RFDataEB

  // We need to read a data register if this is the first element in that register.
  val count = countInner + (countOuter << io.ab.bits.log2Ratio)
  val indexRequires = ((count << io.ab.bits.log2RFIndexEB)(params.log2WordBytes-1, 0) === 0.U)

  // The first local element needs the current index word even if it starts in
  // the middle of that word. Later elements need a new word only at boundaries.
  val indexEnabled = (firstOuter || indexRequires) && io.ab.bits.indexUse
  val indexNotBlocking = io.rfIndexReq.ready || !indexEnabled

  io.rfIndexReq.valid := indexEnabled && fire
  io.rfIndexReq.bits := io.ab.bits.input.indexReg + (count >> (params.log2WordBytes.U - io.ab.bits.log2RFIndexEB))

  // Break into the elements

  //val active = (io.ab.bits.finalOuter > countOuter) || ((io.ab.bits.finalOuter === countOuter) && (io.ab.bits.finalInner >= countInner))
  val active = !io.ab.bits.noLocalElements

  io.bc.valid := io.ab.valid && indexNotBlocking
  io.ab.ready := io.bc.ready && firstOuterNext && indexNotBlocking

  io.bc.bits.input := io.ab.bits.input
  io.bc.bits.indexUse := io.ab.bits.indexUse
  io.bc.bits.dataUse := io.ab.bits.dataUse
  io.bc.bits.maskUse := io.ab.bits.input.maskEnabled
  io.bc.bits.indexEnabled := indexEnabled
  io.bc.bits.dataEnabled := firstOuter && io.ab.bits.dataUse
  io.bc.bits.maskEnabled := firstOuter && io.ab.bits.maskUse
  io.bc.bits.elementIndex := elementIndex
  io.bc.bits.active := active
  io.bc.bits.count := count
  io.bc.bits.srcOffset := srcOffset

  io.bc.bits.teIndex := io.ab.bits.teIndex
  io.bc.bits.last := last
}


class JteInitiatorCIO(params: ZamletParams) extends Bundle {
  val bc = Flipped(Decoupled(new JteInitiatorBC(params)))
  val cd = Decoupled(new JteInitiatorBC(params))
}

class JteInitiatorC(params: ZamletParams) extends Module {
  // We waiting for the register responses.
  val io = IO(new JteInitiatorCIO(params))
  io.cd <> io.bc
}

class JteInitiatorDE(params: ZamletParams) extends Bundle {
  val input = new JteInitiatorInput(params)
  val rfDataEB = UInt((params.log2WordBytes + 1).W)
  val offset = UInt(params.memAddrWidth.W)
  //val offsetEnd = UInt(params.memAddrWidth.W)
  val srcData = params.word()
  val srcOffset = UInt((params.log2WordWidth-3).W)
  val isStore = Bool()
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val last = Bool()
  val active = Bool()
}

class JteInitiatorDIO(params: ZamletParams) extends Bundle {
  val cd = Flipped(Decoupled(new JteInitiatorBC(params)))
  val de = Decoupled(new JteInitiatorDE(params))
  val rfMaskResp = Flipped(Decoupled(params.word()))
  val rfIndexResp = Flipped(Decoupled(params.word()))
  val rfDataResp = Flipped(Decoupled(params.word()))
}

class JteInitiatorD(params: ZamletParams) extends Module {
  // We waiting for the register responses.
  val io = IO(new JteInitiatorDIO(params))

  val fire = io.cd.valid && io.cd.ready

  val maskNotBlocking = io.rfMaskResp.valid || !io.cd.bits.maskEnabled
  val indexNotBlocking = io.rfIndexResp.valid || !io.cd.bits.indexEnabled
  val dataNotBlocking = io.rfDataResp.valid || !io.cd.bits.dataEnabled

  // Get the Mask
  val maskWord = Wire(params.word())
  val maskWordPrevious = RegEnable(maskWord, fire)
  when (io.cd.bits.maskEnabled) {
    maskWord := io.rfMaskResp.bits
  } .elsewhen (io.cd.bits.input.maskEnabled) {
    // We're using a mask but it's the same register address as the previous cycle
    // so we don't have another register response.
    maskWord := maskWordPrevious
  } .otherwise {
    maskWord := ~0.U(params.wordWidth.W)
  }
  val maskBit = maskWord(io.cd.bits.count)
  val emitElement = io.cd.bits.active && maskBit
  val forwardElement = emitElement || io.cd.bits.last
  val canConsume = io.de.ready || !forwardElement

  io.rfMaskResp.ready := io.cd.bits.maskEnabled && io.cd.valid && indexNotBlocking && dataNotBlocking && canConsume
  io.rfIndexResp.ready := io.cd.bits.indexEnabled && io.cd.valid && maskNotBlocking && dataNotBlocking && canConsume
  io.rfDataResp.ready := io.cd.bits.dataEnabled && io.cd.valid && maskNotBlocking && indexNotBlocking && canConsume

  // Get the index word from the register response
  val indexWord = Wire(params.word())
  val indexWordPrevious = RegEnable(indexWord, fire)
  when (io.cd.bits.indexEnabled) {
    indexWord := io.rfIndexResp.bits
  } .otherwise {
    indexWord := indexWordPrevious
  }

  // Look up the index in that register word, or calculate the stride
  val baseOffset = Wire(UInt(params.memAddrWidth.W))
  //def getElement(data: UInt, ew: SimpleElementWidth.Type, index: UInt): UInt = {
  val log2DataEB = WidthHelpers.ewLog2Bits(io.cd.bits.input.rfDataEW) - 3.U
  when (io.cd.bits.indexUse) {
    val simpleEW = WidthHelpers.ewToSimple(io.cd.bits.input.rfIndexEW)
    baseOffset := Utils.getElement(indexWord, simpleEW, io.cd.bits.count)
  } .otherwise {
    val simpleEW = WidthHelpers.ewToSimple(io.cd.bits.input.rfIndexEW)
    baseOffset := Utils.getElement(indexWord, simpleEW, io.cd.bits.count) << log2DataEB
    //baseOffset := io.cd.bits.input.stride * io.cd.bits.elementIndex
  }

  // Grab the data
  val dataWord = Wire(params.word())
  val dataWordPrevious = RegEnable(dataWord, fire)
  when (io.cd.bits.dataEnabled) {
    dataWord := io.rfDataResp.bits
  } .otherwise {
    dataWord := dataWordPrevious
  }

  io.cd.ready := canConsume && maskNotBlocking && indexNotBlocking && dataNotBlocking
  io.de.valid := io.cd.valid && forwardElement && maskNotBlocking && indexNotBlocking && dataNotBlocking

  io.de.bits.input := io.cd.bits.input
  io.de.bits.offset := baseOffset
  io.de.bits.rfDataEB := WidthHelpers.ewBits(io.cd.bits.input.rfDataEW) >> 3.U
  //io.de.bits.offsetEnd := baseOffset + io.de.bits.rfDataEB - 1.U
  io.de.bits.srcData := dataWord
  io.de.bits.srcOffset := io.cd.bits.srcOffset
  io.de.bits.isStore := io.cd.bits.dataUse
  io.de.bits.teIndex := io.cd.bits.teIndex
  io.de.bits.instrIdent := io.cd.bits.input.instrIdent
  io.de.bits.last := io.cd.bits.last
  io.de.bits.active := emitElement

}

class JteInitiatorEF(params: ZamletParams) extends Bundle {
  val input = new JteInitiatorInput(params)
  val address = UInt(params.memAddrWidth.W)
  val srcData = params.word()
  val srcOffset = UInt((params.log2WordWidth-3).W)
  val isStore = Bool()
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val last = Bool()
  val active = Bool()
  val rfDataEB = UInt((params.log2WordBytes + 1).W)
  // We only need the position within a page
  // This is to see if an element crosses a page boundary
  val lastByte = UInt(params.log2PageBytesPerZamlet.W)
}

class JteInitiatorEIO(params: ZamletParams) extends Bundle {
  val de = Flipped(Decoupled(new JteInitiatorDE(params)))
  val ef = Decoupled(new JteInitiatorEF(params))
}

class JteInitiatorE(params: ZamletParams) extends Module {
  val io = IO(new JteInitiatorEIO(params))
  io.ef.valid := io.de.valid
  io.de.ready := io.ef.ready
  io.ef.bits.input := io.de.bits.input
  io.ef.bits.address := io.de.bits.input.baseAddr + io.de.bits.offset
  io.ef.bits.srcData := io.de.bits.srcData
  io.ef.bits.srcOffset := io.de.bits.srcOffset
  io.ef.bits.isStore := io.de.bits.isStore
  io.ef.bits.teIndex := io.de.bits.teIndex
  io.ef.bits.instrIdent := io.de.bits.instrIdent
  io.ef.bits.last := io.de.bits.last
  io.ef.bits.active := io.de.bits.active
  io.ef.bits.lastByte := io.de.bits.input.baseAddr + io.de.bits.offset + io.de.bits.rfDataEB
  io.ef.bits.rfDataEB := io.de.bits.rfDataEB
}

class JteInitiatorFG(params: ZamletParams) extends Bundle {
  val nSectionBytes = UInt(params.log2WordWidth.W)
  val stripeOffset = UInt(params.log2StripeBytes.W)
  val srcData = params.word()
  val srcOffset = UInt((params.log2WordWidth-3).W)
  val isStore = Bool()
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val last = Bool()
  val active = Bool()
}

object JamletTlbStatus extends ChiselEnum {
  val Hit = Value(0.U)
  val SoftDrop = Value(1.U)
  val HardDrop = Value(2.U)
}

class JamletTlbReq(params: ZamletParams) extends Bundle {
  val virtualStripeAddr = UInt(params.memStripeAddrWidth.W)
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val byteIndex = UInt(log2Ceil(params.wordBytes).W)
}

class JamletTlbTranslation(params: ZamletParams) extends Bundle {
  val stripeAddr = UInt(params.memStripeAddrWidth.W)
  val ordering = new Ordering()
}

class JamletTlbResp(params: ZamletParams) extends Bundle {
  val status = JamletTlbStatus()
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val byteIndex = UInt(log2Ceil(params.wordBytes).W)
  val translation = new JamletTlbTranslation(params)
}

class JamletTlbAvailable(params: ZamletParams) extends Bundle {
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val byteIndex = UInt(log2Ceil(params.wordBytes).W)
}

class JteInitiatorFIO(params: ZamletParams) extends Bundle {
  val ef = Flipped(Decoupled(new JteInitiatorEF(params)))
  val fg = Decoupled(new JteInitiatorFG(params))
  val tlbReq = Decoupled(new JamletTlbReq(params))
}

class JteInitiatorF(params: ZamletParams) extends Module {
  val io = IO(new JteInitiatorFIO(params))

  val fire = io.fg.valid && io.fg.ready

  // We need to get the EW and ordering for the destination.
  // It might be different if the element spans a stripe.
  // We emit for each stripe that the element crosses.

  // We request a second tlb lookup for the second half if it also crossed a page
  // boundary.

  // What stripe the first byte of the element is on.
  val firstByteStripe = io.ef.bits.address(params.memAddrWidth-1, params.log2StripeBytes);
  val firstByteStripeOffset = io.ef.bits.address(params.log2StripeBytes-1, 0)
  val dataEB = io.ef.bits.rfDataEB
  val lastByte = io.ef.bits.lastByte
  //val lastByteStripe = lastByte(params.memAddrWidth-1, params.log2StripeBytes);
  val lastByteStripeOffset = lastByte(params.log2StripeBytes-1, 0);
  val bytesToStripeEnd = (1 << params.log2StripeBytes).U - firstByteStripeOffset
  val spansStripe = dataEB > bytesToStripeEnd
  val fSrcByteIndex = io.ef.bits.srcOffset(params.log2WordBytes-1, 0)
  val fSrcByteState = io.ef.bits.input.initiator(fSrcByteIndex)
  val fSrcByteEligible =
    fSrcByteState === JteInitiatorState.Initial ||
    fSrcByteState === JteInitiatorState.Dropped
  val fActive = io.ef.bits.active && fSrcByteEligible

  val first = Wire(Bool())
  // Inactive elements are markers for the commit state, not memory requests.
  // They must not leave a pending second stripe section for the next active element.
  val firstNext = !fActive || !first || !spansStripe
  first := RegEnable(firstNext, true.B, fire)

  val lastByteStripe = RegEnable(firstByteStripe + 1.U, fire)

  io.tlbReq.valid := io.ef.valid && fActive && io.fg.ready
  io.tlbReq.bits.virtualStripeAddr := Mux(first, firstByteStripe, lastByteStripe)
  io.tlbReq.bits.teIndex := io.ef.bits.teIndex
  io.tlbReq.bits.byteIndex := io.ef.bits.srcOffset(params.log2WordBytes-1, 0)

  io.fg.valid := io.ef.valid && (
    !fActive || io.tlbReq.ready
  )
  io.ef.ready := io.fg.ready && (
    !fActive || (io.tlbReq.ready && (!first || !spansStripe))
  )

  val firstSectionBytes = Mux(spansStripe, bytesToStripeEnd, dataEB)
  val secondSectionBytes = dataEB - firstSectionBytes
  when (spansStripe) {
    when (first) {
      io.fg.bits.nSectionBytes := firstSectionBytes
    } .otherwise {
      io.fg.bits.nSectionBytes := secondSectionBytes
    }
  } .otherwise {
    io.fg.bits.nSectionBytes := dataEB
  }
  when (first) {
    io.fg.bits.stripeOffset := firstByteStripeOffset;
  } .otherwise {
    // The second half of a stripe-spanning element starts at the beginning of the next stripe.
    io.fg.bits.stripeOffset := 0.U
  }

  io.fg.bits.srcOffset := Mux(
    spansStripe && !first,
    io.ef.bits.srcOffset + firstSectionBytes,
    io.ef.bits.srcOffset,
  )
  io.fg.bits.srcData := io.ef.bits.srcData
  io.fg.bits.isStore := io.ef.bits.isStore
  io.fg.bits.teIndex := io.ef.bits.teIndex
  io.fg.bits.instrIdent := io.ef.bits.instrIdent
  io.fg.bits.last := io.ef.bits.last && (!fActive || !spansStripe || !first)
  io.fg.bits.active := fActive
}

class JteInitiatorGIO(params: ZamletParams) extends Bundle {
  val fg = Flipped(Decoupled(new JteInitiatorFG(params)))
  val gh = Decoupled(new JteInitiatorFG(params))
}

class JteInitiatorG(params: ZamletParams) extends Module {
  // This stage is just waiting for the results from the tlb and ordering requests.
  val io = IO(new JteInitiatorGIO(params))
  io.gh <> io.fg
}

class JteInitiatorHI(params: ZamletParams) extends Bundle {
  val dstNBytes = UInt(params.log2WordWidth.W)
  val dstLaneIndex = UInt(params.log2JInL.W)
  val laneOrder = LaneOrder()
  val dstOffset = UInt((params.log2WordWidth-3).W)
  val srcOffset = UInt((params.log2WordWidth-3).W)
  val dstData = params.word()
  val dstStripeAddr = UInt((params.memAddrWidth - params.log2StripeBytes).W)
  val isStore = Bool()
  val teIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val last = Bool()
}

class JteInitiatorHIO(params: ZamletParams) extends Bundle {
  val gh = Flipped(Decoupled(new JteInitiatorFG(params)))
  val hi = Decoupled(new JteInitiatorHI(params))
  val tlbResp = Flipped(Decoupled(new JamletTlbResp(params)))
  val commit = Valid(new JteInitiatorCommit(params))
}

class JteInitiatorH(params: ZamletParams) extends Module {
  val io = IO(new JteInitiatorHIO(params))

  val completeSection = Wire(Bool())
  val tlbHit = io.tlbResp.bits.status === JamletTlbStatus.Hit
  val tlbSoftDrop = io.tlbResp.bits.status === JamletTlbStatus.SoftDrop
  val tlbHardDrop = io.tlbResp.bits.status === JamletTlbStatus.HardDrop
  val tlbDrop = tlbSoftDrop || tlbHardDrop
  io.tlbResp.ready := io.gh.valid && io.gh.bits.active && (
    (tlbHit && io.hi.ready && completeSection) || tlbDrop
  )
  val stripeAddress = io.tlbResp.bits.translation.stripeAddr
  val ordering = io.tlbResp.bits.translation.ordering

  io.hi.valid := io.gh.valid && io.gh.bits.active && io.tlbResp.valid && tlbHit
  io.gh.ready := !io.gh.bits.active || (
    io.tlbResp.valid && ((tlbHit && io.hi.ready && completeSection) || tlbDrop)
  )

  val packetFire = io.hi.valid && io.hi.ready
  val markerFire = io.gh.valid && io.gh.ready && !io.gh.bits.active
  val dropFire = io.gh.valid && io.gh.ready && io.gh.bits.active && io.tlbResp.valid && tlbDrop
  val commitFire = packetFire || markerFire || dropFire

  // We have a section.
  // We know:
  //   The location of the first byte in the data word
  //   The virtual address of the first byte in the memory
  //   The WF of the stripe
  //   The base physical address of that page

  // We need now step byte by byte through the section
  // We need to work out from this byte how far until we get to the end of an element in memory.


  val first = RegEnable(completeSection || dropFire, true.B, packetFire || dropFire)
  val stripeOffset = Wire(UInt(params.log2StripeBytes.W))
  val stripeOffsetIncrNext = Wire(UInt(params.log2StripeBytes.W))
  val stripeOffsetIncr = RegEnable(stripeOffsetIncrNext, packetFire)

  val remainingBytes = Wire(UInt(params.log2StripeBytes.W))
  val remainingBytesDecrNext = Wire(UInt(params.log2StripeBytes.W))
  val remainingBytesDecr = RegEnable(remainingBytesDecrNext, packetFire)
  when (first) {
    stripeOffset := io.gh.bits.stripeOffset
    remainingBytes := io.gh.bits.nSectionBytes
  } .otherwise {
    stripeOffset := stripeOffsetIncr
    remainingBytes := remainingBytesDecr
  }
  val byteAddress = (stripeAddress << params.log2StripeBytes) + stripeOffset

  // We need to work out the destination
  //  - lane
  //  - byte offset in word

  val destWFLog2Bytes = WidthHelpers.wfLog2Bits(ordering.wf) - 3.U
  val destWFBytes = WidthHelpers.wfBits(ordering.wf) >> 3

  io.hi.bits.dstLaneIndex := (byteAddress >> destWFLog2Bytes)(params.log2JInL-1, 0)
  io.hi.bits.laneOrder := ordering.laneOrder

  when (destWFLog2Bytes >= (params.log2WordWidth.U - 3.U)) {
    // The destination WF is larger than or equal to a word.
    io.hi.bits.dstOffset := byteAddress(params.log2WordWidth-3, 0)
  } .otherwise {
    // The destination WF is smaller than a word.
    // Multiple elements in a word.
    val wFIndex = byteAddress >> destWFLog2Bytes
    io.hi.bits.dstOffset := (wFIndex(params.log2JInL-1, 0) << destWFLog2Bytes) + Utils.maskLow(byteAddress, destWFLog2Bytes)
  }
  // The number of bytes remaining in the WF element.
  val maxSegmentBytes = destWFBytes - Utils.maskLow(byteAddress, destWFLog2Bytes)
  stripeOffsetIncrNext := stripeOffset + maxSegmentBytes
  remainingBytesDecrNext := remainingBytes - maxSegmentBytes
  when (maxSegmentBytes >= remainingBytes) {
    io.hi.bits.dstNBytes := remainingBytes
    completeSection := true.B
  } .otherwise {
    io.hi.bits.dstNBytes := maxSegmentBytes
    completeSection := false.B
  }
  val last = io.gh.bits.last && (!io.gh.bits.active || completeSection || tlbDrop)
  val emittedBytes = io.gh.bits.nSectionBytes - remainingBytes
  val srcOffset = (io.gh.bits.srcOffset + emittedBytes)(params.log2WordBytes-1, 0)
  // Shift the valid store bytes into the destination word lanes.
  val shiftedSrcData = io.gh.bits.srcData >> (srcOffset << 3.U)
  val maskedSrcData = Utils.maskLow(shiftedSrcData, io.hi.bits.dstNBytes << 3.U)
  io.hi.bits.dstData := maskedSrcData << (io.hi.bits.dstOffset << 3.U)
  io.hi.bits.srcOffset := srcOffset
  io.hi.bits.isStore := io.gh.bits.isStore
  io.hi.bits.dstStripeAddr := stripeAddress
  io.hi.bits.teIndex := io.gh.bits.teIndex
  io.hi.bits.instrIdent := io.gh.bits.instrIdent
  io.hi.bits.last := last

  // We want to build up the commit here.
  // When we start a new transfer-engine entry create a fresh one. Set everything to complete.
  // Then set the ones that we emit packets for to WAITING FOR RESPONSE
  // On the final one send out the commit.

  val initiatorInitial = Wire(Vec(params.wordBytes, JteInitiatorState()))
  for (i <- 0 until params.wordBytes) {
    initiatorInitial(i) := JteInitiatorState.Complete
  }

  val initiatorBaseNext = Wire(Vec(params.wordBytes, JteInitiatorState()))
  val initiator = Wire(Vec(params.wordBytes, JteInitiatorState()))
  val initiatorBase = RegEnable(initiatorBaseNext, initiatorInitial, commitFire)

  initiator := initiatorBase
  when (io.gh.bits.active) {
    when (tlbSoftDrop) {
      initiator(srcOffset) := JteInitiatorState.WaitingForTlb
    } .elsewhen (tlbHardDrop) {
      initiator(srcOffset) := JteInitiatorState.Dropped
    } .otherwise {
      initiator(srcOffset) := JteInitiatorState.RequestSent
    }
  }
  initiatorBaseNext := initiator
  when (last) {
    // Initialize the complete. We'll undo this later.
    initiatorBaseNext := initiatorInitial
  }

  io.commit.valid := commitFire && last
  io.commit.bits.initiator := initiator
  io.commit.bits.teIndex := io.gh.bits.teIndex
}

class JteInitiatorIIO(params: ZamletParams) extends Bundle {
  val hi = Flipped(Decoupled(new JteInitiatorHI(params)))
  val packet = Decoupled(new INetworkWord(params))
  val x = Input(UInt(8.W))
  val y = Input(UInt(8.W))
}

class JteInitiatorI(params: ZamletParams) extends Module {
  val io = IO(new JteInitiatorIIO(params))
  val fire = io.packet.valid && io.packet.ready

  val msgIndexNext = Wire(UInt(2.W))
  val msgIndex = RegEnable(msgIndexNext, 0.U, fire)

  val header = Wire(new JteIHeader(params))
  header := 0.U.asTypeOf(new JteIHeader(params))
  header.dstIndex := io.hi.bits.dstLaneIndex
  header.sourceX := io.x
  header.sourceY := io.y
  header.sendType := SendType.Single
  when (io.hi.bits.isStore) {
    header.messageType := MessageType.StoreWordReq
    header.length := 2.U
  } .otherwise {
    header.messageType := MessageType.LoadWordReq
    header.length := 1.U
  }
  header.nBytes := io.hi.bits.dstNBytes
  header.dstOffset := io.hi.bits.dstOffset
  header.srcOffset := io.hi.bits.srcOffset
  header.ident := io.hi.bits.instrIdent
  header.slot := io.hi.bits.teIndex

  io.packet.valid := io.hi.valid
  io.packet.bits.isHeader := false.B
  io.packet.bits.data := header.asUInt
  val completeMessage = Wire(Bool())
  completeMessage := false.B
  io.packet.bits.laneOrder := io.hi.bits.laneOrder
  when (msgIndex === 0.U) {
    io.packet.bits.isHeader := true.B
  } .elsewhen (msgIndex === 1.U) {
    io.packet.bits.data := io.hi.bits.dstStripeAddr
    when (!io.hi.bits.isStore) {
      completeMessage := true.B
    }
  } .otherwise {
    io.packet.bits.data := io.hi.bits.dstData
    completeMessage := true.B
  }
  io.hi.ready := io.packet.ready && completeMessage
  msgIndexNext := Mux(completeMessage, 0.U, msgIndex + 1.U)
}

class JteInitiatorIO(params: ZamletParams) extends Bundle {
  val laneIndex = Input(UInt(params.log2JInL.W))
  val input = Flipped(Decoupled(new JteInitiatorInput(params)))
  val rfMaskReq = Decoupled(params.rfAddr())
  val rfMaskResp = Flipped(Decoupled(params.word()))
  val rfIndexReq = Decoupled(params.rfAddr())
  val rfIndexResp = Flipped(Decoupled(params.word()))
  val rfDataReq = Decoupled(params.rfAddr())
  val rfDataResp = Flipped(Decoupled(params.word()))
  val tlbReq = Decoupled(new JamletTlbReq(params))
  val tlbResp = Flipped(Decoupled(new JamletTlbResp(params)))
  val commit = Valid(new JteInitiatorCommit(params))
  val packet = Decoupled(new INetworkWord(params))
  val x = Input(UInt(8.W))
  val y = Input(UInt(8.W))
}

class JteInitiator(params: ZamletParams) extends Module {
  val io = IO(new JteInitiatorIO(params))
  val ip = params.jteInitiatorParams

  val aStage = Module(new JteInitiatorA(params))
  aStage.io.laneIndex := RegNext(io.laneIndex)
  aStage.io.input <> DoubleBuffer(io.input, ip.inputFB, ip.inputBB)

  val zStage = Module(new JteInitiatorZ(params))
  zStage.io.za <> DoubleBuffer(aStage.io.ab, ip.zFB, ip.zBB)
  io.rfDataReq <> DoubleBuffer(zStage.io.rfDataReq, ip.rfDataReqFB, ip.rfDataReqBB)
  io.rfMaskReq <> DoubleBuffer(zStage.io.rfMaskReq, ip.rfMaskReqFB, ip.rfMaskReqBB)

  val bStage = Module(new JteInitiatorB(params))
  io.rfIndexReq <> DoubleBuffer(bStage.io.rfIndexReq, ip.rfIndexReqFB, ip.rfIndexReqBB)
  bStage.io.ab <> DoubleBuffer(zStage.io.ab, ip.abFB, ip.abBB)

  val cStage = Module(new JteInitiatorC(params))
  cStage.io.bc <> DoubleBuffer(bStage.io.bc, ip.bcFB, ip.bcBB)

  val dStage = Module(new JteInitiatorD(params))
  dStage.io.rfMaskResp <> DoubleBuffer(io.rfMaskResp, ip.rfMaskRespFB, ip.rfMaskRespBB)
  dStage.io.rfDataResp <> DoubleBuffer(io.rfDataResp, ip.rfDataRespFB, ip.rfDataRespBB)
  dStage.io.rfIndexResp <> DoubleBuffer(io.rfIndexResp, ip.rfIndexRespFB, ip.rfIndexRespBB)
  dStage.io.cd <> DoubleBuffer(cStage.io.cd, ip.cdFB, ip.cdBB)

  val eStage = Module(new JteInitiatorE(params))
  eStage.io.de <> DoubleBuffer(dStage.io.de, ip.deFB, ip.deBB)

  val fStage = Module(new JteInitiatorF(params))
  io.tlbReq <> DoubleBuffer(fStage.io.tlbReq, ip.tlbReqFB, ip.tlbReqBB)
  fStage.io.ef <> DoubleBuffer(eStage.io.ef, ip.efFB, ip.efBB)

  val gStage = Module(new JteInitiatorG(params))
  gStage.io.fg <> DoubleBuffer(fStage.io.fg, ip.fgFB, ip.fgBB)

  val hStage = Module(new JteInitiatorH(params))
  hStage.io.gh <> DoubleBuffer(gStage.io.gh, ip.ghFB, ip.ghBB)
  hStage.io.tlbResp <> DoubleBuffer(io.tlbResp, ip.tlbRespFB, ip.tlbRespBB)
  io.commit := ValidBuffer(hStage.io.commit, ip.commitBuffer)

  val iStage = Module(new JteInitiatorI(params))
  iStage.io.hi <> DoubleBuffer(hStage.io.hi, ip.hiFB, ip.hiBB)
  iStage.io.x := RegNext(io.x)
  iStage.io.y := RegNext(io.y)
  io.packet <> DoubleBuffer(iStage.io.packet, ip.packetFB, ip.packetBB)
}


object JteInitiatorGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    val params = ZamletParams.fromFile(args(0))
    new JteInitiator(params)
  }
}

object JteInitiatorMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  JteInitiatorGenerator.generate(args(0), Seq(args(1)))
}

object JteInitiatorStageMain extends App {
  if (args.length < 3) {
    println("Usage: <outputDir> <configFile> <stage>")
    System.exit(1)
  }

  val stage = args(2)
  val generator = new zamlet.ModuleGenerator {
    override def makeModule(args: Seq[String]): Module = {
      val params = ZamletParams.fromFile(args(0))
      stage match {
        case "A" => new JteInitiatorA(params)
        case "B" => new JteInitiatorB(params)
        case "C" => new JteInitiatorC(params)
        case "D" => new JteInitiatorD(params)
        case "E" => new JteInitiatorE(params)
        case "F" => new JteInitiatorF(params)
        case "G" => new JteInitiatorG(params)
        case "H" => new JteInitiatorH(params)
        case "I" => new JteInitiatorI(params)
        case _ => throw new IllegalArgumentException(s"Unknown JTE initiator stage: $stage")
      }
    }
  }

  generator.generate(args(0), Seq(args(1)))
}
