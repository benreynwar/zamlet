package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.memlet.{AXI4MasterIO, Memlet}
import zamlet.network.{CombinedNetworkNode, NetworkWord}
import zamlet.utils.{ResetPipeline, ResetPipelineBudget}

class KamletMeshWithMemlets(params: ZamletParams) extends Module {
  require(params.kCols % 2 == 0, "KamletMeshWithMemlets requires even kCols")
  require(params.nMemletRouters == KamletMeshCoords.coordsPerMemlet(params),
    "nMemletRouters must match the KamletMeshCoords memlet layout")

  private val totalChannels = params.nAChannels + params.nBChannels

  val io = IO(new Bundle {
    val knetOffsetX = Input(params.xPos())
    val knetOffsetY = Input(params.yPos())
    val lamletKnetX = Input(params.xPos())
    val lamletKnetY = Input(params.yPos())

    val nChannelsIn = Vec(params.kCols, Vec(params.jCols,
      Vec(totalChannels, Flipped(Decoupled(new NetworkWord(params))))))
    val nChannelsOut = Vec(params.kCols, Vec(params.jCols,
      Vec(totalChannels, Decoupled(new NetworkWord(params)))))

    val nKamletAIn = Vec(params.kCols, Vec(params.nAChannels,
      Flipped(Decoupled(new NetworkWord(params)))))
    val nKamletAOut = Vec(params.kCols, Vec(params.nAChannels,
      Decoupled(new NetworkWord(params))))
    val nKamletBIn = Vec(params.kCols, Vec(params.nBChannels,
      Flipped(Decoupled(new NetworkWord(params)))))
    val nKamletBOut = Vec(params.kCols, Vec(params.nBChannels,
      Decoupled(new NetworkWord(params))))

    val nSyncN = Vec(params.kCols, new SyncIO)
    val nSyncNE = Vec(params.kCols, new SyncIO)
    val nSyncNW = Vec(params.kCols, new SyncIO)

    val axi = Vec(params.kInL, new AXI4MasterIO(
      addrBits = params.memAddrWidth,
      dataBits = params.memBeatWords * params.wordWidth,
      idBits = params.memAxiIdBits
    ))
  })

  private val rootResetBudget = ResetPipelineBudget(params.resetPipelineDepth)
  private val resetPipeline =
    ResetPipeline(clock, reset.asBool, 1, rootResetBudget, "KamletMeshWithMemlets")
  private val childResetBudget = resetPipeline.childBudget

  withReset(resetPipeline.localReset) {
  val mesh: KamletMesh = withReset(resetPipeline.childReset) {
    Module(new KamletMesh(
      params,
      MeshEdgeNeighbors.isolated(params.kCols, params.kRows),
      childResetBudget))
  }
  mesh.io.knetOffsetX := io.knetOffsetX
  mesh.io.knetOffsetY := io.knetOffsetY
  mesh.io.lamletKnetX := io.lamletKnetX
  mesh.io.lamletKnetY := io.lamletKnetY

  val memlets = Seq.tabulate(params.kCols, params.kRows) { (kX, kY) =>
    val m: Memlet = withReset(resetPipeline.childReset) {
      Module(new Memlet(params, childResetBudget))
    }
    val idx = kY * params.kCols + kX
    for (router <- 0 until params.nMemletRouters) {
      m.io.routerCoords(router).x := KamletMeshCoords.memletJnetRouterX(params, kX, router)
      m.io.routerCoords(router).y := KamletMeshCoords.memletJnetRouterY(params, kX, kY, router)
      for (localJ <- 0 until params.memletLocalJamlets) {
        val jInK = router * params.memletLocalJamlets + localJ
        m.io.jamletCoords(router)(localJ).x :=
          KamletMeshCoords.kamletJnetBaseX(params, kX) +
            (jInK % params.jCols).U(params.xPosWidth.W)
        m.io.jamletCoords(router)(localJ).y :=
          KamletMeshCoords.kamletJnetBaseY(params, kY) +
            (jInK / params.jCols).U(params.yPosWidth.W)
      }
    }
    io.axi(idx) <> m.io.axi
    m
  }

  val controlNodes = Seq.tabulate(params.kCols, params.kRows) { (kX, kY) =>
    val n: CombinedNetworkNode = withReset(resetPipeline.childReset) {
      Module(new CombinedNetworkNode(params, childResetBudget))
    }
    n.io.thisX := KamletMeshCoords.memletKnetX(params, io.knetOffsetX, kX)
    n.io.thisY := KamletMeshCoords.memletKnetY(params, io.knetOffsetY, kY)
    n.io.aHi <> memlets(kX)(kY).io.controlAHi
    memlets(kX)(kY).io.controlBHo <> n.io.bHo
    n.io.aHo.ready := true.B
    n.io.bHi.valid := false.B
    n.io.bHi.bits := DontCare
    n
  }

  def tieIn(port: DecoupledIO[NetworkWord]): Unit = {
    port.valid := false.B
    port.bits := DontCare
  }

  def tieOut(port: DecoupledIO[NetworkWord]): Unit = {
    port.ready := true.B
  }

  def tieSyncIn(port: SyncIO): Unit = {
    port.in.valid := false.B
    port.in.bits := 0.U
  }

  def connectKnetEastWest(left: CombinedNetworkNode, right: CombinedNetworkNode): Unit = {
    for (ch <- 0 until params.nAChannels) {
      left.io.aEo(ch) <> right.io.aWi(ch)
      right.io.aWo(ch) <> left.io.aEi(ch)
    }
    for (ch <- 0 until params.nBChannels) {
      left.io.bEo(ch) <> right.io.bWi(ch)
      right.io.bWo(ch) <> left.io.bEi(ch)
    }
  }

  def connectKnetToWestMesh(node: CombinedNetworkNode, kY: Int): Unit = {
    for (ch <- 0 until params.nAChannels) {
      node.io.aEi(ch) <> mesh.io.wKamletAOut(kY)(ch)
      node.io.aEo(ch) <> mesh.io.wKamletAIn(kY)(ch)
    }
    for (ch <- 0 until params.nBChannels) {
      node.io.bEi(ch) <> mesh.io.wKamletBOut(kY)(ch)
      node.io.bEo(ch) <> mesh.io.wKamletBIn(kY)(ch)
    }
  }

  def connectKnetToEastMesh(node: CombinedNetworkNode, kY: Int): Unit = {
    for (ch <- 0 until params.nAChannels) {
      node.io.aWi(ch) <> mesh.io.eKamletAOut(kY)(ch)
      node.io.aWo(ch) <> mesh.io.eKamletAIn(kY)(ch)
    }
    for (ch <- 0 until params.nBChannels) {
      node.io.bWi(ch) <> mesh.io.eKamletBOut(kY)(ch)
      node.io.bWo(ch) <> mesh.io.eKamletBIn(kY)(ch)
    }
  }

  def tieKnetNorthSouth(node: CombinedNetworkNode): Unit = {
    for (ch <- 0 until params.nAChannels) {
      tieIn(node.io.aNi(ch))
      tieOut(node.io.aNo(ch))
      tieIn(node.io.aSi(ch))
      tieOut(node.io.aSo(ch))
    }
    for (ch <- 0 until params.nBChannels) {
      tieIn(node.io.bNi(ch))
      tieOut(node.io.bNo(ch))
      tieIn(node.io.bSi(ch))
      tieOut(node.io.bSo(ch))
    }
  }

  def tieKnetWest(node: CombinedNetworkNode): Unit = {
    for (ch <- 0 until params.nAChannels) {
      tieIn(node.io.aWi(ch))
      tieOut(node.io.aWo(ch))
    }
    for (ch <- 0 until params.nBChannels) {
      tieIn(node.io.bWi(ch))
      tieOut(node.io.bWo(ch))
    }
  }

  def tieKnetEast(node: CombinedNetworkNode): Unit = {
    for (ch <- 0 until params.nAChannels) {
      tieIn(node.io.aEi(ch))
      tieOut(node.io.aEo(ch))
    }
    for (ch <- 0 until params.nBChannels) {
      tieIn(node.io.bEi(ch))
      tieOut(node.io.bEo(ch))
    }
  }

  for (kX <- 0 until params.kCols) {
    for (kY <- 0 until params.kRows) {
      tieKnetNorthSouth(controlNodes(kX)(kY))
    }
  }

  val halfCols = KamletMeshCoords.halfCols(params)

  for (kY <- 0 until params.kRows) {
    for (kX <- 0 until halfCols - 1) {
      connectKnetEastWest(controlNodes(kX)(kY), controlNodes(kX + 1)(kY))
    }
    tieKnetWest(controlNodes(0)(kY))
    connectKnetToWestMesh(controlNodes(halfCols - 1)(kY), kY)

    connectKnetToEastMesh(controlNodes(halfCols)(kY), kY)
    for (kX <- halfCols until params.kCols - 1) {
      connectKnetEastWest(controlNodes(kX)(kY), controlNodes(kX + 1)(kY))
    }
    tieKnetEast(controlNodes(params.kCols - 1)(kY))
  }

  case class RouterEndpoint(memlet: Memlet, router: Int, x: Int, y: Int)

  val routerEndpoints = (
    for {
      kX <- 0 until params.kCols
      kY <- 0 until params.kRows
      router <- 0 until params.nMemletRouters
    } yield {
      RouterEndpoint(
        memlets(kX)(kY),
        router,
        KamletMeshCoords.memletJnetRouterXInt(params, kX, router),
        KamletMeshCoords.memletJnetRouterYInt(params, kX, kY, router)
      )
    }
  ).toSeq

  val routerByCoord = routerEndpoints.map(e => (e.x, e.y) -> e).toMap

  def connectRoutersEastWest(left: RouterEndpoint, right: RouterEndpoint): Unit = {
    for (ch <- 0 until params.nAChannels) {
      left.memlet.io.aEo(left.router)(ch) <> right.memlet.io.aWi(right.router)(ch)
      right.memlet.io.aWo(right.router)(ch) <> left.memlet.io.aEi(left.router)(ch)
    }
    for (ch <- 0 until params.nBChannels) {
      left.memlet.io.bEo(left.router)(ch) <> right.memlet.io.bWi(right.router)(ch)
      right.memlet.io.bWo(right.router)(ch) <> left.memlet.io.bEi(left.router)(ch)
    }
  }

  def connectRoutersNorthSouth(north: RouterEndpoint, south: RouterEndpoint): Unit = {
    for (ch <- 0 until params.nAChannels) {
      south.memlet.io.aNi(south.router)(ch) <> north.memlet.io.aSo(north.router)(ch)
      south.memlet.io.aNo(south.router)(ch) <> north.memlet.io.aSi(north.router)(ch)
    }
    for (ch <- 0 until params.nBChannels) {
      south.memlet.io.bNi(south.router)(ch) <> north.memlet.io.bSo(north.router)(ch)
      south.memlet.io.bNo(south.router)(ch) <> north.memlet.io.bSi(north.router)(ch)
    }
  }

  def connectRouterToWestMesh(e: RouterEndpoint): Unit = {
    val kY = e.y / params.jRows
    val jY = e.y % params.jRows
    for (ch <- 0 until params.nAChannels) {
      e.memlet.io.aEi(e.router)(ch) <> mesh.io.wChannelsOut(kY)(jY)(ch)
      e.memlet.io.aEo(e.router)(ch) <> mesh.io.wChannelsIn(kY)(jY)(ch)
    }
    for (ch <- 0 until params.nBChannels) {
      val meshCh = params.nAChannels + ch
      e.memlet.io.bEi(e.router)(ch) <> mesh.io.wChannelsOut(kY)(jY)(meshCh)
      e.memlet.io.bEo(e.router)(ch) <> mesh.io.wChannelsIn(kY)(jY)(meshCh)
    }
  }

  def connectRouterToEastMesh(e: RouterEndpoint): Unit = {
    val kY = e.y / params.jRows
    val jY = e.y % params.jRows
    for (ch <- 0 until params.nAChannels) {
      e.memlet.io.aWi(e.router)(ch) <> mesh.io.eChannelsOut(kY)(jY)(ch)
      e.memlet.io.aWo(e.router)(ch) <> mesh.io.eChannelsIn(kY)(jY)(ch)
    }
    for (ch <- 0 until params.nBChannels) {
      val meshCh = params.nAChannels + ch
      e.memlet.io.bWi(e.router)(ch) <> mesh.io.eChannelsOut(kY)(jY)(meshCh)
      e.memlet.io.bWo(e.router)(ch) <> mesh.io.eChannelsIn(kY)(jY)(meshCh)
    }
  }

  def tieRouterNorth(e: RouterEndpoint): Unit = {
    for (ch <- 0 until params.nAChannels) {
      tieIn(e.memlet.io.aNi(e.router)(ch))
      tieOut(e.memlet.io.aNo(e.router)(ch))
    }
    for (ch <- 0 until params.nBChannels) {
      tieIn(e.memlet.io.bNi(e.router)(ch))
      tieOut(e.memlet.io.bNo(e.router)(ch))
    }
  }

  def tieRouterSouth(e: RouterEndpoint): Unit = {
    for (ch <- 0 until params.nAChannels) {
      tieIn(e.memlet.io.aSi(e.router)(ch))
      tieOut(e.memlet.io.aSo(e.router)(ch))
    }
    for (ch <- 0 until params.nBChannels) {
      tieIn(e.memlet.io.bSi(e.router)(ch))
      tieOut(e.memlet.io.bSo(e.router)(ch))
    }
  }

  def tieRouterWest(e: RouterEndpoint): Unit = {
    for (ch <- 0 until params.nAChannels) {
      tieIn(e.memlet.io.aWi(e.router)(ch))
      tieOut(e.memlet.io.aWo(e.router)(ch))
    }
    for (ch <- 0 until params.nBChannels) {
      tieIn(e.memlet.io.bWi(e.router)(ch))
      tieOut(e.memlet.io.bWo(e.router)(ch))
    }
  }

  def tieRouterEast(e: RouterEndpoint): Unit = {
    for (ch <- 0 until params.nAChannels) {
      tieIn(e.memlet.io.aEi(e.router)(ch))
      tieOut(e.memlet.io.aEo(e.router)(ch))
    }
    for (ch <- 0 until params.nBChannels) {
      tieIn(e.memlet.io.bEi(e.router)(ch))
      tieOut(e.memlet.io.bEo(e.router)(ch))
    }
  }

  val meshJnetWestX = KamletMeshCoords.sideJnetCols(params)
  val meshJnetEastX = KamletMeshCoords.sideJnetCols(params) + params.kCols * params.jCols - 1

  for (e <- routerEndpoints) {
    routerByCoord.get((e.x, e.y - 1)) match {
      case Some(north) => connectRoutersNorthSouth(north, e)
      case None => tieRouterNorth(e)
    }

    if (!routerByCoord.contains((e.x, e.y + 1))) {
      tieRouterSouth(e)
    }

    if (!routerByCoord.contains((e.x - 1, e.y))) {
      if (e.x == meshJnetEastX + 1) {
        connectRouterToEastMesh(e)
      } else {
        tieRouterWest(e)
      }
    }

    routerByCoord.get((e.x + 1, e.y)) match {
      case Some(east) => connectRoutersEastWest(e, east)
      case None =>
        if (e.x == meshJnetWestX - 1) {
          connectRouterToWestMesh(e)
        } else {
          tieRouterEast(e)
        }
    }
  }

  for (kX <- 0 until params.kCols) {
    for (jX <- 0 until params.jCols) {
      for (ch <- 0 until totalChannels) {
        mesh.io.nChannelsIn(kX)(jX)(ch) <> io.nChannelsIn(kX)(jX)(ch)
        mesh.io.nChannelsOut(kX)(jX)(ch) <> io.nChannelsOut(kX)(jX)(ch)
        tieIn(mesh.io.sChannelsIn(kX)(jX)(ch))
        tieOut(mesh.io.sChannelsOut(kX)(jX)(ch))
      }
    }
  }

  for (kX <- 0 until params.kCols) {
    for (ch <- 0 until params.nAChannels) {
      mesh.io.nKamletAIn(kX)(ch) <> io.nKamletAIn(kX)(ch)
      mesh.io.nKamletAOut(kX)(ch) <> io.nKamletAOut(kX)(ch)
      tieIn(mesh.io.sKamletAIn(kX)(ch))
      tieOut(mesh.io.sKamletAOut(kX)(ch))
    }
    for (ch <- 0 until params.nBChannels) {
      mesh.io.nKamletBIn(kX)(ch) <> io.nKamletBIn(kX)(ch)
      mesh.io.nKamletBOut(kX)(ch) <> io.nKamletBOut(kX)(ch)
      tieIn(mesh.io.sKamletBIn(kX)(ch))
      tieOut(mesh.io.sKamletBOut(kX)(ch))
    }
  }

  for (kX <- 0 until params.kCols) {
    mesh.io.nSyncN(kX).in := io.nSyncN(kX).in
    io.nSyncN(kX).out := mesh.io.nSyncN(kX).out
    mesh.io.nSyncNE(kX).in := io.nSyncNE(kX).in
    io.nSyncNE(kX).out := mesh.io.nSyncNE(kX).out
    mesh.io.nSyncNW(kX).in := io.nSyncNW(kX).in
    io.nSyncNW(kX).out := mesh.io.nSyncNW(kX).out

    tieSyncIn(mesh.io.sSyncS(kX))
    tieSyncIn(mesh.io.sSyncSE(kX))
    tieSyncIn(mesh.io.sSyncSW(kX))
  }

  for (kY <- 0 until params.kRows) {
    tieSyncIn(mesh.io.eSyncE(kY))
    tieSyncIn(mesh.io.wSyncW(kY))
  }

  for (i <- 0 until params.kRows - 1) {
    tieSyncIn(mesh.io.eSyncNE(i))
    tieSyncIn(mesh.io.eSyncSE(i))
    tieSyncIn(mesh.io.wSyncNW(i))
    tieSyncIn(mesh.io.wSyncSW(i))
  }
  }
}

object KamletMeshWithMemletsGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <configFile>")
      System.exit(1)
    }
    val params = ZamletParams.fromFile(args(0))
    new KamletMeshWithMemlets(params)
  }
}

object KamletMeshWithMemletsMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  KamletMeshWithMemletsGenerator.generate(outputDir, Seq(configFile))
}
