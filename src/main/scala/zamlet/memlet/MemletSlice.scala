package zamlet.memlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.network.{CombinedNetworkNode, NetworkWord}

class MemletSliceIO(params: ZamletParams) extends Bundle {

  // Configuration
  val isInnerSlice = Input(Bool())
  val isOuterSlice = Input(Bool())
  val sliceIdx = Input(UInt(log2Ceil(params.nMemletRouters).W))
  val kBaseX = Input(UInt(params.xPosWidth.W))
  val kBaseY = Input(UInt(params.yPosWidth.W))
  val routerX = Input(UInt(params.xPosWidth.W))
  val routerY = Input(UInt(params.yPosWidth.W))

  // Mesh ports — A channels
  val aNi = Vec(params.nAChannels, Flipped(Decoupled(new NetworkWord(params))))
  val aNo = Vec(params.nAChannels, Decoupled(new NetworkWord(params)))
  val aSi = Vec(params.nAChannels, Flipped(Decoupled(new NetworkWord(params))))
  val aSo = Vec(params.nAChannels, Decoupled(new NetworkWord(params)))
  val aEi = Vec(params.nAChannels, Flipped(Decoupled(new NetworkWord(params))))
  val aEo = Vec(params.nAChannels, Decoupled(new NetworkWord(params)))
  val aWi = Vec(params.nAChannels, Flipped(Decoupled(new NetworkWord(params))))
  val aWo = Vec(params.nAChannels, Decoupled(new NetworkWord(params)))

  // Mesh ports — B channels
  val bNi = Vec(params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))
  val bNo = Vec(params.nBChannels, Decoupled(new NetworkWord(params)))
  val bSi = Vec(params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))
  val bSo = Vec(params.nBChannels, Decoupled(new NetworkWord(params)))
  val bEi = Vec(params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))
  val bEo = Vec(params.nBChannels, Decoupled(new NetworkWord(params)))
  val bWi = Vec(params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))
  val bWo = Vec(params.nBChannels, Decoupled(new NetworkWord(params)))

  // Gather side: propagation chains
  val identAllocIn = Flipped(Valid(new IdentAllocEvent(params)))
  val identAllocOut = Valid(new IdentAllocEvent(params))
  val arrivedIn = Flipped(Valid(UInt(log2Ceil(params.nMemletGatheringSlots).W)))
  val arrivedOut = Valid(UInt(log2Ceil(params.nMemletGatheringSlots).W))

  // Gather side: MemoryEngine interface
  val completeEnq = Decoupled(new GatheringSlotMeta(params))
  val gatheringDataReq = Flipped(Decoupled(new GatheringDataReadSliceReq(params)))
  val gatheringDataResp = Decoupled(UInt(params.wordWidth.W))
  val gatheringFree = Flipped(Valid(UInt(log2Ceil(params.nMemletGatheringSlots).W)))

  // Response side: MemoryEngine interface
  val responseDataWrite = Flipped(Valid(new ResponseDataWrite(params)))
  val responseMetaEvent = Flipped(Valid(new ResponseMetaEvent(params)))
  val writeLineRespEnq = Flipped(Decoupled(new NetworkWord(params)))
  val responseFree = Valid(UInt(log2Ceil(params.nResponseBufferSlots).W))

  // Response side: propagation chains
  val sentIn = Flipped(Valid(UInt(log2Ceil(params.nResponseBufferSlots).W)))
  val sentOut = Valid(UInt(log2Ceil(params.nResponseBufferSlots).W))

  // Errors
  val gatherErrors = new GatherSideErrors(params)
  val responseErrors = new ResponseSideErrors(params)
}

class MemletSlice(params: ZamletParams) extends Module {
  val io = IO(new MemletSliceIO(params))

  // ============================================================
  // Router
  // ============================================================

  val router = Module(new CombinedNetworkNode(params))
  router.io.thisX := io.routerX
  router.io.thisY := io.routerY

  router.io.aNi <> io.aNi
  router.io.aNo <> io.aNo
  router.io.aSi <> io.aSi
  router.io.aSo <> io.aSo
  router.io.aEi <> io.aEi
  router.io.aEo <> io.aEo
  router.io.aWi <> io.aWi
  router.io.aWo <> io.aWo
  router.io.bNi <> io.bNi
  router.io.bNo <> io.bNo
  router.io.bSi <> io.bSi
  router.io.bSo <> io.bSo
  router.io.bEi <> io.bEi
  router.io.bEo <> io.bEo
  router.io.bWi <> io.bWi
  router.io.bWo <> io.bWo

  router.io.aHo.ready := false.B
  router.io.bHi.valid := false.B
  router.io.bHi.bits := DontCare

  // ============================================================
  // GatherSide
  // ============================================================

  val gatherSide = Module(new GatherSide(params))

  gatherSide.io.isInnerSlice := io.isInnerSlice
  gatherSide.io.isOuterSlice := io.isOuterSlice
  gatherSide.io.kBaseX := io.kBaseX
  gatherSide.io.kBaseY := io.kBaseY
  gatherSide.io.bHo <> router.io.bHo
  gatherSide.io.identAllocIn := io.identAllocIn
  io.identAllocOut := gatherSide.io.identAllocOut
  gatherSide.io.arrivedIn := io.arrivedIn
  io.arrivedOut := gatherSide.io.arrivedOut
  io.completeEnq <> gatherSide.io.completeEnq
  gatherSide.io.gatheringDataReq <> io.gatheringDataReq
  io.gatheringDataResp <> gatherSide.io.gatheringDataResp
  gatherSide.io.gatheringFree := io.gatheringFree
  io.gatherErrors := gatherSide.io.errors

  // ============================================================
  // ResponseSide
  // ============================================================

  val responseSide = Module(new ResponseSide(params))

  responseSide.io.isInnerSlice := io.isInnerSlice
  responseSide.io.isOuterSlice := io.isOuterSlice
  responseSide.io.sliceIdx := io.sliceIdx
  responseSide.io.kBaseX := io.kBaseX
  responseSide.io.kBaseY := io.kBaseY
  responseSide.io.routerX := io.routerX
  responseSide.io.routerY := io.routerY
  router.io.aHi <> responseSide.io.aHi
  responseSide.io.dropEnq <> gatherSide.io.dropEnq
  responseSide.io.writeLineRespEnq <> io.writeLineRespEnq
  responseSide.io.responseDataWrite := io.responseDataWrite
  responseSide.io.responseMetaEvent := io.responseMetaEvent
  io.responseFree := responseSide.io.responseFree
  responseSide.io.sentIn := io.sentIn
  io.sentOut := responseSide.io.sentOut
  io.responseErrors := responseSide.io.errors
}
