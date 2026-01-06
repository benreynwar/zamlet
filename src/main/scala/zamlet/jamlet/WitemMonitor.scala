package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.utils.{DoubleBuffer, ValidBuffer}

object WitemMonitorUtils {
  def coordsToVwIndex(params: JamletParams, wordOrder: WordOrder.Type, x: UInt, y: UInt): UInt = {
    Mux(wordOrder === WordOrder.Standard,
        y * params.jTotalCols.U + x,
        0.U)
  }

  def ewCodeToBits(ewCode: EwCode.Type): UInt = {
    MuxLookup(ewCode.asUInt, 64.U)(Seq(
      EwCode.Ew1.asUInt -> 1.U,
      EwCode.Ew8.asUInt -> 8.U,
      EwCode.Ew16.asUInt -> 16.U,
      EwCode.Ew32.asUInt -> 32.U,
      EwCode.Ew64.asUInt -> 64.U
    ))
  }

  def ewCodeToLog2(ewCode: EwCode.Type): UInt = {
    MuxLookup(ewCode.asUInt, 6.U)(Seq(
      EwCode.Ew1.asUInt -> 0.U,
      EwCode.Ew8.asUInt -> 3.U,
      EwCode.Ew16.asUInt -> 4.U,
      EwCode.Ew32.asUInt -> 5.U,
      EwCode.Ew64.asUInt -> 6.U
    ))
  }

  def ewCodeToMask(ewCode: EwCode.Type): UInt = {
    MuxLookup(ewCode.asUInt, "hFFFFFFFFFFFFFFFF".U(64.W))(Seq(
      EwCode.Ew1.asUInt -> 1.U(64.W),
      EwCode.Ew8.asUInt -> "hFF".U(64.W),
      EwCode.Ew16.asUInt -> "hFFFF".U(64.W),
      EwCode.Ew32.asUInt -> "hFFFFFFFF".U(64.W),
      EwCode.Ew64.asUInt -> "hFFFFFFFFFFFFFFFF".U(64.W)
    ))
  }

  def elementsInVlineMask(params: JamletParams, ewCode: EwCode.Type): UInt = {
    val vlineBits = params.wordWidth * params.jInL
    MuxLookup(ewCode.asUInt, (vlineBits / 64 - 1).U)(Seq(
      EwCode.Ew1.asUInt -> (vlineBits / 1 - 1).U,
      EwCode.Ew8.asUInt -> (vlineBits / 8 - 1).U,
      EwCode.Ew16.asUInt -> (vlineBits / 16 - 1).U,
      EwCode.Ew32.asUInt -> (vlineBits / 32 - 1).U,
      EwCode.Ew64.asUInt -> (vlineBits / 64 - 1).U
    ))
  }

  def ewCodeToElementByteMask(ewCode: EwCode.Type): UInt = {
    MuxLookup(ewCode.asUInt, 7.U)(Seq(
      EwCode.Ew8.asUInt -> 0.U,
      EwCode.Ew16.asUInt -> 1.U,
      EwCode.Ew32.asUInt -> 3.U,
      EwCode.Ew64.asUInt -> 7.U
    ))
  }

  def vwIndexToCoords(params: JamletParams, wordOrder: WordOrder.Type, vwIndex: UInt): (UInt, UInt) = {
    // Use masking/shifting since jTotalCols is guaranteed power of 2
    val x = Mux(wordOrder === WordOrder.Standard,
                vwIndex & (params.jTotalCols - 1).U,
                0.U)
    val y = Mux(wordOrder === WordOrder.Standard,
                vwIndex >> params.log2JTotalCols,
                0.U)
    (x, y)
  }
}

class S11StridedIndexedState(params: JamletParams) extends Bundle {
  val iterating = Bool()
  val previousTag = UInt((params.log2WordBytes + 1).W)
  val phase = Bool()  // false = phase 0 (compute intermediates), true = phase 1 (compute outputs)

  // Intermediate values computed in phase 0, used in phase 1:
  val offsetInPortion = UInt(params.log2WordBytes.W)
  val offsetInElement = UInt(4.W)  // ebPlusOneWidth
  val currentTag = UInt((params.log2WordBytes + 1).W)
  val portionEndInWord = UInt((params.log2WordBytes + 1).W)
  val rfElementBytes = UInt(4.W)  // ebPlusOneWidth
  val memElementBytes = UInt(4.W)  // ebPlusOneWidth

  // Fault tracking: set when TLB fault detected, persists across elements of same entry
  val faulted = Bool()
  val faultElementIndex = params.elementIndex()  // Element where fault occurred
  val lastInstrIdent = params.ident()
}

class S11J2JState(params: JamletParams) extends Bundle {
  // Width constants derived from params
  private val ebPlusOneWidth = params.log2WordWidth + 1  // Bits to hold element width in bits (up to wordWidth)
  private val log2EwWidth = log2Ceil(params.log2WordWidth + 1)  // Bits to hold log2(element width)
  private val ebWidth = params.log2WordWidth  // Bits for element boundary (0 to wordWidth-1)
  private val bitAddrWidth = params.elementIndexWidth + params.log2WordWidth  // Bit address in vline

  val iterating = Bool()
  val currentTag = UInt(log2Ceil(params.wordBytes).W)
  val currentVline = UInt(params.elementIndexWidth.W)
  val phase = Bool()  // false = phase 0, true = phase 1

  // Intermediate values computed in phase 0, used in phase 1:
  val memEw = UInt(ebPlusOneWidth.W)
  val regEw = UInt(ebPlusOneWidth.W)
  val memEwCode = EwCode()
  val regEwCode = EwCode()
  val log2RegElementsInVline = UInt((params.log2JInL + params.log2WordWidth).W)
  val startVline = UInt(params.elementIndexWidth.W)
  val endVline = UInt(params.elementIndexWidth.W)
  val startIndex = UInt(params.elementIndexWidth.W)
  val nElements = UInt(params.elementIndexWidth.W)
  val tagWb = UInt((params.log2WordBytes + 3).W)
  val thisVw = UInt(params.log2JInL.W)
  val isLoad = Bool()
  // Load path intermediates
  val memVe = UInt(params.elementIndexWidth.W)
  val memEb = UInt(ebWidth.W)
  val memBitAddrInVline = UInt(bitAddrWidth.W)
  val memVOffset = UInt(1.W)
  // Store path intermediates
  val storeRegVe = UInt(params.elementIndexWidth.W)
  val storeRegEb = UInt(ebWidth.W)
  // Word orders for coordinate conversion
  val rfWordOrder = WordOrder()
  val memWordOrder = WordOrder()
  // baseBitAddr needed in phase 1
  val baseBitAddr = UInt(bitAddrWidth.W)
  // Wide adds pre-computed in phase 0 to break critical path
  val loadRegBitAddr = UInt(bitAddrWidth.W)
  val storeMemBitAddr = UInt(bitAddrWidth.W)
}

class S11J2JResult(params: JamletParams) extends Bundle {
  val output = new S12S13Reg(params)
  val nextState = new S11J2JState(params)
  val outValid = Bool()
  val finished = Bool()
  val invalidEw = Bool()
}

/**
 * J2J tag iteration logic.
 *
 * Implements the mapping logic from python/zamlet/transactions/j2j_mapping.py:
 * - LoadJ2JWords: get_mapping_from_mem() - iterate memory bytes, find reg mappings
 * - StoreJ2JWords: get_mapping_from_reg() - iterate register bytes, find mem mappings
 *
 * The iteration has two loops:
 * - Outer loop: iterate over byte positions (tags) in the local word
 * - Inner loop: iterate over vlines in [startVline, endVline]
 *
 * Each (tag, vline) pair may produce one output if:
 * 1. The tag is "active" (not already handled by a previous tag)
 * 2. The element at this vline is within [startIndex, startIndex + nElements)
 */
object S11J2J {
  def compute(
    params: JamletParams,
    in_input: S10S11Reg,
    in_state: S11J2JState,
    thisX: UInt,
    thisY: UInt
  ): S11J2JResult = {
    val result = Wire(new S11J2JResult(params))

    // Width constants
    val tagWidth = params.log2WordBytes
    val tagPlusOneWidth = params.log2WordBytes + 1
    val ebWidth = 6  // Element boundary: 0-63 for max 64-bit elements
    val ebPlusOneWidth = 7  // For bit counts up to 64
    val vwWidth = params.log2JInL
    val vlineWidth = params.elementIndexWidth
    val bitAddrWidth = params.elementIndexWidth + 8  // Bit address in vline

    // Constants
    val jInL = params.jInL.U
    val log2JInL = params.log2JInL.U
    val wordBytes = params.wordBytes.U

    // Pass-through fields (always set regardless of phase)
    result.output.entryIndex := in_input.entryIndex
    result.output.instrIdent := in_input.instrIdent
    result.output.witemType := in_input.witemType
    result.output.witemInfo := in_input.witemInfo
    result.output.isVpu := false.B  // J2J is always within VPU
    result.output.paddr := 0.U      // Not used for J2J

    when(!in_state.phase) {
      // =========================================================================
      // Phase 0: Compute intermediate values, store in state
      // =========================================================================

      // Decode J2J instruction from kinstr
      val kinstr = KInstr.asJ2J(params, in_input.witemInfo.kinstr)

      // Determine load vs store from witem type
      val isLoad = in_input.witemType === WitemType.LoadJ2JWords

      // Element widths from J2J instruction (in bits: 8/16/32/64)
      val memEw = Wire(UInt(ebPlusOneWidth.W))
      memEw := WitemMonitorUtils.ewCodeToBits(kinstr.memEw)
      val regEw = Wire(UInt(ebPlusOneWidth.W))
      regEw := WitemMonitorUtils.ewCodeToBits(kinstr.rfEw)
      val memEwCode = kinstr.memEw
      val regEwCode = kinstr.rfEw
      val log2MemEw = WitemMonitorUtils.ewCodeToLog2(memEwCode)
      val log2RegEw = WitemMonitorUtils.ewCodeToLog2(regEwCode)

      // Compute thisVw based on coordinates and word order
      val wordOrder = Mux(isLoad, kinstr.memWordOrder, kinstr.rfWordOrder)
      val thisVw = Wire(UInt(vwWidth.W))
      thisVw := WitemMonitorUtils.coordsToVwIndex(params, wordOrder, thisX, thisY)

      val startIndex = kinstr.startIndex
      val nElements = in_input.witemInfo.nElements

      // Vline range calculation
      val log2RegElementsInVline = Wire(UInt(5.W))
      log2RegElementsInVline := log2JInL +& params.log2WordWidth.U - log2RegEw
      val startVline = Wire(UInt(vlineWidth.W))
      startVline := startIndex >> log2RegElementsInVline
      val endVline = Wire(UInt(vlineWidth.W))
      endVline := (startIndex +& nElements - 1.U) >> log2RegElementsInVline

      // Current position in iteration
      val currentTag = Wire(UInt(tagWidth.W))
      currentTag := Mux(in_state.iterating, in_state.currentTag, 0.U)
      val currentVline = in_state.currentVline

      // Bit offset for current tag: tag_wb = tag * 8
      val tagWb = Wire(UInt((tagWidth + 3).W))
      tagWb := currentTag << 3

      // Load path: compute values before wide add
      val memVe = Wire(UInt(vlineWidth.W))
      memVe := ((tagWb >> log2MemEw) << log2JInL) + thisVw
      val memEb = Wire(UInt(ebWidth.W))
      memEb := tagWb & (memEw - 1.U)
      val memBitAddrInVline = Wire(UInt(bitAddrWidth.W))
      memBitAddrInVline := (memVe << log2MemEw) + memEb

      val baseBitAddr = in_input.witemInfo.baseAddr
      val memVOffset = Mux(memBitAddrInVline < baseBitAddr, 1.U, 0.U)

      // Store path: compute values before wide add
      val storeRegVe = Wire(UInt(vlineWidth.W))
      storeRegVe := ((tagWb >> log2RegEw) << log2JInL) + thisVw
      val storeRegEb = Wire(UInt(ebWidth.W))
      storeRegEb := tagWb & (regEw - 1.U)

      // Pre-compute wide adds to break critical path (these depend on currentVline)
      val vlineShift = (params.log2WordWidth + params.log2JInL).U
      val loadRegBitAddr = Wire(UInt(bitAddrWidth.W))
      loadRegBitAddr := memBitAddrInVline +& (currentVline << vlineShift) - baseBitAddr

      // storeRegVe << regEwCode using switch (avoids barrel shifter)
      val storeRegVeShifted = Wire(UInt((vlineWidth + 6).W))
      storeRegVeShifted := storeRegVe << 3  // default Ew8
      switch(regEwCode) {
        is(EwCode.Ew16) { storeRegVeShifted := storeRegVe << 4 }
        is(EwCode.Ew32) { storeRegVeShifted := storeRegVe << 5 }
        is(EwCode.Ew64) { storeRegVeShifted := storeRegVe << 6 }
      }
      val storeRegAddr = Wire(UInt(bitAddrWidth.W))
      storeRegAddr := (currentVline << vlineShift) +& storeRegVeShifted + storeRegEb
      val storeMemBitAddr = Wire(UInt(bitAddrWidth.W))
      storeMemBitAddr := storeRegAddr +& baseBitAddr

      // Store intermediates in next state
      result.nextState.phase := true.B
      result.nextState.iterating := in_state.iterating
      result.nextState.currentTag := currentTag
      result.nextState.currentVline := currentVline
      result.nextState.memEw := memEw
      result.nextState.regEw := regEw
      result.nextState.memEwCode := memEwCode
      result.nextState.regEwCode := regEwCode
      result.nextState.log2RegElementsInVline := log2RegElementsInVline
      result.nextState.startVline := startVline
      result.nextState.endVline := endVline
      result.nextState.startIndex := startIndex
      result.nextState.nElements := nElements
      result.nextState.tagWb := tagWb
      result.nextState.thisVw := thisVw
      result.nextState.isLoad := isLoad
      result.nextState.memVe := memVe
      result.nextState.memEb := memEb
      result.nextState.memBitAddrInVline := memBitAddrInVline
      result.nextState.memVOffset := memVOffset
      result.nextState.storeRegVe := storeRegVe
      result.nextState.storeRegEb := storeRegEb
      result.nextState.rfWordOrder := kinstr.rfWordOrder
      result.nextState.memWordOrder := kinstr.memWordOrder
      result.nextState.baseBitAddr := baseBitAddr
      result.nextState.loadRegBitAddr := loadRegBitAddr
      result.nextState.storeMemBitAddr := storeMemBitAddr

      // Phase 0 doesn't emit output
      result.output.rfV := 0.U
      result.output.srcTag := 0.U
      result.output.dstTag := 0.U
      result.output.nBytes := 0.U
      result.output.targetX := 0.U
      result.output.targetY := 0.U
      result.outValid := false.B
      result.finished := false.B
      result.invalidEw := false.B

    }.otherwise {
      // =========================================================================
      // Phase 1: Use stored intermediates, compute outputs with wide adds
      // =========================================================================

      // Read intermediates from state
      val memEw = in_state.memEw
      val regEw = in_state.regEw
      val memEwCode = in_state.memEwCode
      val regEwCode = in_state.regEwCode

      // Error if Ew1 is used (not valid for J2J)
      val j2jEwError = (regEwCode === EwCode.Ew1) || (memEwCode === EwCode.Ew1)

      // Helpers for fixed-shift mux (faster than barrel shifter)
      // Assumes ewCode is Ew8/16/32/64 (not Ew1)
      def shiftRightByEwCode(value: UInt, ewCode: EwCode.Type): UInt = {
        val result = Wire(UInt(value.getWidth.W))
        result := value >> 3  // default Ew8
        switch(ewCode) {
          is(EwCode.Ew16) { result := value >> 4 }
          is(EwCode.Ew32) { result := value >> 5 }
          is(EwCode.Ew64) { result := value >> 6 }
        }
        result
      }
      def shiftLeftByEwCode(value: UInt, ewCode: EwCode.Type): UInt = {
        val result = Wire(UInt((value.getWidth + 6).W))
        result := value << 3  // default Ew8
        switch(ewCode) {
          is(EwCode.Ew16) { result := value << 4 }
          is(EwCode.Ew32) { result := value << 5 }
          is(EwCode.Ew64) { result := value << 6 }
        }
        result
      }
      val log2RegElementsInVline = in_state.log2RegElementsInVline
      val startVline = in_state.startVline
      val endVline = in_state.endVline
      val startIndex = in_state.startIndex
      val nElements = in_state.nElements
      val currentTag = in_state.currentTag
      val currentVline = in_state.currentVline
      val isLoad = in_state.isLoad
      val memVe = in_state.memVe
      val memEb = in_state.memEb
      val memBitAddrInVline = in_state.memBitAddrInVline
      val memVOffset = in_state.memVOffset
      val storeRegVe = in_state.storeRegVe
      val storeRegEb = in_state.storeRegEb
      val baseBitAddr = in_state.baseBitAddr

      // -----------------------------------------------------------------------
      // LoadJ2JWords: Use pre-computed wide add, derive remaining values
      // -----------------------------------------------------------------------
      val loadRegBitAddr = in_state.loadRegBitAddr
      val loadRegEb = Wire(UInt(ebWidth.W))
      loadRegEb := loadRegBitAddr & (regEw - 1.U)
      val loadRegVw = Wire(UInt(vwWidth.W))
      val loadRegBitAddrShifted = shiftRightByEwCode(loadRegBitAddr, regEwCode)
      loadRegVw := loadRegBitAddrShifted & (jInL - 1.U)
      val loadRegWe = Wire(UInt(vlineWidth.W))
      loadRegWe := loadRegBitAddrShifted >> log2JInL

      val loadNBits = Wire(UInt(ebPlusOneWidth.W))
      loadNBits := (regEw - loadRegEb).min(memEw - memEb)
      val loadNBytes = Wire(UInt(4.W))
      loadNBytes := loadNBits >> 3

      val loadRegVe = Wire(UInt(vlineWidth.W))
      loadRegVe := (loadRegWe << log2JInL) + loadRegVw
      val loadElementIndex = Wire(UInt(vlineWidth.W))
      loadElementIndex := loadRegVe +& (currentVline << log2RegElementsInVline)
      val loadInRange = (startIndex <= loadElementIndex) &&
                        (loadElementIndex < startIndex +& nElements)

      val loadAlreadyHandled = (memEb =/= 0.U) && (loadRegEb =/= 0.U)

      val loadRegWb = Wire(UInt((tagWidth + 3).W))
      loadRegWb := shiftLeftByEwCode(loadRegWe, regEwCode) + loadRegEb
      val loadDstTag = Wire(UInt(tagWidth.W))
      loadDstTag := loadRegWb >> 3

      // -----------------------------------------------------------------------
      // StoreJ2JWords: Use pre-computed wide add, derive remaining values
      // -----------------------------------------------------------------------
      val storeMemBitAddr = in_state.storeMemBitAddr
      val storeMemEb = Wire(UInt(ebWidth.W))
      storeMemEb := storeMemBitAddr & (memEw - 1.U)
      val storeMemVw = Wire(UInt(vwWidth.W))
      val storeMemBitAddrShifted = shiftRightByEwCode(storeMemBitAddr, memEwCode)
      storeMemVw := storeMemBitAddrShifted & (jInL - 1.U)
      val storeMemWe = Wire(UInt(vlineWidth.W))
      storeMemWe := storeMemBitAddrShifted >> log2JInL

      val storeNBits = Wire(UInt(ebPlusOneWidth.W))
      storeNBits := (memEw - storeMemEb).min(regEw - storeRegEb)
      val storeNBytes = Wire(UInt(4.W))
      storeNBytes := storeNBits >> 3

      val storeElementIndex = Wire(UInt(vlineWidth.W))
      storeElementIndex := storeRegVe +& (currentVline << log2RegElementsInVline)
      val storeInRange = (startIndex <= storeElementIndex) &&
                         (storeElementIndex < startIndex +& nElements)

      val storeAlreadyHandled = (storeMemEb =/= 0.U) && (storeRegEb =/= 0.U)

      val storeMemWb = Wire(UInt((tagWidth + 3).W))
      storeMemWb := shiftLeftByEwCode(storeMemWe, memEwCode) + storeMemEb
      val storeDstTag = Wire(UInt(tagWidth.W))
      storeDstTag := storeMemWb >> 3

      // -----------------------------------------------------------------------
      // Select based on isLoad
      // -----------------------------------------------------------------------
      val nBytes = Wire(UInt(4.W))
      nBytes := Mux(isLoad, loadNBytes, storeNBytes)
      val targetVw = Wire(UInt(vwWidth.W))
      targetVw := Mux(isLoad, loadRegVw, storeMemVw)
      val dstTag = Wire(UInt(tagWidth.W))
      dstTag := Mux(isLoad, loadDstTag, storeDstTag)
      val inRange = Mux(isLoad, loadInRange, storeInRange)
      val alreadyHandled = Mux(isLoad, loadAlreadyHandled, storeAlreadyHandled)

      // Convert target vw to coordinates
      val targetWordOrder = Mux(isLoad, in_state.rfWordOrder, in_state.memWordOrder)
      val (targetX, targetY) = WitemMonitorUtils.vwIndexToCoords(params, targetWordOrder, targetVw)

      // -----------------------------------------------------------------------
      // Output valid: in vline range, not already handled, element in range
      // -----------------------------------------------------------------------
      val inVlineRange = (currentVline >= startVline) && (currentVline <= endVline)
      val emitValid = inVlineRange && !alreadyHandled && inRange

      // -----------------------------------------------------------------------
      // State advancement
      // -----------------------------------------------------------------------
      val needJumpToStart = !in_state.iterating || (currentVline < startVline)
      val atEndOfVlineLoop = currentVline >= endVline

      val nextVline = Wire(UInt(vlineWidth.W))
      nextVline := Mux(needJumpToStart, startVline,
                       Mux(atEndOfVlineLoop, startVline, currentVline + 1.U))
      val advanceTag = in_state.iterating && atEndOfVlineLoop
      val nextTag = Wire(UInt(tagPlusOneWidth.W))
      nextTag := Mux(advanceTag, currentTag +& nBytes, currentTag)
      val iterDone = nextTag >= wordBytes

      // Next state: go back to phase 0
      result.nextState.phase := false.B
      result.nextState.iterating := !iterDone
      result.nextState.currentTag := Mux(iterDone, 0.U, nextTag)
      result.nextState.currentVline := Mux(iterDone, 0.U, nextVline)
      // Clear intermediates
      result.nextState.memEw := 0.U
      result.nextState.regEw := 0.U
      result.nextState.memEwCode := EwCode.Ew8
      result.nextState.regEwCode := EwCode.Ew8
      result.nextState.log2RegElementsInVline := 0.U
      result.nextState.startVline := 0.U
      result.nextState.endVline := 0.U
      result.nextState.startIndex := 0.U
      result.nextState.nElements := 0.U
      result.nextState.tagWb := 0.U
      result.nextState.thisVw := 0.U
      result.nextState.isLoad := false.B
      result.nextState.memVe := 0.U
      result.nextState.memEb := 0.U
      result.nextState.memBitAddrInVline := 0.U
      result.nextState.memVOffset := 0.U
      result.nextState.storeRegVe := 0.U
      result.nextState.storeRegEb := 0.U
      result.nextState.rfWordOrder := WordOrder.Standard
      result.nextState.memWordOrder := WordOrder.Standard
      result.nextState.baseBitAddr := 0.U
      result.nextState.loadRegBitAddr := 0.U
      result.nextState.storeMemBitAddr := 0.U

      // -----------------------------------------------------------------------
      // Output bundle
      // -----------------------------------------------------------------------
      // For load: rfV is the mem vline to read (currentVline + memVOffset)
      // For store: rfV is the reg vline to read (currentVline)
      result.output.rfV := Mux(isLoad, currentVline + memVOffset, currentVline)
      result.output.srcTag := currentTag
      result.output.dstTag := dstTag
      result.output.nBytes := nBytes
      result.output.targetX := targetX
      result.output.targetY := targetY

      // On first cycle (!iterating), we jump to startVline but don't emit
      // This ensures we start at the correct vline position
      result.outValid := in_state.iterating && emitValid
      result.finished := iterDone
      result.invalidEw := j2jEwError
    }

    result
  }
}

class S11StridedIndexedResult(params: JamletParams) extends Bundle {
  val output = new S12S13Reg(params)
  val nextState = new S11StridedIndexedState(params)
  val outValid = Bool()       // Emit to S12+ (send packet)
  val skipAndComplete = Bool() // Don't send, but set tag srcState=Complete directly
  val finished = Bool()
}

/**
 * Strided/indexed tag iteration.
 *
 * Implements logic matching python/zamlet/transactions/{load,store}_scatter_base.py.
 *
 * Key insight: iteration is over RF byte positions (tag = 0 to wordBytes-1).
 * For each tag, we check if it's at a boundary (rfEb == 0 or memEb == 0).
 *
 * - srcTag: RF byte position (for stores, where to read from RF)
 * - dstTag: memory byte position (for packet header)
 */
object S11StridedIndexed {
  def compute(
    params: JamletParams,
    in_input: S10S11Reg,
    in_state: S11StridedIndexedState
  ): S11StridedIndexedResult = {
    val result = Wire(new S11StridedIndexedResult(params))

    // Width constants
    val tagWidth = params.log2WordBytes
    val tagPlusOneWidth = params.log2WordBytes + 1
    val ebWidth = 3  // Element boundary: 0-7 for max 8-byte elements
    val ebPlusOneWidth = 4  // For byte counts: 1-8

    // Fault tracking: reset on new entry, set on TLB fault, persists across elements
    val isNewEntry = in_input.instrIdent =/= in_state.lastInstrIdent
    val effectiveFaulted = Mux(isNewEntry, false.B, in_state.faulted) || in_input.tlbFault

    // Pass-through fields (always set regardless of phase)
    result.output.entryIndex := in_input.entryIndex
    result.output.instrIdent := in_input.instrIdent
    result.output.witemType := in_input.witemType
    result.output.witemInfo := in_input.witemInfo
    result.output.rfV := in_input.rfV
    result.output.isVpu := in_input.isVpu

    // Propagate fault state, element index, and instrIdent to next state
    result.nextState.faulted := effectiveFaulted
    // Record element index on first fault (when transitioning from not-faulted to faulted)
    val newFault = in_input.tlbFault && !Mux(isNewEntry, false.B, in_state.faulted)
    result.nextState.faultElementIndex := Mux(newFault, in_input.elementIndex, in_state.faultElementIndex)
    result.nextState.lastInstrIdent := in_input.instrIdent

    when(!in_state.phase) {
      // =========================================================================
      // Phase 0: Compute intermediate values, store in state
      // =========================================================================

      // Decode strided instruction from kinstr
      val kinstr = KInstr.asStrided(params, in_input.witemInfo.kinstr)

      val wordBytes = params.wordBytes.U
      val rfEwBits = WitemMonitorUtils.ewCodeToBits(kinstr.rfEw)
      val memEwBits = WitemMonitorUtils.ewCodeToBits(in_input.memEwCode)

      val rfElementBytes = Wire(UInt(ebPlusOneWidth.W))
      rfElementBytes := rfEwBits >> 3
      val memElementBytes = Wire(UInt(ebPlusOneWidth.W))
      memElementBytes := memEwBits >> 3

      // Compute element's start position within RF word
      val elementStartInWord = Wire(UInt(tagWidth.W))
      elementStartInWord := (in_input.elementIndex * rfElementBytes) & (wordBytes - 1.U)

      // For page-crossing portions:
      val portionStartInWord = Wire(UInt(tagWidth.W))
      portionStartInWord := elementStartInWord +& in_input.elementByteOffset
      val portionEndInWord = Wire(UInt(tagPlusOneWidth.W))
      portionEndInWord := portionStartInWord +& in_input.portionBytes - 1.U

      // Current RF byte position (tag)
      val currentTag = Wire(UInt(tagPlusOneWidth.W))
      currentTag := Mux(in_state.iterating, in_state.previousTag, portionStartInWord)

      // Offset within the portion (for computing memory address)
      val offsetInPortion = Wire(UInt(tagWidth.W))
      offsetInPortion := currentTag - portionStartInWord

      // Offset within the element (for RF boundary check)
      val offsetInElement = Wire(UInt(ebPlusOneWidth.W))
      offsetInElement := in_input.elementByteOffset +& offsetInPortion

      // Store intermediates in next state
      result.nextState.phase := true.B
      result.nextState.iterating := in_state.iterating
      result.nextState.previousTag := in_state.previousTag
      result.nextState.offsetInPortion := offsetInPortion
      result.nextState.offsetInElement := offsetInElement
      result.nextState.currentTag := currentTag
      result.nextState.portionEndInWord := portionEndInWord
      result.nextState.rfElementBytes := rfElementBytes
      result.nextState.memElementBytes := memElementBytes

      // Phase 0 doesn't emit output
      result.output.srcTag := 0.U
      result.output.dstTag := 0.U
      result.output.nBytes := 0.U
      result.output.targetX := 0.U
      result.output.targetY := 0.U
      result.output.paddr := 0.U
      result.outValid := false.B
      result.skipAndComplete := false.B
      result.finished := false.B

    }.otherwise {
      // =========================================================================
      // Phase 1: Use stored intermediates, compute outputs
      // =========================================================================

      // Read intermediates from state
      val offsetInPortion = in_state.offsetInPortion
      val offsetInElement = in_state.offsetInElement
      val currentTag = in_state.currentTag
      val portionEndInWord = in_state.portionEndInWord
      val rfElementBytes = in_state.rfElementBytes
      val memElementBytes = in_state.memElementBytes

      // RF element boundary: byte offset within RF element
      val rfEb = Wire(UInt(ebWidth.W))
      rfEb := offsetInElement & (rfElementBytes - 1.U)

      // Memory address for this tag (WIDE ADDS - now at start of phase 1)
      val memAddrForTag = Wire(UInt(params.memAddrWidth.W))
      memAddrForTag := in_input.gAddr +& offsetInPortion
      val paddrForTag = Wire(UInt(params.memAddrWidth.W))
      paddrForTag := in_input.paddr +& offsetInPortion

      // Memory element boundary: byte offset within memory element
      val memEb = Wire(UInt(ebWidth.W))
      memEb := memAddrForTag & (memElementBytes - 1.U)

      // Tag is active at RF or memory element boundary
      val tagActive = (rfEb === 0.U) || (memEb === 0.U)

      // Compute nBytes: minimum of bytes to next RF boundary, memory boundary, or end
      val bytesToRfBoundary = Wire(UInt(ebPlusOneWidth.W))
      bytesToRfBoundary := rfElementBytes - rfEb
      val bytesToMemBoundary = Wire(UInt(ebPlusOneWidth.W))
      bytesToMemBoundary := memElementBytes - memEb
      val bytesToEnd = Wire(UInt(tagPlusOneWidth.W))
      bytesToEnd := portionEndInWord - currentTag + 1.U
      val nBytes = Wire(UInt(ebPlusOneWidth.W))
      nBytes := bytesToRfBoundary.min(bytesToMemBoundary).min(bytesToEnd)

      // Target coordinates from physical address (for VPU memory)
      val vwIndex = (paddrForTag >> params.log2WordBytes) & (params.jInL - 1).U
      val (targetX, targetY) = WitemMonitorUtils.vwIndexToCoords(params, in_input.memWordOrder, vwIndex)

      // srcTag = RF byte position (for stores, S13 reads from here)
      // dstTag = memory byte position (for packet header)
      result.output.srcTag := currentTag
      result.output.dstTag := paddrForTag(tagWidth - 1, 0)
      result.output.nBytes := nBytes
      result.output.targetX := targetX
      result.output.targetY := targetY
      result.output.paddr := paddrForTag

      // Advance to next tag position
      val nextTag = Wire(UInt(tagPlusOneWidth.W))
      nextTag := currentTag +& nBytes
      val iterDone = nextTag > portionEndInWord

      // Next state: go back to phase 0
      result.nextState.phase := false.B
      result.nextState.iterating := !iterDone
      result.nextState.previousTag := nextTag
      // Clear intermediates (not strictly necessary but cleaner)
      result.nextState.offsetInPortion := 0.U
      result.nextState.offsetInElement := 0.U
      result.nextState.currentTag := 0.U
      result.nextState.portionEndInWord := 0.U
      result.nextState.rfElementBytes := 0.U
      result.nextState.memElementBytes := 0.U

      // Emit output when tag is active and not faulted
      // When faulted, skip sending but signal to set tag Complete directly
      result.outValid := tagActive && !effectiveFaulted
      result.skipAndComplete := tagActive && effectiveFaulted

      // Finished when past the last tag
      result.finished := iterDone
    }

    result
  }
}

class CandidateSelect(params: JamletParams) extends Bundle {
  val idx = UInt(log2Ceil(params.witemTableDepth).W)
  val prio = UInt(log2Ceil(params.witemTableDepth).W)
  val valid = Bool()
}

class S1S2Reg(params: JamletParams) extends Bundle {
  val entryIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val witemType = WitemType()
}

class S2S3Reg(params: JamletParams) extends Bundle {
  val entryIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val witemType = WitemType()
}

class S3S4Reg(params: JamletParams) extends Bundle {
  val entryIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val witemType = WitemType()
  val witemInfo = new WitemInfoResp(params)
  // Pre-computed in S3 to break critical path (elementIndex arithmetic)
  val elementIndex = params.elementIndex()
}

class S4S5Reg(params: JamletParams) extends Bundle {
  val entryIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val witemType = WitemType()
  val witemInfo = new WitemInfoResp(params)
  val elementIndex = params.elementIndex()
  val elementActive = Bool()
  val rfV = UInt(log2Ceil(params.rfSliceWords).W)
  val maskBitPos = UInt(6.W)
  val indexBytePos = UInt(3.W)
}

class S5S6Reg(params: JamletParams) extends Bundle {
  val entryIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val witemType = WitemType()
  val witemInfo = new WitemInfoResp(params)
  val elementIndex = params.elementIndex()
  val elementActive = Bool()
  val rfV = UInt(log2Ceil(params.rfSliceWords).W)
  val maskBitPos = UInt(6.W)
  val indexBytePos = UInt(3.W)
}

class S6S7Reg(params: JamletParams) extends Bundle {
  val entryIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val witemType = WitemType()
  val witemInfo = new WitemInfoResp(params)
  val elementIndex = params.elementIndex()
  val elementActive = Bool()
  val rfV = UInt(log2Ceil(params.rfSliceWords).W)
  val maskBitPos = UInt(6.W)
  val indexBytePos = UInt(3.W)
  val maskWord = UInt(64.W)
  val indexWord = UInt(64.W)
  val stridedOffset = UInt(params.memAddrWidth.W)  // Pre-computed elementIndex * strideBytes
}

class S7S8Reg(params: JamletParams) extends Bundle {
  val entryIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val witemType = WitemType()
  val witemInfo = new WitemInfoResp(params)
  val elementIndex = params.elementIndex()
  val elementActive = Bool()
  val rfV = UInt(log2Ceil(params.rfSliceWords).W)
  val gAddr = params.memAddr()
  val crossesPage = Bool()
  val pageBoundary = params.memAddr()
}

class S8S9Reg(params: JamletParams) extends Bundle {
  val entryIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val witemType = WitemType()
  val witemInfo = new WitemInfoResp(params)
  val elementIndex = params.elementIndex()
  val elementActive = Bool()
  val rfV = UInt(log2Ceil(params.rfSliceWords).W)
  val gAddr = params.memAddr()
  val isSecondPage = Bool()
  val elementByteOffset = UInt(log2Ceil(params.wordBytes).W)
  val portionBytes = UInt(log2Ceil(params.wordBytes + 1).W)
}

class S10S11Reg(params: JamletParams) extends Bundle {
  val entryIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val witemType = WitemType()
  val witemInfo = new WitemInfoResp(params)
  val elementIndex = params.elementIndex()
  val elementActive = Bool()
  val rfV = UInt(log2Ceil(params.rfSliceWords).W)
  val gAddr = params.memAddr()
  val isSecondPage = Bool()
  val elementByteOffset = UInt(log2Ceil(params.wordBytes).W)
  val portionBytes = UInt(log2Ceil(params.wordBytes + 1).W)
  // TLB response
  val paddr = params.memAddr()
  val isVpu = Bool()
  val memEwCode = EwCode()
  val memWordOrder = WordOrder()
  val tlbFault = Bool()
}

class S12S13Reg(params: JamletParams) extends Bundle {
  val entryIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val witemType = WitemType()
  val witemInfo = new WitemInfoResp(params)
  val rfV = UInt(log2Ceil(params.rfSliceWords).W)
  // Per-tag info emitted by S11 iteration
  val srcTag = UInt(log2Ceil(params.wordBytes).W)
  val dstTag = UInt(log2Ceil(params.wordBytes).W)
  val nBytes = UInt(log2Ceil(params.wordBytes + 1).W)
  val targetX = params.xPos()
  val targetY = params.yPos()
  val isVpu = Bool()
  val paddr = params.memAddr()
}

class S13S14Reg(params: JamletParams) extends Bundle {
  val entryIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val witemType = WitemType()
  val witemInfo = new WitemInfoResp(params)
  val rfV = UInt(log2Ceil(params.rfSliceWords).W)
  val srcTag = UInt(log2Ceil(params.wordBytes).W)
  val dstTag = UInt(log2Ceil(params.wordBytes).W)
  val nBytes = UInt(log2Ceil(params.wordBytes + 1).W)
  val targetX = params.xPos()
  val targetY = params.yPos()
  val isVpu = Bool()
  val paddr = params.memAddr()
}

class S14S15Reg(params: JamletParams) extends Bundle {
  val entryIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val witemType = WitemType()
  val srcTag = UInt(log2Ceil(params.wordBytes).W)
  val dstTag = UInt(log2Ceil(params.wordBytes).W)
  val nBytes = UInt(log2Ceil(params.wordBytes + 1).W)
  val targetX = params.xPos()
  val targetY = params.yPos()
  val isVpu = Bool()
  val paddr = params.memAddr()
  // Indicates whether data read was issued (stores and cache loads)
  val needsDataResp = Bool()
  // Indicates SRAM read (vs RF read)
  val isSramRead = Bool()
}

class S15S16Reg(params: JamletParams) extends Bundle {
  val entryIndex = UInt(log2Ceil(params.witemTableDepth).W)
  val instrIdent = params.ident()
  val witemType = WitemType()
  val srcTag = UInt(log2Ceil(params.wordBytes).W)
  val dstTag = UInt(log2Ceil(params.wordBytes).W)
  val nBytes = UInt(log2Ceil(params.wordBytes + 1).W)
  val targetX = params.xPos()
  val targetY = params.yPos()
  val isVpu = Bool()
  val paddr = params.memAddr()
  val needsDataResp = Bool()
  val isSramRead = Bool()
}

class WitemMonitor(params: JamletParams) extends Module {
  val wmp = params.witemMonitorParams

  val io = IO(new Bundle {
    // Position
    val thisX = Input(params.xPos())
    val thisY = Input(params.yPos())

    // From Kamlet (witem lifecycle)
    val witemCreate = Flipped(Valid(new WitemCreate(params)))
    val witemCacheAvail = Flipped(Valid(params.ident()))
    val witemRemove = Flipped(Valid(params.ident()))
    val witemComplete = Valid(params.ident())

    // Witem info lookup (to KamletWitemTable)
    val witemInfoReq = Decoupled(new WitemInfoReq(params))
    val witemInfoResp = Flipped(Decoupled(new WitemInfoResp(params)))

    // State updates from RX handlers
    val witemSrcUpdate = Flipped(Valid(new WitemSrcUpdate(params)))
    val witemDstUpdate = Flipped(Valid(new WitemDstUpdate(params)))

    // Sync interface to KamletWitemTable
    val witemFaultReady = Valid(new WitemFaultReady(params))
    val witemCompleteReady = Valid(params.ident())
    val witemFaultSync = Flipped(Valid(new WitemFaultSync(params)))
    val witemCompletionSync = Flipped(Valid(new WitemCompletionSync(params)))

    // TLB interface
    val tlbReq = Decoupled(new TlbReq(params))
    val tlbResp = Flipped(Decoupled(new TlbResp(params)))

    // SRAM interface
    val sramReq = Decoupled(new SramReq(params))
    val sramResp = Flipped(Decoupled(new SramResp(params)))

    // RF interfaces (separate ports for mask, index, and data)
    val maskRfReq = Decoupled(new RfReq(params))
    val maskRfResp = Flipped(Decoupled(new RfResp(params)))
    val indexRfReq = Decoupled(new RfReq(params))
    val indexRfResp = Flipped(Decoupled(new RfResp(params)))
    val dataRfReq = Decoupled(new RfReq(params))
    val dataRfResp = Flipped(Decoupled(new RfResp(params)))

    // Packet output to arbiter
    val packetOut = Decoupled(new NetworkWord(params))

    // Error signals
    val err = Output(new WitemMonitorErrors())
  })

  // Register thisX and thisY to break long combinational paths
  val thisX = RegNext(io.thisX)
  val thisY = RegNext(io.thisY)

  // -------------------------------------------------------------------------
  // Optional buffers for Decoupled interfaces
  // -------------------------------------------------------------------------

  // Witem info lookup
  val witemInfoReq = Wire(Decoupled(new WitemInfoReq(params)))
  io.witemInfoReq <> DoubleBuffer(witemInfoReq,
    wmp.witemInfoReqForwardBuffer, wmp.witemInfoReqBackwardBuffer)
  val witemInfoResp = DoubleBuffer(io.witemInfoResp,
    wmp.witemInfoRespForwardBuffer, wmp.witemInfoRespBackwardBuffer)

  // TLB interface
  val tlbReq = Wire(Decoupled(new TlbReq(params)))
  io.tlbReq <> DoubleBuffer(tlbReq, wmp.tlbReqForwardBuffer, wmp.tlbReqBackwardBuffer)
  val tlbResp = DoubleBuffer(io.tlbResp, wmp.tlbRespForwardBuffer, wmp.tlbRespBackwardBuffer)

  // SRAM interface
  val sramReq = Wire(Decoupled(new SramReq(params)))
  io.sramReq <> DoubleBuffer(sramReq, wmp.sramReqForwardBuffer, wmp.sramReqBackwardBuffer)
  val sramResp = DoubleBuffer(io.sramResp, wmp.sramRespForwardBuffer, wmp.sramRespBackwardBuffer)

  // RF interfaces
  val maskRfReq = Wire(Decoupled(new RfReq(params)))
  io.maskRfReq <> DoubleBuffer(maskRfReq,
    wmp.maskRfReqForwardBuffer, wmp.maskRfReqBackwardBuffer)
  val maskRfResp = DoubleBuffer(io.maskRfResp,
    wmp.maskRfRespForwardBuffer, wmp.maskRfRespBackwardBuffer)

  val indexRfReq = Wire(Decoupled(new RfReq(params)))
  io.indexRfReq <> DoubleBuffer(indexRfReq,
    wmp.indexRfReqForwardBuffer, wmp.indexRfReqBackwardBuffer)
  val indexRfResp = DoubleBuffer(io.indexRfResp,
    wmp.indexRfRespForwardBuffer, wmp.indexRfRespBackwardBuffer)

  val dataRfReq = Wire(Decoupled(new RfReq(params)))
  io.dataRfReq <> DoubleBuffer(dataRfReq,
    wmp.dataRfReqForwardBuffer, wmp.dataRfReqBackwardBuffer)
  val dataRfResp = DoubleBuffer(io.dataRfResp,
    wmp.dataRfRespForwardBuffer, wmp.dataRfRespBackwardBuffer)

  // Packet output
  val packetOut = Wire(Decoupled(new NetworkWord(params)))
  io.packetOut <> DoubleBuffer(packetOut,
    wmp.packetOutForwardBuffer, wmp.packetOutBackwardBuffer)

  // -------------------------------------------------------------------------
  // Optional buffers for Valid interfaces
  // -------------------------------------------------------------------------

  // Sync outputs
  val witemFaultReady = Wire(Valid(new WitemFaultReady(params)))
  io.witemFaultReady := ValidBuffer(witemFaultReady, wmp.witemFaultReadyOutputReg)

  val witemCompleteReady = Wire(Valid(params.ident()))
  io.witemCompleteReady := ValidBuffer(witemCompleteReady, wmp.witemCompleteReadyOutputReg)

  // Sync inputs
  val witemFaultSync = ValidBuffer(io.witemFaultSync, wmp.witemFaultSyncInputReg)
  val witemCompletionSync = ValidBuffer(io.witemCompletionSync, wmp.witemCompletionSyncInputReg)

  // Error output
  val err = Wire(new WitemMonitorErrors())
  if (wmp.errOutputReg) {
    io.err := RegNext(err)
  } else {
    io.err := err
  }

  // Entry table
  val initEntry = Wire(new WitemEntry(params))
  initEntry.valid := false.B
  initEntry.instrIdent := DontCare
  initEntry.witemType := DontCare
  initEntry.state := DontCare
  initEntry.tagStates := DontCare
  initEntry.readyForS1 := DontCare
  initEntry.priority := DontCare
  val entries = RegInit(VecInit.fill(params.witemTableDepth)(initEntry))
  val nextPriority = RegInit(0.U(log2Ceil(params.witemTableDepth).W))

  // -------------------------------------------------------------------------
  // Optional input register for witemCreate
  // -------------------------------------------------------------------------
  val witemCreateIn = if (wmp.witemCreateInputReg) {
    RegNext(io.witemCreate)
  } else {
    io.witemCreate
  }

  // -------------------------------------------------------------------------
  // Entry Allocation (witemCreate)
  // -------------------------------------------------------------------------
  val freeSlotValid = entries.map(!_.valid)
  val freeSlotIndex = PriorityEncoder(freeSlotValid)
  val hasFreeSlot = freeSlotValid.reduce(_ || _)

  err.noFreeSlot := witemCreateIn.valid && !hasFreeSlot

  val maxPriority = (params.witemTableDepth - 1).U
  err.priorityOverflow := witemCreateIn.valid && hasFreeSlot && nextPriority === maxPriority

  // For src-only types, dst state starts COMPLETE
  val isSrcOnlyType = (witemCreateIn.bits.witemType === WitemType.LoadStride) ||
                      (witemCreateIn.bits.witemType === WitemType.LoadIdxUnord) ||
                      (witemCreateIn.bits.witemType === WitemType.LoadIdxElement)

  when(witemCreateIn.valid && hasFreeSlot) {
    val slot = entries(freeSlotIndex)
    slot.valid := true.B
    slot.instrIdent := witemCreateIn.bits.instrIdent
    slot.witemType := witemCreateIn.bits.witemType
    slot.state := Mux(witemCreateIn.bits.cacheIsAvail,
                      WitemEntryState.Active,
                      WitemEntryState.WaitingForCache)
    slot.readyForS1 := witemCreateIn.bits.cacheIsAvail
    slot.priority := nextPriority

    for (i <- 0 until params.wordBytes) {
      slot.tagStates(i).srcState := WitemSendState.Initial
      slot.tagStates(i).dstState := Mux(isSrcOnlyType,
                                        WitemRecvState.Complete,
                                        WitemRecvState.WaitingForRequest)
    }

    nextPriority := nextPriority + 1.U
  }

  // -------------------------------------------------------------------------
  // Optional input register for witemCacheAvail
  // -------------------------------------------------------------------------
  val witemCacheAvailIn = if (wmp.witemCacheAvailInputReg) {
    RegNext(io.witemCacheAvail)
  } else {
    io.witemCacheAvail
  }

  // -------------------------------------------------------------------------
  // Cache Available (witemCacheAvail)
  // -------------------------------------------------------------------------
  val cacheAvailMatch = entries.map(e => e.valid && e.instrIdent === witemCacheAvailIn.bits)
  val cacheAvailIndex = OHToUInt(cacheAvailMatch)

  when(witemCacheAvailIn.valid) {
    entries(cacheAvailIndex).state := WitemEntryState.Active
    entries(cacheAvailIndex).readyForS1 := true.B
  }

  // -------------------------------------------------------------------------
  // Optional input register for witemRemove
  // -------------------------------------------------------------------------
  val witemRemoveIn = if (wmp.witemRemoveInputReg) {
    RegNext(io.witemRemove)
  } else {
    io.witemRemove
  }

  // -------------------------------------------------------------------------
  // Entry Removal (witemRemove) with priority compaction
  // -------------------------------------------------------------------------
  val removeMatch = entries.map(e => e.valid && e.instrIdent === witemRemoveIn.bits)
  val removeIndex = OHToUInt(removeMatch)

  when(witemRemoveIn.valid) {
    val removedPriority = entries(removeIndex).priority
    entries(removeIndex).valid := false.B

    // Compact priorities: decrement all entries with priority > removed
    for (i <- 0 until params.witemTableDepth) {
      when(entries(i).valid && entries(i).priority > removedPriority) {
        entries(i).priority := entries(i).priority - 1.U
      }
    }

    nextPriority := nextPriority - 1.U
  }

  // -------------------------------------------------------------------------
  // S1: Entry Selection (oldest-first among ready)
  // -------------------------------------------------------------------------
  val candidates = VecInit(entries.zipWithIndex.map { case (entry, idx) =>
    val c = Wire(new CandidateSelect(params))
    c.idx := idx.U
    c.prio := entry.priority
    c.valid := entry.valid && entry.readyForS1
    c
  })

  val selected = candidates.reduceTree { (a, b) =>
    val pick1 = a.valid && (!b.valid || a.prio <= b.prio)
    val result = Wire(new CandidateSelect(params))
    result.idx := Mux(pick1, a.idx, b.idx)
    result.prio := Mux(pick1, a.prio, b.prio)
    result.valid := a.valid || b.valid
    result
  }

  val s1SelectedIndex = selected.idx
  val s1SelectedEntry = entries(s1SelectedIndex)
  val s1Valid = selected.valid

  // -------------------------------------------------------------------------
  // S1 → S2 Pipeline: Entry Selection Output
  // -------------------------------------------------------------------------
  val s1Out = Wire(Decoupled(new S1S2Reg(params)))
  val s1Fire = s1Valid && s1Out.ready
  s1Out.valid := s1Valid
  s1Out.bits.entryIndex := s1SelectedIndex
  s1Out.bits.instrIdent := s1SelectedEntry.instrIdent
  s1Out.bits.witemType := s1SelectedEntry.witemType

  val s2In = DoubleBuffer(s1Out, wmp.s1s2ForwardBuffer, wmp.s1s2BackwardBuffer)

  // Clear readyForS1 when entry is selected and pipeline accepts it
  when(s1Fire) {
    entries(s1SelectedIndex).readyForS1 := false.B
  }

  // -------------------------------------------------------------------------
  // S2: Send Kamlet Request
  // -------------------------------------------------------------------------
  witemInfoReq.valid := s2In.valid && s2In.ready
  witemInfoReq.bits.instrIdent := s2In.bits.instrIdent

  val s2Out = Wire(Decoupled(new S2S3Reg(params)))
  s2Out.valid := s2In.valid && witemInfoReq.ready
  s2Out.bits.entryIndex := s2In.bits.entryIndex
  s2Out.bits.instrIdent := s2In.bits.instrIdent
  s2Out.bits.witemType := s2In.bits.witemType
  s2In.ready := s2Out.ready && witemInfoReq.ready

  val s3In = DoubleBuffer(s2Out, wmp.s2s3ForwardBuffer, wmp.s2s3BackwardBuffer)

  // -------------------------------------------------------------------------
  // S3: Receive Kamlet Response
  // -------------------------------------------------------------------------
  // Pre-compute elementIndex here to break S4 critical path
  // rfWordOrder and startIndex are at same bit positions for StridedInstr and IndexedInstr
  val s3Kinstr = KInstr.asStrided(params, witemInfoResp.bits.kinstr)
  val s3VwIndex = WitemMonitorUtils.coordsToVwIndex(params, s3Kinstr.rfWordOrder, thisX, thisY)
  val s3StartIndex = s3Kinstr.startIndex
  // Compute elementIndex: find this jamlet's element within the strided/indexed range
  val jInLMask = (params.jInL - 1).U
  val s3StartMod = s3StartIndex & jInLMask
  val s3BaseElement = s3StartIndex - s3StartMod + s3VwIndex
  val s3ElementIndex = Mux(s3BaseElement < s3StartIndex,
                           s3BaseElement + params.jInL.U,
                           s3BaseElement)

  val s3Out = Wire(Decoupled(new S3S4Reg(params)))
  s3Out.valid := s3In.valid && witemInfoResp.valid
  s3Out.bits.entryIndex := s3In.bits.entryIndex
  s3Out.bits.instrIdent := s3In.bits.instrIdent
  s3Out.bits.witemType := s3In.bits.witemType
  s3Out.bits.witemInfo := witemInfoResp.bits
  s3Out.bits.elementIndex := s3ElementIndex
  s3In.ready := s3Out.ready && witemInfoResp.valid
  witemInfoResp.ready := s3In.valid && s3Out.ready

  val s4In = DoubleBuffer(s3Out, wmp.s3s4ForwardBuffer, wmp.s3s4BackwardBuffer)

  // -------------------------------------------------------------------------
  // S4: Element Computation + RF Read Issue
  // -------------------------------------------------------------------------
  val s4IsJ2J = (s4In.bits.witemType === WitemType.LoadJ2JWords) ||
                (s4In.bits.witemType === WitemType.StoreJ2JWords)

  val s4IsWordSrc = (s4In.bits.witemType === WitemType.LoadWordSrc) ||
                    (s4In.bits.witemType === WitemType.StoreWordSrc)

  val s4IsStrided = (s4In.bits.witemType === WitemType.StoreStride) ||
                    (s4In.bits.witemType === WitemType.LoadStride)

  val s4IsIndexed = (s4In.bits.witemType === WitemType.StoreIdxUnord) ||
                    (s4In.bits.witemType === WitemType.LoadIdxUnord) ||
                    (s4In.bits.witemType === WitemType.LoadIdxElement)

  val s4NeedsMaskRf = s4IsStrided || s4IsIndexed
  val s4NeedsIndexRf = s4IsIndexed

  // Decode kinstr for strided/indexed ops (common fields at same positions)
  val s4KinstrStrided = KInstr.asStrided(params, s4In.bits.witemInfo.kinstr)
  val s4KinstrIndexed = KInstr.asIndexed(params, s4In.bits.witemInfo.kinstr)

  // Extract common fields (using Mux for clarity even though bit positions match)
  // Note: rfWordOrder, startIndex, and elementIndex now computed in S3
  val s4StartIndex = Mux(s4IsIndexed, s4KinstrIndexed.startIndex, s4KinstrStrided.startIndex)
  val s4RfEw = Mux(s4IsIndexed, s4KinstrIndexed.rfEw, s4KinstrStrided.rfEw)
  val s4MaskReg = Mux(s4IsIndexed, s4KinstrIndexed.maskReg, s4KinstrStrided.maskReg)
  val s4MaskEnabled = Mux(s4IsIndexed, s4KinstrIndexed.maskEnabled, s4KinstrStrided.maskEnabled)

  // Use pre-computed elementIndex from S3 (vwIndex multiply + elementIndex arithmetic moved)
  val s4ElementIndex = s4In.bits.elementIndex
  val log2JInL = params.log2JInL.U

  // Element is active if within range [startIndex, startIndex + nElements)
  val s4EndIndex = s4StartIndex + s4In.bits.witemInfo.nElements
  val s4ElementActive = (s4ElementIndex >= s4StartIndex) && (s4ElementIndex < s4EndIndex)

  // Mask bit position: element_index / jInL = element_index >> log2(jInL)
  val s4MaskBitPos = s4ElementIndex >> log2JInL

  // Index byte position within word (for indexed ops)
  // log2(vlineBits) = log2(wordWidth * jInL) = log2WordWidth + log2JInL
  // log2(elementsInVline) = log2(vlineBits) - log2(indexEw)
  val log2VlineBits = (params.log2WordWidth + params.log2JInL).U
  val s4IndexEw = s4KinstrIndexed.indexEw  // Only valid for indexed ops
  val s4Log2IndexEw = WitemMonitorUtils.ewCodeToLog2(s4IndexEw)
  val s4Log2IndexElementsPerVline = log2VlineBits - s4Log2IndexEw

  // index_v = element_index >> log2(elementsInVline)
  val s4IndexV = s4ElementIndex >> s4Log2IndexElementsPerVline
  // index_ve = element_index % elementsInVline
  val s4IndexVe = s4ElementIndex & WitemMonitorUtils.elementsInVlineMask(params, s4IndexEw)
  // index_we = index_ve >> log2(jInL)
  val s4IndexWe = s4IndexVe >> log2JInL
  // byte_in_word = (index_we << (log2(indexEw) - 3)) & (wordBytes - 1)
  val s4IndexByteShift = s4Log2IndexEw - 3.U
  val s4IndexBytePos = (s4IndexWe << s4IndexByteShift)(params.log2WordBytes - 1, 0)

  // RF vline offset for data read (using rf element width)
  val s4Log2RfEw = WitemMonitorUtils.ewCodeToLog2(s4RfEw)
  val s4Log2RfElementsPerVline = log2VlineBits - s4Log2RfEw
  val s4RfV = s4ElementIndex >> s4Log2RfElementsPerVline

  // Mask RF address: mask has 1 bit per element, wordWidth bits per word
  val s4MaskV = s4ElementIndex >> params.log2WordWidth.U
  val s4MaskRfAddr = s4MaskReg + s4MaskV

  // Index RF address (only valid for indexed ops)
  val s4IndexReg = s4KinstrIndexed.indexReg
  val s4IndexRfAddr = s4IndexReg + s4IndexV

  // Determine which RF requests are needed
  val s4NeedsMaskRfReq = s4NeedsMaskRf && s4MaskEnabled
  val s4NeedsIndexRfReq = s4NeedsIndexRf

  // Ready from each output path (true if not needed or if ready)
  val s4OutReady = Wire(Bool())
  val s4MaskRfPathReady = !s4NeedsMaskRfReq || maskRfReq.ready
  val s4IndexRfPathReady = !s4NeedsIndexRfReq || indexRfReq.ready

  // Issue mask RF read (valid when input valid and other paths ready)
  maskRfReq.valid := s4In.valid && s4NeedsMaskRfReq && s4OutReady && s4IndexRfPathReady
  maskRfReq.bits.addr := s4MaskRfAddr
  maskRfReq.bits.isWrite := false.B
  maskRfReq.bits.writeData := DontCare

  // Issue index RF read
  indexRfReq.valid := s4In.valid && s4NeedsIndexRfReq && s4OutReady && s4MaskRfPathReady
  indexRfReq.bits.addr := s4IndexRfAddr
  indexRfReq.bits.isWrite := false.B
  indexRfReq.bits.writeData := DontCare

  // S4 → S5 Pipeline Register
  val s4Out = Wire(Decoupled(new S4S5Reg(params)))
  s4Out.valid := s4In.valid && s4MaskRfPathReady && s4IndexRfPathReady
  s4Out.bits.entryIndex := s4In.bits.entryIndex
  s4Out.bits.instrIdent := s4In.bits.instrIdent
  s4Out.bits.witemType := s4In.bits.witemType
  s4Out.bits.witemInfo := s4In.bits.witemInfo
  s4Out.bits.elementIndex := s4ElementIndex
  s4Out.bits.elementActive := s4ElementActive
  s4Out.bits.rfV := s4RfV
  s4Out.bits.maskBitPos := s4MaskBitPos
  s4Out.bits.indexBytePos := s4IndexBytePos

  s4OutReady := s4Out.ready
  s4In.ready := s4OutReady && s4MaskRfPathReady && s4IndexRfPathReady

  val s5In = DoubleBuffer(s4Out, wmp.s4s5ForwardBuffer, wmp.s4s5BackwardBuffer)

  // -------------------------------------------------------------------------
  // S5: RF Read Wait (pass-through)
  // -------------------------------------------------------------------------
  val s5Out = Wire(Decoupled(new S5S6Reg(params)))
  s5Out.valid := s5In.valid
  s5Out.bits.entryIndex := s5In.bits.entryIndex
  s5Out.bits.instrIdent := s5In.bits.instrIdent
  s5Out.bits.witemType := s5In.bits.witemType
  s5Out.bits.witemInfo := s5In.bits.witemInfo
  s5Out.bits.elementIndex := s5In.bits.elementIndex
  s5Out.bits.elementActive := s5In.bits.elementActive
  s5Out.bits.rfV := s5In.bits.rfV
  s5Out.bits.maskBitPos := s5In.bits.maskBitPos
  s5Out.bits.indexBytePos := s5In.bits.indexBytePos
  s5In.ready := s5Out.ready

  val s6In = DoubleBuffer(s5Out, wmp.s5s6ForwardBuffer, wmp.s5s6BackwardBuffer)

  // -------------------------------------------------------------------------
  // S6: RF Response (receive mask and index words)
  // -------------------------------------------------------------------------
  val s6IsStrided = (s6In.bits.witemType === WitemType.StoreStride) ||
                    (s6In.bits.witemType === WitemType.LoadStride)
  val s6IsIndexed = (s6In.bits.witemType === WitemType.StoreIdxUnord) ||
                    (s6In.bits.witemType === WitemType.LoadIdxUnord) ||
                    (s6In.bits.witemType === WitemType.LoadIdxElement)

  // Decode kinstr for maskEnabled
  val s6KinstrStrided = KInstr.asStrided(params, s6In.bits.witemInfo.kinstr)
  val s6KinstrIndexed = KInstr.asIndexed(params, s6In.bits.witemInfo.kinstr)
  val s6MaskEnabled = Mux(s6IsIndexed, s6KinstrIndexed.maskEnabled, s6KinstrStrided.maskEnabled)

  val s6NeedsMaskResp = (s6IsStrided || s6IsIndexed) && s6MaskEnabled
  val s6NeedsIndexResp = s6IsIndexed

  val s6MaskRespReady = !s6NeedsMaskResp || maskRfResp.valid
  val s6IndexRespReady = !s6NeedsIndexResp || indexRfResp.valid

  val s6Out = Wire(Decoupled(new S6S7Reg(params)))

  maskRfResp.ready := s6In.valid && s6NeedsMaskResp && s6Out.ready && s6IndexRespReady
  indexRfResp.ready := s6In.valid && s6NeedsIndexResp && s6Out.ready && s6MaskRespReady

  s6Out.valid := s6In.valid && s6MaskRespReady && s6IndexRespReady
  s6Out.bits.entryIndex := s6In.bits.entryIndex
  s6Out.bits.instrIdent := s6In.bits.instrIdent
  s6Out.bits.witemType := s6In.bits.witemType
  s6Out.bits.witemInfo := s6In.bits.witemInfo
  s6Out.bits.elementIndex := s6In.bits.elementIndex
  s6Out.bits.elementActive := s6In.bits.elementActive
  s6Out.bits.rfV := s6In.bits.rfV
  s6Out.bits.maskBitPos := s6In.bits.maskBitPos
  s6Out.bits.indexBytePos := s6In.bits.indexBytePos
  s6Out.bits.maskWord := Mux(s6NeedsMaskResp, maskRfResp.bits.readData, 0.U)
  s6Out.bits.indexWord := Mux(s6NeedsIndexResp, indexRfResp.bits.readData, 0.U)
  // Pre-compute strided offset for S7 (moves multiply out of critical path)
  val s6Stride = s6In.bits.witemInfo.strideBytes
  val s6StridedOffset = Wire(UInt(params.memAddrWidth.W))
  s6StridedOffset := (s6In.bits.elementIndex.asSInt * s6Stride).asUInt
  s6Out.bits.stridedOffset := s6StridedOffset
  s6In.ready := s6Out.ready && s6MaskRespReady && s6IndexRespReady

  val s7In = DoubleBuffer(s6Out, wmp.s6s7ForwardBuffer, wmp.s6s7BackwardBuffer)

  // -------------------------------------------------------------------------
  // S7: Mask Check + Address Computation
  // -------------------------------------------------------------------------
  val s7IsStrided = (s7In.bits.witemType === WitemType.StoreStride) ||
                    (s7In.bits.witemType === WitemType.LoadStride)
  val s7IsIndexed = (s7In.bits.witemType === WitemType.StoreIdxUnord) ||
                    (s7In.bits.witemType === WitemType.LoadIdxUnord) ||
                    (s7In.bits.witemType === WitemType.LoadIdxElement)

  // Decode kinstr for strided/indexed ops
  val s7KinstrStrided = KInstr.asStrided(params, s7In.bits.witemInfo.kinstr)
  val s7KinstrIndexed = KInstr.asIndexed(params, s7In.bits.witemInfo.kinstr)

  // Extract common fields (using Mux for clarity even though bit positions match)
  val s7MaskEnabled = Mux(s7IsIndexed, s7KinstrIndexed.maskEnabled, s7KinstrStrided.maskEnabled)
  val s7RfEwCode = Mux(s7IsIndexed, s7KinstrIndexed.rfEw, s7KinstrStrided.rfEw)

  // Mask check
  val s7MaskBit = s7In.bits.maskWord(s7In.bits.maskBitPos)
  val s7MaskedOut = s7MaskEnabled && !s7MaskBit
  val s7ElementActive = s7In.bits.elementActive && !s7MaskedOut

  // Extract index value from indexWord (only valid for indexed ops)
  // Use explicit 8-way byte-aligned mux instead of barrel shifter
  val s7IndexWord = s7In.bits.indexWord
  val s7IndexShifted = Wire(UInt(64.W))
  s7IndexShifted := MuxLookup(s7In.bits.indexBytePos, s7IndexWord)(Seq(
    1.U -> Cat(0.U(8.W), s7IndexWord(63, 8)),
    2.U -> Cat(0.U(16.W), s7IndexWord(63, 16)),
    3.U -> Cat(0.U(24.W), s7IndexWord(63, 24)),
    4.U -> Cat(0.U(32.W), s7IndexWord(63, 32)),
    5.U -> Cat(0.U(40.W), s7IndexWord(63, 40)),
    6.U -> Cat(0.U(48.W), s7IndexWord(63, 48)),
    7.U -> Cat(0.U(56.W), s7IndexWord(63, 56))
  ))
  val s7IndexEw = s7KinstrIndexed.indexEw
  val s7IndexValue = Wire(UInt(64.W))
  s7IndexValue := s7IndexShifted & WitemMonitorUtils.ewCodeToMask(s7IndexEw)

  // Address computation (stridedOffset pre-computed in S6)
  val s7BaseAddr = s7In.bits.witemInfo.baseAddr
  val s7GAddr = Wire(UInt(params.memAddrWidth.W))
  s7GAddr := Mux(s7IsStrided, s7BaseAddr + s7In.bits.stridedOffset, s7BaseAddr + s7IndexValue)

  // Page crossing check
  val s7RfEw = Wire(UInt(7.W))
  s7RfEw := WitemMonitorUtils.ewCodeToBits(s7RfEwCode)
  val s7ElementBytes = Wire(UInt(4.W))
  s7ElementBytes := s7RfEw >> 3.U
  val s7ElementEndAddr = Wire(UInt(params.memAddrWidth.W))
  s7ElementEndAddr := s7GAddr +& s7ElementBytes - 1.U
  val log2PageBytes = params.log2PageBytesPerLamlet
  val s7PageNum = s7GAddr(params.memAddrWidth - 1, log2PageBytes)
  val s7EndPageNum = s7ElementEndAddr(params.memAddrWidth - 1, log2PageBytes)
  val s7CrossesPage = s7PageNum =/= s7EndPageNum
  val s7PageBoundary = Cat(s7PageNum + 1.U, 0.U(log2PageBytes.W))

  val s7Out = Wire(Decoupled(new S7S8Reg(params)))
  s7Out.valid := s7In.valid
  s7Out.bits.entryIndex := s7In.bits.entryIndex
  s7Out.bits.instrIdent := s7In.bits.instrIdent
  s7Out.bits.witemType := s7In.bits.witemType
  s7Out.bits.witemInfo := s7In.bits.witemInfo
  s7Out.bits.elementIndex := s7In.bits.elementIndex
  s7Out.bits.elementActive := s7ElementActive
  s7Out.bits.rfV := s7In.bits.rfV
  s7Out.bits.gAddr := s7GAddr
  s7Out.bits.crossesPage := s7CrossesPage
  s7Out.bits.pageBoundary := s7PageBoundary
  s7In.ready := s7Out.ready

  val s8In = DoubleBuffer(s7Out, wmp.s7s8ForwardBuffer, wmp.s7s8BackwardBuffer)

  // -------------------------------------------------------------------------
  // S8: TLB Issue
  // -------------------------------------------------------------------------
  // For strided/indexed ops, issue TLB request(s) to translate the element address.
  // If the element crosses a page boundary, this stage splits the single input into
  // two output paths - one for each page. The first path carries gAddr, the second
  // carries pageBoundary. Each path gets its own TLB response and handles its
  // portion of the element's tags in later stages.
  val s8IsStrided = (s8In.bits.witemType === WitemType.StoreStride) ||
                    (s8In.bits.witemType === WitemType.LoadStride)
  val s8IsIndexed = (s8In.bits.witemType === WitemType.StoreIdxUnord) ||
                    (s8In.bits.witemType === WitemType.LoadIdxUnord) ||
                    (s8In.bits.witemType === WitemType.LoadIdxElement)
  val s8NeedsTlb = s8IsStrided || s8IsIndexed

  val s8IsStore = (s8In.bits.witemType === WitemType.StoreStride) ||
                  (s8In.bits.witemType === WitemType.StoreIdxUnord)

  // State for page crossing: tracks if we're issuing the second request
  val s8IsSecondReq = RegInit(false.B)

  // TLB address: first request uses gAddr, second uses pageBoundary
  val s8TlbAddr = Mux(s8IsSecondReq, s8In.bits.pageBoundary, s8In.bits.gAddr)

  // Element byte offset: which byte of the element this path starts at
  // First path: 0, Second path: pageBoundary - originalGAddr
  val s8FirstPortionBytes = s8In.bits.pageBoundary - s8In.bits.gAddr
  val s8ElementByteOffset = Mux(s8IsSecondReq, s8FirstPortionBytes, 0.U)

  // Total element bytes and portion bytes for this path
  // Decode kinstr for rfEw
  val s8KinstrStrided = KInstr.asStrided(params, s8In.bits.witemInfo.kinstr)
  val s8KinstrIndexed = KInstr.asIndexed(params, s8In.bits.witemInfo.kinstr)
  val s8RfEw = Mux(s8IsIndexed, s8KinstrIndexed.rfEw, s8KinstrStrided.rfEw)
  val s8ElementBytes = WitemMonitorUtils.ewCodeToBits(s8RfEw) >> 3
  val s8SecondPortionBytes = s8ElementBytes - s8FirstPortionBytes
  val s8PortionBytes = Mux(s8IsSecondReq, s8SecondPortionBytes,
                           Mux(s8In.bits.crossesPage, s8FirstPortionBytes, s8ElementBytes))

  // Need TLB when valid, needs TLB, and element is active
  val s8TlbNeeded = s8In.valid && s8NeedsTlb && s8In.bits.elementActive

  // S8 output
  val s8Out = Wire(Decoupled(new S8S9Reg(params)))

  // Issue TLB when needed and downstream is ready
  tlbReq.valid := s8TlbNeeded && s8Out.ready
  tlbReq.bits.vaddr := s8TlbAddr
  tlbReq.bits.isWrite := s8IsStore

  // State machine: when first request fires and page crosses, prepare for second
  when(tlbReq.fire && !s8IsSecondReq && s8In.bits.crossesPage) {
    s8IsSecondReq := true.B
  }
  when(tlbReq.fire && s8IsSecondReq) {
    s8IsSecondReq := false.B
  }

  // Final request: either no page crossing, or this is the second request
  val s8FinalReq = !s8In.bits.crossesPage || s8IsSecondReq

  // Output valid when: pass-through (no TLB needed) OR TLB accepted
  s8Out.valid := s8In.valid && (!s8TlbNeeded || tlbReq.ready)
  s8Out.bits.entryIndex := s8In.bits.entryIndex
  s8Out.bits.instrIdent := s8In.bits.instrIdent
  s8Out.bits.witemType := s8In.bits.witemType
  s8Out.bits.witemInfo := s8In.bits.witemInfo
  s8Out.bits.elementIndex := s8In.bits.elementIndex
  s8Out.bits.elementActive := s8In.bits.elementActive
  s8Out.bits.rfV := s8In.bits.rfV
  s8Out.bits.gAddr := s8TlbAddr
  s8Out.bits.isSecondPage := s8IsSecondReq
  s8Out.bits.elementByteOffset := s8ElementByteOffset
  s8Out.bits.portionBytes := s8PortionBytes

  // Consume input only when pass-through or final request fires
  s8In.ready := s8Out.ready && (!s8TlbNeeded || (tlbReq.ready && s8FinalReq))

  val s9In = DoubleBuffer(s8Out, wmp.s8s9ForwardBuffer, wmp.s8s9BackwardBuffer)

  // -------------------------------------------------------------------------
  // S9: TLB Wait (pass-through)
  // -------------------------------------------------------------------------
  val s9Out = Wire(Decoupled(new S8S9Reg(params)))
  s9Out.valid := s9In.valid
  s9Out.bits := s9In.bits
  s9In.ready := s9Out.ready

  val s10In = DoubleBuffer(s9Out, wmp.s9s10ForwardBuffer, wmp.s9s10BackwardBuffer)

  // -------------------------------------------------------------------------
  // S10: TLB Response
  // -------------------------------------------------------------------------
  val s10IsStrided = (s10In.bits.witemType === WitemType.StoreStride) ||
                     (s10In.bits.witemType === WitemType.LoadStride)
  val s10IsIndexed = (s10In.bits.witemType === WitemType.StoreIdxUnord) ||
                     (s10In.bits.witemType === WitemType.LoadIdxUnord) ||
                     (s10In.bits.witemType === WitemType.LoadIdxElement)
  val s10NeedsTlb = s10IsStrided || s10IsIndexed

  // Need TLB response when we issued a request (active element with TLB-needing op)
  val s10NeedsTlbResp = s10NeedsTlb && s10In.bits.elementActive

  val s10TlbRespReady = !s10NeedsTlbResp || tlbResp.valid

  val s10Out = Wire(Decoupled(new S10S11Reg(params)))

  tlbResp.ready := s10In.valid && s10NeedsTlbResp && s10Out.ready

  s10Out.valid := s10In.valid && s10TlbRespReady
  s10Out.bits.entryIndex := s10In.bits.entryIndex
  s10Out.bits.instrIdent := s10In.bits.instrIdent
  s10Out.bits.witemType := s10In.bits.witemType
  s10Out.bits.witemInfo := s10In.bits.witemInfo
  s10Out.bits.elementIndex := s10In.bits.elementIndex
  s10Out.bits.elementActive := s10In.bits.elementActive
  s10Out.bits.rfV := s10In.bits.rfV
  s10Out.bits.gAddr := s10In.bits.gAddr
  s10Out.bits.isSecondPage := s10In.bits.isSecondPage
  s10Out.bits.elementByteOffset := s10In.bits.elementByteOffset
  s10Out.bits.portionBytes := s10In.bits.portionBytes
  s10Out.bits.paddr := tlbResp.bits.paddr
  s10Out.bits.isVpu := tlbResp.bits.isVpu
  s10Out.bits.memEwCode := tlbResp.bits.memEwCode
  s10Out.bits.memWordOrder := tlbResp.bits.memWordOrder
  s10Out.bits.tlbFault := tlbResp.bits.fault
  s10In.ready := s10Out.ready && s10TlbRespReady

  val s11In = DoubleBuffer(s10Out, wmp.s10s11ForwardBuffer, wmp.s10s11BackwardBuffer)

  // -------------------------------------------------------------------------
  // S11: Tag Iteration (one-to-many)
  //
  // J2J types: iterate over all word_bytes tags, for each active tag iterate
  //            over vlines in [startVline, endVline]
  // Strided/indexed: iterate over tags within a single element
  // WordSrc types: pass through (no iteration, single whole-word transfer)
  // -------------------------------------------------------------------------

  val s11IsJ2J = (s11In.bits.witemType === WitemType.LoadJ2JWords) ||
                 (s11In.bits.witemType === WitemType.StoreJ2JWords)

  val s11IsWordSrc = (s11In.bits.witemType === WitemType.LoadWordSrc) ||
                     (s11In.bits.witemType === WitemType.StoreWordSrc)

  // J2J state and computation
  val s11J2JState = RegInit({
    val init = Wire(new S11J2JState(params))
    init.iterating := false.B
    init.currentTag := 0.U
    init.currentVline := 0.U
    init.phase := false.B
    init.memEw := 0.U
    init.regEw := 0.U
    init.memEwCode := EwCode.Ew8
    init.regEwCode := EwCode.Ew8
    init.log2RegElementsInVline := 0.U
    init.startVline := 0.U
    init.endVline := 0.U
    init.startIndex := 0.U
    init.nElements := 0.U
    init.tagWb := 0.U
    init.thisVw := 0.U
    init.isLoad := false.B
    init.memVe := 0.U
    init.memEb := 0.U
    init.memBitAddrInVline := 0.U
    init.memVOffset := 0.U
    init.storeRegVe := 0.U
    init.storeRegEb := 0.U
    init.rfWordOrder := WordOrder.Standard
    init.memWordOrder := WordOrder.Standard
    init.baseBitAddr := 0.U
    init.loadRegBitAddr := 0.U
    init.storeMemBitAddr := 0.U
    init
  })
  val s11J2J = S11J2J.compute(params, s11In.bits, s11J2JState, thisX, thisY)

  // Strided/indexed state and computation
  val s11SIState = RegInit({
    val init = Wire(new S11StridedIndexedState(params))
    init.iterating := false.B
    init.previousTag := 0.U
    init.phase := false.B
    init.offsetInPortion := 0.U
    init.offsetInElement := 0.U
    init.currentTag := 0.U
    init.portionEndInWord := 0.U
    init.rfElementBytes := 0.U
    init.memElementBytes := 0.U
    init.faulted := false.B
    init.faultElementIndex := 0.U
    init.lastInstrIdent := 0.U
    init
  })

  val s11SI = S11StridedIndexed.compute(params, s11In.bits, s11SIState)

  // WordSrc pass-through computation
  // For WordSrc, only ONE jamlet participates (determined by elementActive from S4)
  // If active, emit one output; if not active, finish immediately with no output
  val s11WordInstr = KInstr.asWord(params, s11In.bits.witemInfo.kinstr)
  val s11IsLoad = s11In.bits.witemType === WitemType.LoadWordSrc

  // For WordSrc: target is where data goes
  // LoadWordSrc: mem → reg, so target is regLoc
  // StoreWordSrc: reg → mem, so target is memLoc
  val s11WordTargetKIndex = Mux(s11IsLoad, s11WordInstr.regLoc.kIndex, s11WordInstr.memLoc.kIndex)
  val s11WordTargetJInK = Mux(s11IsLoad, s11WordInstr.regLoc.jInKIndex, s11WordInstr.memLoc.jInKIndex)

  // Convert (k_index, j_in_k_index) to (x, y) coordinates
  // k_x = k_index % k_cols, k_y = k_index / k_cols
  // j_in_k_x = j_in_k_index % j_cols, j_in_k_y = j_in_k_index / j_cols
  // x = k_x * j_cols + j_in_k_x, y = k_y * j_rows + j_in_k_y
  // Use masking/shifting since kCols and jCols are guaranteed power of 2
  val s11WordKX = s11WordTargetKIndex & (params.kCols - 1).U
  val s11WordKY = s11WordTargetKIndex >> params.log2KCols
  val s11WordJInKX = s11WordTargetJInK & (params.jCols - 1).U
  val s11WordJInKY = s11WordTargetJInK >> params.log2JCols
  val s11WordTargetX = (s11WordKX << params.log2JCols) + s11WordJInKX
  val s11WordTargetY = (s11WordKY << params.log2JRows) + s11WordJInKY

  // nBytes from byteMask popcount
  val s11WordNBytes = PopCount(s11WordInstr.byteMask)

  // Build WordSrc output
  val s11WordOutput = Wire(new S12S13Reg(params))
  s11WordOutput.entryIndex := s11In.bits.entryIndex
  s11WordOutput.instrIdent := s11In.bits.instrIdent
  s11WordOutput.witemType := s11In.bits.witemType
  s11WordOutput.witemInfo := s11In.bits.witemInfo
  s11WordOutput.rfV := s11In.bits.rfV
  s11WordOutput.srcTag := Mux(s11IsLoad, s11WordInstr.memOffsetInWord, s11WordInstr.regOffsetInWord)
  s11WordOutput.dstTag := Mux(s11IsLoad, s11WordInstr.regOffsetInWord, s11WordInstr.memOffsetInWord)
  s11WordOutput.nBytes := s11WordNBytes
  s11WordOutput.targetX := s11WordTargetX
  s11WordOutput.targetY := s11WordTargetY
  s11WordOutput.isVpu := true.B  // WordSrc is always internal VPU transfer
  s11WordOutput.paddr := 0.U     // Not used for VPU internal

  // WordSrc: valid if element is active, always finishes in one cycle
  val s11WordOutValid = s11In.bits.elementActive
  val s11WordFinished = true.B

  // Select output based on witem type
  val s11Output = Mux(s11IsJ2J, s11J2J.output,
                  Mux(s11IsWordSrc, s11WordOutput, s11SI.output))
  val s11OutValid = Mux(s11IsJ2J, s11J2J.outValid,
                    Mux(s11IsWordSrc, s11WordOutValid, s11SI.outValid))
  val s11Finished = Mux(s11IsJ2J, s11J2J.finished,
                    Mux(s11IsWordSrc, s11WordFinished, s11SI.finished))

  // Error for invalid element width in J2J
  err.invalidEw := s11IsJ2J && s11J2J.invalidEw

  // For strided/indexed: skipAndComplete means set tag srcState=Complete directly
  val s11IsStridedIndexed = !s11IsJ2J && !s11IsWordSrc
  val s11SkipAndComplete = s11IsStridedIndexed && s11SI.skipAndComplete

  // S11 output
  val s11Out = Wire(Decoupled(new S12S13Reg(params)))
  s11Out.bits := s11Output
  s11Out.valid := s11In.valid && s11OutValid

  // Can progress when downstream accepts or not emitting or skipping
  val s11CanProgress = s11Out.ready || !s11OutValid || s11SkipAndComplete

  // Update appropriate state when input valid and can progress
  when(s11In.valid && s11CanProgress) {
    when(s11IsJ2J) {
      s11J2JState := s11J2J.nextState
    }.otherwise {
      s11SIState := s11SI.nextState
    }
  }

  // When skipping due to fault, set tag srcState to Complete directly
  when(s11In.valid && s11SkipAndComplete && s11CanProgress) {
    entries(s11SI.output.entryIndex).tagStates(s11SI.output.srcTag).srcState :=
      WitemSendState.Complete
  }

  // Can consume input only when current computation is finished and can progress
  s11In.ready := s11Finished && s11CanProgress

  // Signal faultReady when S11 finishes for strided/indexed entry
  // This transitions entry from Active to WaitingForFaultSync
  val s11EntryConsumed = s11In.fire && s11Finished && s11IsStridedIndexed
  val s11EntryIndex = s11In.bits.entryIndex
  val s11EntryIsActive = entries(s11EntryIndex).state === WitemEntryState.Active

  when(s11EntryConsumed && s11EntryIsActive) {
    entries(s11EntryIndex).state := WitemEntryState.WaitingForFaultSync
  }

  // faultReady output: signal when entry transitions to WaitingForFaultSync
  val s11SignalFaultReady = s11EntryConsumed && s11EntryIsActive
  val s11FaultReadyIdent = s11In.bits.instrIdent
  val s11HasFault = s11SIState.faulted || s11In.bits.tlbFault  // Current or previous fault
  val s11FaultElement = Mux(s11In.bits.tlbFault && !s11SIState.faulted,
                            s11In.bits.elementIndex,
                            s11SIState.faultElementIndex)

  val s12In = DoubleBuffer(s11Out, wmp.s11s12ForwardBuffer, wmp.s11s12BackwardBuffer)

  // -------------------------------------------------------------------------
  // S12: Tag Iteration Buffer (pass-through)
  // -------------------------------------------------------------------------
  val s12Out = Wire(Decoupled(new S12S13Reg(params)))
  s12Out.valid := s12In.valid
  s12Out.bits := s12In.bits
  s12In.ready := s12Out.ready

  val s13In = DoubleBuffer(s12Out, wmp.s12s13ForwardBuffer, wmp.s12s13BackwardBuffer)

  // -------------------------------------------------------------------------
  // S13: Tag Iteration Emit (pass-through)
  // -------------------------------------------------------------------------
  val s13Out = Wire(Decoupled(new S13S14Reg(params)))
  s13Out.valid := s13In.valid
  s13Out.bits.entryIndex := s13In.bits.entryIndex
  s13Out.bits.instrIdent := s13In.bits.instrIdent
  s13Out.bits.witemType := s13In.bits.witemType
  s13Out.bits.witemInfo := s13In.bits.witemInfo
  s13Out.bits.rfV := s13In.bits.rfV
  s13Out.bits.srcTag := s13In.bits.srcTag
  s13Out.bits.dstTag := s13In.bits.dstTag
  s13Out.bits.nBytes := s13In.bits.nBytes
  s13Out.bits.targetX := s13In.bits.targetX
  s13Out.bits.targetY := s13In.bits.targetY
  s13Out.bits.isVpu := s13In.bits.isVpu
  s13Out.bits.paddr := s13In.bits.paddr
  s13In.ready := s13Out.ready

  val s14In = DoubleBuffer(s13Out, wmp.s13s14ForwardBuffer, wmp.s13s14BackwardBuffer)

  // -------------------------------------------------------------------------
  // S14: Data Read Issue + Build Header
  //
  // - Stores (StoreJ2JWords, StoreWordSrc, StoreStride, StoreIdxUnord): Issue dataRfReq
  // - Cache loads (LoadJ2JWords, LoadWordSrc): Issue sramReq
  // - Memory loads (LoadStride, LoadIdxUnord, LoadIdxElement): No data read
  // -------------------------------------------------------------------------
  val s14IsStore = (s14In.bits.witemType === WitemType.StoreJ2JWords) ||
                   (s14In.bits.witemType === WitemType.StoreWordSrc) ||
                   (s14In.bits.witemType === WitemType.StoreStride) ||
                   (s14In.bits.witemType === WitemType.StoreIdxUnord)

  val s14IsCacheLoad = (s14In.bits.witemType === WitemType.LoadJ2JWords) ||
                       (s14In.bits.witemType === WitemType.LoadWordSrc)

  val s14IsMemLoad = (s14In.bits.witemType === WitemType.LoadStride) ||
                     (s14In.bits.witemType === WitemType.LoadIdxUnord) ||
                     (s14In.bits.witemType === WitemType.LoadIdxElement)

  val s14NeedsDataRead = s14IsStore || s14IsCacheLoad

  // Decode kinstr to get register addresses
  val s14KinstrJ2J = KInstr.asJ2J(params, s14In.bits.witemInfo.kinstr)
  val s14KinstrWord = KInstr.asWord(params, s14In.bits.witemInfo.kinstr)
  val s14KinstrStrided = KInstr.asStrided(params, s14In.bits.witemInfo.kinstr)

  // RF address for stores: reg + rfV
  val s14IsJ2J = (s14In.bits.witemType === WitemType.LoadJ2JWords) ||
                 (s14In.bits.witemType === WitemType.StoreJ2JWords)
  val s14IsWordSrc = (s14In.bits.witemType === WitemType.LoadWordSrc) ||
                     (s14In.bits.witemType === WitemType.StoreWordSrc)

  val s14RfReg = Mux(s14IsJ2J, s14KinstrJ2J.reg,
                 Mux(s14IsWordSrc, s14KinstrWord.reg, s14KinstrStrided.reg))
  val s14RfAddr = s14RfReg + s14In.bits.rfV

  // SRAM address for cache loads: cacheSlot * cacheSlotWords + rfV
  val s14SramAddr = (s14KinstrJ2J.cacheSlot * params.cacheSlotWords.U) + s14In.bits.rfV

  // Output ready signals
  val s14Out = Wire(Decoupled(new S14S15Reg(params)))

  // Issue SRAM read for cache loads
  val s14SramReqNeeded = s14In.valid && s14IsCacheLoad
  sramReq.valid := s14SramReqNeeded && s14Out.ready
  sramReq.bits.addr := s14SramAddr
  sramReq.bits.isWrite := false.B
  sramReq.bits.writeData := DontCare

  // Issue RF read for stores
  val s14RfReqNeeded = s14In.valid && s14IsStore
  dataRfReq.valid := s14RfReqNeeded && s14Out.ready
  dataRfReq.bits.addr := s14RfAddr
  dataRfReq.bits.isWrite := false.B
  dataRfReq.bits.writeData := DontCare

  // S13 can proceed when:
  // - No data read needed (memory loads): always ready
  // - SRAM read needed: sramReq.ready
  // - RF read needed: dataRfReq.ready
  val s14DataPathReady = Mux(s14IsCacheLoad, sramReq.ready,
                          Mux(s14IsStore, dataRfReq.ready, true.B))

  s14Out.valid := s14In.valid && s14DataPathReady
  s14Out.bits.entryIndex := s14In.bits.entryIndex
  s14Out.bits.instrIdent := s14In.bits.instrIdent
  s14Out.bits.witemType := s14In.bits.witemType
  s14Out.bits.srcTag := s14In.bits.srcTag
  s14Out.bits.dstTag := s14In.bits.dstTag
  s14Out.bits.nBytes := s14In.bits.nBytes
  s14Out.bits.targetX := s14In.bits.targetX
  s14Out.bits.targetY := s14In.bits.targetY
  s14Out.bits.isVpu := s14In.bits.isVpu
  s14Out.bits.paddr := s14In.bits.paddr
  s14Out.bits.needsDataResp := s14NeedsDataRead
  s14Out.bits.isSramRead := s14IsCacheLoad

  s14In.ready := s14Out.ready && s14DataPathReady

  val s15In = DoubleBuffer(s14Out, wmp.s14s15ForwardBuffer, wmp.s14s15BackwardBuffer)

  // -------------------------------------------------------------------------
  // S15: Data Read Wait (pass-through)
  // -------------------------------------------------------------------------
  val s15Out = Wire(Decoupled(new S15S16Reg(params)))
  s15Out.valid := s15In.valid
  s15Out.bits.entryIndex := s15In.bits.entryIndex
  s15Out.bits.instrIdent := s15In.bits.instrIdent
  s15Out.bits.witemType := s15In.bits.witemType
  s15Out.bits.srcTag := s15In.bits.srcTag
  s15Out.bits.dstTag := s15In.bits.dstTag
  s15Out.bits.nBytes := s15In.bits.nBytes
  s15Out.bits.targetX := s15In.bits.targetX
  s15Out.bits.targetY := s15In.bits.targetY
  s15Out.bits.isVpu := s15In.bits.isVpu
  s15Out.bits.paddr := s15In.bits.paddr
  s15Out.bits.needsDataResp := s15In.bits.needsDataResp
  s15Out.bits.isSramRead := s15In.bits.isSramRead
  s15In.ready := s15Out.ready

  val s16In = DoubleBuffer(s15Out, wmp.s15s16ForwardBuffer, wmp.s15s16BackwardBuffer)

  // -------------------------------------------------------------------------
  // S16: Data Response + Send Packet
  //
  // Packet formats:
  // 1. Target knows address: [header] [data]
  //    - LoadJ2JWords, StoreJ2JWords, LoadWordSrc, StoreWordSrc
  // 2. Target needs address, no data: [header] [paddr]
  //    - LoadStride, LoadIdxUnord, LoadIdxElement
  // 3. Target needs address, with data: [header] [paddr] [data]
  //    - StoreStride, StoreIdxUnord
  //
  // From pipeline register:
  // - needsDataResp: packet includes data (formats 1 and 3)
  // - isSramRead: data comes from SRAM (vs RF)
  // -------------------------------------------------------------------------

  // Determine message type based on witem type
  val s16MessageType = MuxLookup(s16In.bits.witemType.asUInt, MessageType.Reserved2)(Seq(
    WitemType.LoadJ2JWords.asUInt -> MessageType.LoadJ2JWordsReq,
    WitemType.StoreJ2JWords.asUInt -> MessageType.StoreJ2JWordsReq,
    WitemType.LoadWordSrc.asUInt -> MessageType.LoadWordReq,
    WitemType.StoreWordSrc.asUInt -> MessageType.StoreWordReq,
    WitemType.LoadStride.asUInt -> MessageType.ReadMemWordReq,
    WitemType.StoreStride.asUInt -> MessageType.WriteMemWordReq,
    WitemType.LoadIdxUnord.asUInt -> MessageType.ReadMemWordReq,
    WitemType.StoreIdxUnord.asUInt -> MessageType.WriteMemWordReq,
    WitemType.LoadIdxElement.asUInt -> MessageType.ReadMemWordReq
  ))

  // Packet includes paddr (formats 2 and 3)
  val s16NeedsPaddr = (s16In.bits.witemType === WitemType.LoadStride) ||
                      (s16In.bits.witemType === WitemType.StoreStride) ||
                      (s16In.bits.witemType === WitemType.LoadIdxUnord) ||
                      (s16In.bits.witemType === WitemType.StoreIdxUnord) ||
                      (s16In.bits.witemType === WitemType.LoadIdxElement)

  // Data response muxing based on isSramRead
  val s16DataRespValid = Mux(s16In.bits.isSramRead, sramResp.valid, dataRfResp.valid)
  val s16DataRespData = Mux(s16In.bits.isSramRead, sramResp.bits.readData, dataRfResp.bits.readData)

  // S15 State Machine
  object S16State extends ChiselEnum {
    val SendHeader, SendPaddr, SendData = Value
  }

  val s16State = RegInit(S16State.SendHeader)

  // Determine which header type to use
  val s16IsWriteMemWord = (s16In.bits.witemType === WitemType.StoreStride) ||
                          (s16In.bits.witemType === WitemType.StoreIdxUnord)
  val s16IsReadMemWord = (s16In.bits.witemType === WitemType.LoadStride) ||
                         (s16In.bits.witemType === WitemType.LoadIdxUnord) ||
                         (s16In.bits.witemType === WitemType.LoadIdxElement)
  val s16IsMaskedTagged = s16In.bits.witemType === WitemType.StoreJ2JWords

  // Packet length = 1 (header) + optional paddr + optional data
  val s16PacketLength = 1.U +
                        Mux(s16NeedsPaddr, 1.U, 0.U) +
                        Mux(s16In.bits.needsDataResp, 1.U, 0.U)

  // Build WriteMemWordHeader (for StoreStride, StoreIdxUnord)
  val s16WriteMemWordHeader = Wire(new WriteMemWordHeader(params))
  s16WriteMemWordHeader.targetX := s16In.bits.targetX
  s16WriteMemWordHeader.targetY := s16In.bits.targetY
  s16WriteMemWordHeader.sourceX := thisX
  s16WriteMemWordHeader.sourceY := thisY
  s16WriteMemWordHeader.length := s16PacketLength
  s16WriteMemWordHeader.messageType := s16MessageType
  s16WriteMemWordHeader.sendType := SendType.Single
  s16WriteMemWordHeader.ident := s16In.bits.instrIdent
  s16WriteMemWordHeader.tag := s16In.bits.srcTag
  s16WriteMemWordHeader.dstByteInWord := s16In.bits.dstTag
  s16WriteMemWordHeader.nBytes := s16In.bits.nBytes

  // Build ReadMemWordHeader (for LoadStride, LoadIdxUnord, LoadIdxElement)
  val s16ReadMemWordHeader = Wire(new ReadMemWordHeader(params))
  s16ReadMemWordHeader.targetX := s16In.bits.targetX
  s16ReadMemWordHeader.targetY := s16In.bits.targetY
  s16ReadMemWordHeader.sourceX := thisX
  s16ReadMemWordHeader.sourceY := thisY
  s16ReadMemWordHeader.length := s16PacketLength
  s16ReadMemWordHeader.messageType := s16MessageType
  s16ReadMemWordHeader.sendType := SendType.Single
  s16ReadMemWordHeader.ident := s16In.bits.instrIdent
  s16ReadMemWordHeader.tag := s16In.bits.srcTag
  s16ReadMemWordHeader.fault := false.B

  // Build MaskedTaggedHeader (for StoreJ2JWords)
  val s16MaskedTaggedHeader = Wire(new MaskedTaggedHeader(params))
  s16MaskedTaggedHeader.targetX := s16In.bits.targetX
  s16MaskedTaggedHeader.targetY := s16In.bits.targetY
  s16MaskedTaggedHeader.sourceX := thisX
  s16MaskedTaggedHeader.sourceY := thisY
  s16MaskedTaggedHeader.length := s16PacketLength
  s16MaskedTaggedHeader.messageType := s16MessageType
  s16MaskedTaggedHeader.sendType := SendType.Single
  s16MaskedTaggedHeader.ident := s16In.bits.instrIdent
  s16MaskedTaggedHeader.tag := s16In.bits.srcTag
  s16MaskedTaggedHeader.mask := 0.U  // TODO: populate from instruction if needed

  // Build TaggedHeader (for LoadJ2JWords, LoadWordSrc, StoreWordSrc)
  val s16TaggedHeader = Wire(new TaggedHeader(params))
  s16TaggedHeader.targetX := s16In.bits.targetX
  s16TaggedHeader.targetY := s16In.bits.targetY
  s16TaggedHeader.sourceX := thisX
  s16TaggedHeader.sourceY := thisY
  s16TaggedHeader.length := s16PacketLength
  s16TaggedHeader.messageType := s16MessageType
  s16TaggedHeader.sendType := SendType.Single
  s16TaggedHeader.ident := s16In.bits.instrIdent
  s16TaggedHeader.tag := s16In.bits.srcTag

  // Select header based on message type
  val s16HeaderData = MuxCase(s16TaggedHeader.asUInt, Seq(
    s16IsWriteMemWord -> s16WriteMemWordHeader.asUInt,
    s16IsReadMemWord -> s16ReadMemWordHeader.asUInt,
    s16IsMaskedTagged -> s16MaskedTaggedHeader.asUInt
  ))

  // Default outputs
  s16In.ready := false.B
  sramResp.ready := false.B
  dataRfResp.ready := false.B
  packetOut.valid := false.B
  packetOut.bits.data := 0.U
  packetOut.bits.isHeader := false.B

  switch(s16State) {
    is(S16State.SendHeader) {
      when(s16In.valid) {
        packetOut.valid := true.B
        packetOut.bits.data := s16HeaderData
        packetOut.bits.isHeader := true.B
        when(packetOut.fire) {
          when(s16NeedsPaddr) {
            s16State := S16State.SendPaddr
          }.elsewhen(s16In.bits.needsDataResp) {
            s16State := S16State.SendData
          }.otherwise {
            s16In.ready := true.B
          }
        }
      }
    }

    is(S16State.SendPaddr) {
      packetOut.valid := true.B
      packetOut.bits.data := s16In.bits.paddr
      packetOut.bits.isHeader := false.B
      when(packetOut.fire) {
        when(s16In.bits.needsDataResp) {
          s16State := S16State.SendData
        }.otherwise {
          s16In.ready := true.B
          s16State := S16State.SendHeader
        }
      }
    }

    is(S16State.SendData) {
      when(s16DataRespValid) {
        packetOut.valid := true.B
        packetOut.bits.data := s16DataRespData
        packetOut.bits.isHeader := false.B
        when(packetOut.fire) {
          when(s16In.bits.isSramRead) {
            sramResp.ready := true.B
          }.otherwise {
            dataRfResp.ready := true.B
          }
          s16In.ready := true.B
          s16State := S16State.SendHeader
        }
      }
    }
  }

  // Update srcState to WaitingForResponse when packet is successfully sent
  // This happens when s16In fires (ready and valid both true)
  when(s16In.fire) {
    entries(s16In.bits.entryIndex).tagStates(s16In.bits.srcTag).srcState :=
      WitemSendState.WaitingForResponse
  }

  // -------------------------------------------------------------------------
  // Completion Detector
  // -------------------------------------------------------------------------
  // Sync types (strided/indexed) complete via completionSync path
  // Non-sync types (J2J, WordSrc) complete directly when all tags are done
  def isSyncType(wt: WitemType.Type): Bool = {
    (wt === WitemType.LoadStride) || (wt === WitemType.StoreStride) ||
    (wt === WitemType.LoadIdxUnord) || (wt === WitemType.StoreIdxUnord) ||
    (wt === WitemType.LoadIdxElement)
  }

  // Non-sync entries: complete when all tags Complete and state is Active
  val nonSyncEntryComplete = VecInit(entries.map { e =>
    val allTagsComplete = VecInit(e.tagStates.map { ts =>
      ts.srcState === WitemSendState.Complete && ts.dstState === WitemRecvState.Complete
    }).reduceTree(_ && _)
    e.valid && e.state === WitemEntryState.Active && !isSyncType(e.witemType) && allTagsComplete
  })

  val anyNonSyncComplete = nonSyncEntryComplete.reduceTree(_ || _)
  val nonSyncCompleteIndex = PriorityEncoder(nonSyncEntryComplete)

  when(anyNonSyncComplete) {
    entries(nonSyncCompleteIndex).state := WitemEntryState.Complete
  }

  // Sync entries: complete when completionSync received
  val completionSyncMatch = entries.map(e =>
    e.valid && e.instrIdent === witemCompletionSync.bits.instrIdent &&
    e.state === WitemEntryState.WaitingForCompletionSync)
  val completionSyncIndex = OHToUInt(completionSyncMatch)
  val completionSyncValid = witemCompletionSync.valid && completionSyncMatch.reduce(_ || _)

  when(completionSyncValid) {
    entries(completionSyncIndex).state := WitemEntryState.Complete
  }

  // witemComplete: non-sync completing directly OR sync completing via completionSync
  val witemCompleteOut = Wire(Valid(params.ident()))
  witemCompleteOut.valid := anyNonSyncComplete || completionSyncValid
  witemCompleteOut.bits := Mux(anyNonSyncComplete,
                               entries(nonSyncCompleteIndex).instrIdent,
                               entries(completionSyncIndex).instrIdent)

  if (wmp.witemCompleteOutputReg) {
    io.witemComplete := RegNext(witemCompleteOut)
  } else {
    io.witemComplete := witemCompleteOut
  }

  // -------------------------------------------------------------------------
  // Optional input registers for RX state updates
  // -------------------------------------------------------------------------
  val witemSrcUpdateIn = if (wmp.witemSrcUpdateInputReg) {
    RegNext(io.witemSrcUpdate)
  } else {
    io.witemSrcUpdate
  }

  val witemDstUpdateIn = if (wmp.witemDstUpdateInputReg) {
    RegNext(io.witemDstUpdate)
  } else {
    io.witemDstUpdate
  }

  // -------------------------------------------------------------------------
  // State Updates from RX handlers
  // -------------------------------------------------------------------------
  val srcUpdateMatch = entries.map(e => e.valid && e.instrIdent === witemSrcUpdateIn.bits.instrIdent)
  val srcUpdateIndex = OHToUInt(srcUpdateMatch)

  when(witemSrcUpdateIn.valid) {
    entries(srcUpdateIndex).tagStates(witemSrcUpdateIn.bits.tag).srcState :=
      witemSrcUpdateIn.bits.newState
  }

  val dstUpdateMatch = entries.map(e => e.valid && e.instrIdent === witemDstUpdateIn.bits.instrIdent)
  val dstUpdateIndex = OHToUInt(dstUpdateMatch)

  when(witemDstUpdateIn.valid) {
    entries(dstUpdateIndex).tagStates(witemDstUpdateIn.bits.tag).dstState :=
      witemDstUpdateIn.bits.newState
  }

  // faultReady: signal when strided/indexed entry finishes first pass
  witemFaultReady.valid := s11SignalFaultReady
  witemFaultReady.bits.instrIdent := s11FaultReadyIdent
  witemFaultReady.bits.hasFault := s11HasFault
  witemFaultReady.bits.minFaultElement := s11FaultElement

  // -------------------------------------------------------------------------
  // faultSync handling: transition entry from WaitingForFaultSync to WaitingForCompletionSync
  // -------------------------------------------------------------------------
  val faultSyncMatch = entries.map(e =>
    e.valid && e.instrIdent === witemFaultSync.bits.instrIdent &&
    e.state === WitemEntryState.WaitingForFaultSync)
  val faultSyncIndex = OHToUInt(faultSyncMatch)

  when(witemFaultSync.valid) {
    entries(faultSyncIndex).state := WitemEntryState.WaitingForCompletionSync
  }

  // -------------------------------------------------------------------------
  // completeReady: signal when all tags are Complete for sync entry in WaitingForCompletionSync
  // -------------------------------------------------------------------------
  val syncEntryCompleteReady = VecInit(entries.map { e =>
    val allTagsComplete = VecInit(e.tagStates.map { ts =>
      ts.srcState === WitemSendState.Complete && ts.dstState === WitemRecvState.Complete
    }).reduceTree(_ && _)
    e.valid && e.state === WitemEntryState.WaitingForCompletionSync && allTagsComplete
  })

  val anySyncCompleteReady = syncEntryCompleteReady.reduceTree(_ || _)
  val syncCompleteReadyIndex = PriorityEncoder(syncEntryCompleteReady)

  witemCompleteReady.valid := anySyncCompleteReady
  witemCompleteReady.bits := entries(syncCompleteReadyIndex).instrIdent
}

object WitemMonitorGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> WitemMonitor <jamletParamsFileName>")
      null
    } else {
      val params = JamletParams.fromFile(args(0))
      new WitemMonitor(params)
    }
  }
}
