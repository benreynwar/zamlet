package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.{CacheLineRequest, CacheLineResponse, JteHandlerBC, SendCacheLineCmd}
import zamlet.network.NetworkWord

object KceCacheSlotState extends ChiselEnum {
  val Empty, EmptyInQueue, Fetching, FetchingWillWrite, PresentClean, PresentDirty, Evicting = Value
}

class KceClaimSlotReq(params: ZamletParams) extends Bundle {
  val cacheLineAddr = params.cacheLineAddr()
  val willWrite = Bool()
  val claimIfFetching = Bool()
}

class KceClaimSlotResp(params: ZamletParams) extends Bundle {
  val hasSlot = Bool()
  val slot = params.cacheSlot()
  val state = KceCacheSlotState()
}

class KceAllocSlotReq(params: ZamletParams) extends Bundle {
  val cacheLineAddr = params.cacheLineAddr()
  val willWrite = Bool()
}

class KceAllocSlotResp(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
}

class KceSlotRelease(params: ZamletParams) extends Bundle {
  val slot = params.cacheSlot()
}

class KceJteReplay(params: ZamletParams) extends Bundle {
  val payload = new JteHandlerBC(params)
  val slot = params.cacheSlot()
}

class KceCacheEngineErrors extends Bundle {
  val cacheTable = new KceCacheTableErrors
  val memletInterface = new KceMemletInterfaceErrors
  val pendingTable = new KcePendingTableErrors
}

class KamletCacheEngineIO(params: ZamletParams) extends Bundle {
  val knetX = Input(params.xPos())
  val knetY = Input(params.yPos())
  val memletKnetX = Input(params.xPos())
  val memletKnetY = Input(params.yPos())

  // JTE cache-line request path. These requests are mediated by KcePendingTable.
  val jteCacheLineReq = Vec(params.jInK, Flipped(Decoupled(new CacheLineRequest(params))))
  val jteCacheLineResp = Vec(params.jInK, Decoupled(new CacheLineResponse(params)))
  val jteReplay = Vec(params.jInK, Decoupled(new KceJteReplay(params)))
  val jteCacheLineRelease = Vec(params.jInK, Flipped(Valid(new KceSlotRelease(params))))

  // JCE cache-line path. Fetch fills report done; dirty writebacks are triggered here.
  val jceFetchDone = Vec(params.jInK, Flipped(Valid(params.cacheSlot())))
  val jceWritebackReq = Vec(params.jInK, Valid(new SendCacheLineCmd(params)))

  // KamletTransferEngine cache-line path.
  val kteClaimSlotReq = Flipped(Decoupled(new KceClaimSlotReq(params)))
  val kteClaimSlotResp = Decoupled(new KceClaimSlotResp(params))
  val kteReleaseSlot = Flipped(Valid(new KceSlotRelease(params)))
  val kteAllocSlotReq = Flipped(Decoupled(new KceAllocSlotReq(params)))
  val kteAllocSlotResp = Decoupled(new KceAllocSlotResp(params))
  val kteSlotIsAvailable = Valid(params.cacheSlot())

  // ReservationStation deterministic-latency cache-line path.
  val rsClaimSlotReq = Flipped(Valid(new KceClaimSlotReq(params)))
  val rsClaimSlotResp = Valid(new KceClaimSlotResp(params))

  // Kamlet-network Memlet control path.
  val packetIn = Flipped(Decoupled(new NetworkWord(params)))
  val packetOut = Decoupled(new NetworkWord(params))

  val errors = Output(new KceCacheEngineErrors)
}

class KamletCacheEngine(params: ZamletParams) extends Module {
  val io = IO(new KamletCacheEngineIO(params))

  // ============================================================
  // Submodules
  // ============================================================

  val cacheTable = Module(new KceCacheTable(params))
  val scanner = Module(new KceScanner(params))
  val memletInterface = Module(new KceMemletInterface(params))
  val pendingTable = Module(new KcePendingTable(params))

  // ============================================================
  // Position / network configuration
  // ============================================================

  memletInterface.io.knetX := io.knetX
  memletInterface.io.knetY := io.knetY
  memletInterface.io.memletKnetX := io.memletKnetX
  memletInterface.io.memletKnetY := io.memletKnetY

  // ============================================================
  // JTE cache-line path
  // ============================================================

  for (jInK <- 0 until params.jInK) {
    pendingTable.io.cacheLineReq(jInK) <> io.jteCacheLineReq(jInK)
    io.jteCacheLineResp(jInK) <> pendingTable.io.cacheLineResp(jInK)
    io.jteReplay(jInK) <> pendingTable.io.replay(jInK)

    pendingTable.io.cacheLineRelease(jInK) := io.jteCacheLineRelease(jInK)
    memletInterface.io.jceFetchDone(jInK) := io.jceFetchDone(jInK)
    io.jceWritebackReq(jInK) := memletInterface.io.jceWritebackReq(jInK)
  }

  // ============================================================
  // PendingTable <-> CacheTable
  // ============================================================

  cacheTable.io.pendingClaimSlotReq <> pendingTable.io.claimSlotReq
  pendingTable.io.claimSlotResp <> cacheTable.io.pendingClaimSlotResp

  cacheTable.io.pendingAllocSlotReq <> pendingTable.io.allocSlotReq
  pendingTable.io.allocSlotResp <> cacheTable.io.pendingAllocSlotResp
  cacheTable.io.pendingReleaseSlot := pendingTable.io.releaseSlot

  pendingTable.io.slotIsAvailable := cacheTable.io.slotIsAvailable

  // ============================================================
  // KTE <-> CacheTable
  // ============================================================

  cacheTable.io.kteClaimSlotReq <> io.kteClaimSlotReq
  io.kteClaimSlotResp <> cacheTable.io.kteClaimSlotResp
  cacheTable.io.kteReleaseSlot := io.kteReleaseSlot

  cacheTable.io.kteAllocSlotReq <> io.kteAllocSlotReq
  io.kteAllocSlotResp <> cacheTable.io.kteAllocSlotResp

  io.kteSlotIsAvailable := cacheTable.io.slotIsAvailable

  // ============================================================
  // RS <-> CacheTable
  // ============================================================

  cacheTable.io.rsClaimSlotReq := io.rsClaimSlotReq
  io.rsClaimSlotResp := cacheTable.io.rsClaimSlotResp

  // ============================================================
  // CacheTable <-> Scanner / MemletInterface
  // ============================================================

  cacheTable.io.emptySlot <> scanner.io.emptySlot
  cacheTable.io.memletFetchReq <> memletInterface.io.fetchSlotReq
  memletInterface.io.fetchSlotComplete <> cacheTable.io.memletFetchComplete

  // ============================================================
  // Scanner <-> CacheTable / MemletInterface
  // ============================================================

  cacheTable.io.scannerSlotReq <> scanner.io.slotReq
  scanner.io.slotResp <> cacheTable.io.scannerSlotResp
  scanner.io.slotUpdate <> cacheTable.io.scannerSlotUpdate
  memletInterface.io.writebackSlotReq <> scanner.io.writebackSlot
  scanner.io.writebackSlotComplete := memletInterface.io.writebackSlotComplete
  cacheTable.io.scannerWritebackComplete := scanner.io.scannerWritebackComplete

  // ============================================================
  // Memlet control network
  // ============================================================

  memletInterface.io.packetIn <> io.packetIn
  io.packetOut <> memletInterface.io.packetOut

  // ============================================================
  // Errors
  // ============================================================

  io.errors.cacheTable := cacheTable.io.errors
  io.errors.memletInterface := memletInterface.io.errors
  io.errors.pendingTable := pendingTable.io.errors
}

object KamletCacheEngineGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <configFile>")
      System.exit(1)
    }
    val params = ZamletParams.fromFile(args(0))
    new KamletCacheEngine(params)
  }
}

object KamletCacheEngineMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  KamletCacheEngineGenerator.generate(outputDir, Seq(configFile))
}
