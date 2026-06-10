package zamlet.memlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.network.NetworkWord

class MemletErrors(params: ZamletParams) extends Bundle {
  val controlErrors = new ControlSideErrors(params)
  val gatherErrors = Vec(params.nMemletRouters, new GatherSideErrors(params))
  val responseErrors = Vec(params.nMemletRouters, new ResponseSideErrors(params))
}

class MemletIO(params: ZamletParams) extends Bundle {
  val nRouters = params.nMemletRouters

  // Configuration
  val routerCoords = Input(Vec(nRouters, new Bundle {
    val x = UInt(params.xPosWidth.W)
    val y = UInt(params.yPosWidth.W)
  }))
  val jamletCoords = Input(Vec(nRouters, Vec(params.memletLocalJamlets, new Bundle {
    val x = UInt(params.xPosWidth.W)
    val y = UInt(params.yPosWidth.W)
  })))

  val errors = new MemletErrors(params)

  // Single Kamlet-network control connection
  val controlBHo = Flipped(Decoupled(new NetworkWord(params)))
  val controlAHi = Decoupled(new NetworkWord(params))

  // AXI4 master port (single, from MemoryEngine)
  val axi = new AXI4MasterIO(
    addrBits = params.memAddrWidth,
    dataBits = params.memBeatWords * params.wordWidth,
    idBits = params.memAxiIdBits
  )

  // Per-router mesh ports
  val aNi = Vec(nRouters, Vec(params.nAChannels,
    Flipped(Decoupled(new NetworkWord(params)))))
  val aNo = Vec(nRouters, Vec(params.nAChannels,
    Decoupled(new NetworkWord(params))))
  val aSi = Vec(nRouters, Vec(params.nAChannels,
    Flipped(Decoupled(new NetworkWord(params)))))
  val aSo = Vec(nRouters, Vec(params.nAChannels,
    Decoupled(new NetworkWord(params))))
  val aEi = Vec(nRouters, Vec(params.nAChannels,
    Flipped(Decoupled(new NetworkWord(params)))))
  val aEo = Vec(nRouters, Vec(params.nAChannels,
    Decoupled(new NetworkWord(params))))
  val aWi = Vec(nRouters, Vec(params.nAChannels,
    Flipped(Decoupled(new NetworkWord(params)))))
  val aWo = Vec(nRouters, Vec(params.nAChannels,
    Decoupled(new NetworkWord(params))))
  val bNi = Vec(nRouters, Vec(params.nBChannels,
    Flipped(Decoupled(new NetworkWord(params)))))
  val bNo = Vec(nRouters, Vec(params.nBChannels,
    Decoupled(new NetworkWord(params))))
  val bSi = Vec(nRouters, Vec(params.nBChannels,
    Flipped(Decoupled(new NetworkWord(params)))))
  val bSo = Vec(nRouters, Vec(params.nBChannels,
    Decoupled(new NetworkWord(params))))
  val bEi = Vec(nRouters, Vec(params.nBChannels,
    Flipped(Decoupled(new NetworkWord(params)))))
  val bEo = Vec(nRouters, Vec(params.nBChannels,
    Decoupled(new NetworkWord(params))))
  val bWi = Vec(nRouters, Vec(params.nBChannels,
    Flipped(Decoupled(new NetworkWord(params)))))
  val bWo = Vec(nRouters, Vec(params.nBChannels,
    Decoupled(new NetworkWord(params))))
}

class Memlet(params: ZamletParams) extends Module {
  val io = IO(new MemletIO(params))

  val nRouters = params.nMemletRouters
  val nGSlots = params.nMemletGatheringSlots
  val nRSlots = params.nResponseBufferSlots

  // ============================================================
  // Instantiate control side, slices, and MemoryEngine
  // ============================================================

  val controlSide = Module(new ControlSide(params))
  val slices = Seq.tabulate(nRouters)(i => Module(new MemletSlice(params)))
  val engine = Module(new MemoryEngine(params))

  io.axi <> engine.io.axi
  controlSide.io.controlBHo <> io.controlBHo
  io.controlAHi <> controlSide.io.controlAHi

  // ============================================================
  // Slice configuration and mesh ports
  // ============================================================

  for (r <- 0 until nRouters) {
    val s = slices(r)
    s.io.isInnerSlice := (r == 0).B
    s.io.isOuterSlice := (r == nRouters - 1).B
    s.io.sliceIdx := r.U
    s.io.routerX := io.routerCoords(r).x
    s.io.routerY := io.routerCoords(r).y
    s.io.jamletCoords := io.jamletCoords(r)

    s.io.aNi <> io.aNi(r)
    s.io.aNo <> io.aNo(r)
    s.io.aSi <> io.aSi(r)
    s.io.aSo <> io.aSo(r)
    s.io.aEi <> io.aEi(r)
    s.io.aEo <> io.aEo(r)
    s.io.aWi <> io.aWi(r)
    s.io.aWo <> io.aWo(r)
    s.io.bNi <> io.bNi(r)
    s.io.bNo <> io.bNo(r)
    s.io.bSi <> io.bSi(r)
    s.io.bSo <> io.bSo(r)
    s.io.bEi <> io.bEi(r)
    s.io.bEo <> io.bEo(r)
    s.io.bWi <> io.bWi(r)
    s.io.bWo <> io.bWo(r)
  }

  // ============================================================
  // Inter-slice propagation chains
  // ============================================================

  // Cache slot allocation: ControlSide outward through all slices
  slices(0).io.cacheSlotAllocIn := controlSide.io.cacheSlotAllocOut
  for (r <- 1 until nRouters) {
    slices(r).io.cacheSlotAllocIn := slices(r - 1).io.cacheSlotAllocOut
  }

  // Arrived: inward toward slice 0
  slices(nRouters - 1).io.arrivedIn.valid := false.B
  slices(nRouters - 1).io.arrivedIn.bits := DontCare
  for (r <- (0 until nRouters - 1).reverse) {
    slices(r).io.arrivedIn := slices(r + 1).io.arrivedOut
  }

  // Sent (routerDone): inward toward slice 0
  slices(nRouters - 1).io.sentIn.valid := false.B
  slices(nRouters - 1).io.sentIn.bits := DontCare
  for (r <- (0 until nRouters - 1).reverse) {
    slices(r).io.sentIn := slices(r + 1).io.sentOut
  }

  // ============================================================
  // ControlSide ↔ MemoryEngine
  // ============================================================

  engine.io.routerX := io.routerCoords(0).x
  engine.io.routerY := io.routerCoords(0).y
  engine.io.completeDeq <> controlSide.io.completeEnq
  controlSide.io.gatherComplete := slices(0).io.gatherComplete
  controlSide.io.gatheringFree := engine.io.gatheringFree
  controlSide.io.writeLineRespEnq <> engine.io.writeLineRespEnq

  // ============================================================
  // Slice 0 ↔ MemoryEngine
  // ============================================================

  slices(0).io.gatheringFree := engine.io.gatheringFree
  engine.io.responseFree := slices(0).io.responseFree
  for (r <- 1 until nRouters) {
    slices(r).io.gatheringFree := engine.io.gatheringFree
  }

  // ============================================================
  // Response data write: MemoryEngine → slices (demux by routerSel)
  // ============================================================

  for (r <- 0 until nRouters) {
    slices(r).io.responseDataWrite.valid :=
      engine.io.responseDataRouterSel(r)
    slices(r).io.responseDataWrite.bits := engine.io.responseDataWrite
  }

  // ============================================================
  // Response metadata: MemoryEngine → all slices (broadcast)
  // ============================================================

  for (r <- 0 until nRouters) {
    slices(r).io.responseMetaEvent := engine.io.responseMetaEvent
  }

  // ============================================================
  // Gathering data read interconnect
  //
  // MemoryEngine issues requests with routerIdx. Demux to the
  // addressed slice, enqueue routerIdx into an ordering FIFO.
  // Response side dequeues the FIFO to select which slice's
  // response to forward back to MemoryEngine.
  // ============================================================

  // This is a fifo where we put the indices of the routers we've gathered
  // from.
  val gatherOrderFifo = Module(new Queue(
    UInt(log2Ceil(nRouters).W), entries = 4))

  // Request side: demux to slices
  val reqRouterIdx = engine.io.gatheringDataReq.bits.routerIdx
  for (r <- 0 until nRouters) {
    slices(r).io.gatheringDataReq.valid :=
      engine.io.gatheringDataReq.valid &&
      reqRouterIdx === r.U && gatherOrderFifo.io.enq.ready
    slices(r).io.gatheringDataReq.bits.slotIdx :=
      engine.io.gatheringDataReq.bits.slotIdx
    slices(r).io.gatheringDataReq.bits.wordIdx :=
      engine.io.gatheringDataReq.bits.wordIdx
  }

  val sliceReadyVec = VecInit(slices.map(_.io.gatheringDataReq.ready))
  val targetSliceReady = Wire(Bool())
  targetSliceReady := sliceReadyVec(reqRouterIdx)
  dontTouch(targetSliceReady)

  engine.io.gatheringDataReq.ready := targetSliceReady && gatherOrderFifo.io.enq.ready
  gatherOrderFifo.io.enq.valid := engine.io.gatheringDataReq.valid && targetSliceReady

  gatherOrderFifo.io.enq.bits := reqRouterIdx

  // Response side: mux from slices in request order
  val respRouterIdx = gatherOrderFifo.io.deq.bits
  engine.io.gatheringDataResp.valid :=
    gatherOrderFifo.io.deq.valid &&
    Mux1H((0 until nRouters).map(r =>
      (respRouterIdx === r.U) -> slices(r).io.gatheringDataResp.valid))
  engine.io.gatheringDataResp.bits :=
    Mux1H((0 until nRouters).map(r =>
      (respRouterIdx === r.U) -> slices(r).io.gatheringDataResp.bits))

  gatherOrderFifo.io.deq.ready := engine.io.gatheringDataResp.fire

  for (r <- 0 until nRouters) {
    slices(r).io.gatheringDataResp.ready :=
      gatherOrderFifo.io.deq.valid &&
      respRouterIdx === r.U &&
      engine.io.gatheringDataResp.ready
  }

  // ============================================================
  // Non-slice-0 defaults for ports only used by slice 0
  // ============================================================

  // ============================================================
  // Errors
  // ============================================================

  io.errors.controlErrors := controlSide.io.errors
  for (r <- 0 until nRouters) {
    io.errors.gatherErrors(r) := slices(r).io.gatherErrors
    io.errors.responseErrors(r) := slices(r).io.responseErrors
  }
}

object MemletGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <configFile>")
      System.exit(1)
    }
    val params = ZamletParams.fromFile(args(0))
    new Memlet(params)
  }
}

object MemletMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  MemletGenerator.generate(args(0), Seq(args(1)))
}
