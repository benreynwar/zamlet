package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.NetworkWord

/**
 * Configuration for external sync neighbors at mesh perimeter.
 * If true, that perimeter position has external neighbors for all its outward directions.
 *
 * Corners: single Boolean each
 * Edges (excluding corners): Seq[Boolean] with length kCols-2 or kRows-2
 */
case class MeshEdgeNeighbors(
  neCorner: Boolean,
  nwCorner: Boolean,
  seCorner: Boolean,
  swCorner: Boolean,
  nEdge: Seq[Boolean],  // length kCols-2, indexed 0 = kX=1
  sEdge: Seq[Boolean],  // length kCols-2, indexed 0 = kX=1
  eEdge: Seq[Boolean],  // length kRows-2, indexed 0 = kY=1
  wEdge: Seq[Boolean]   // length kRows-2, indexed 0 = kY=1
)

object MeshEdgeNeighbors {
  def isolated(kCols: Int, kRows: Int): MeshEdgeNeighbors = MeshEdgeNeighbors(
    neCorner = false,
    nwCorner = false,
    seCorner = false,
    swCorner = false,
    nEdge = Seq.fill(math.max(0, kCols - 2))(false),
    sEdge = Seq.fill(math.max(0, kCols - 2))(false),
    eEdge = Seq.fill(math.max(0, kRows - 2))(false),
    wEdge = Seq.fill(math.max(0, kRows - 2))(false)
  )
}

/** Bidirectional sync port pair */
class SyncIO extends Bundle {
  val in = Input(new SyncPort)
  val out = Output(new SyncPort)
}

/**
 * KamletMesh is a grid of kamlets forming the compute fabric.
 *
 * The mesh handles:
 * - Network routing between kamlets (N/S/E/W packet channels)
 * - Sync network connections (8 directions including diagonals)
 * - External edge ports for lamlet and memory interfaces
 *
 * Grid layout (looking down, Y increases southward):
 *
 *              North edge (to lamlet)
 *         ┌─────────┬─────────┐
 *         │ K(0,0)  │ K(1,0)  │
 *   West  ├─────────┼─────────┤  East
 *   edge  │ K(0,1)  │ K(1,1)  │  edge
 *         └─────────┴─────────┘
 *              South edge (to memory)
 *
 * Sync network: Each kamlet connects to 8 neighbors (N, S, E, W, NE, NW, SE, SW).
 * Edge kamlets connect to external neighbors based on edgeNeighbors config.
 */
class KamletMesh(params: ZamletParams, edgeNeighbors: MeshEdgeNeighbors) extends Module {
  val io = IO(new Bundle {
    // North edge network ports (to lamlet/external)
    val nChannelsIn = Vec(params.kCols, Vec(params.jCols,
      Vec(params.nAChannels + params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))))
    val nChannelsOut = Vec(params.kCols, Vec(params.jCols,
      Vec(params.nAChannels + params.nBChannels, Decoupled(new NetworkWord(params)))))

    // South edge network ports (to memory/external)
    val sChannelsIn = Vec(params.kCols, Vec(params.jCols,
      Vec(params.nAChannels + params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))))
    val sChannelsOut = Vec(params.kCols, Vec(params.jCols,
      Vec(params.nAChannels + params.nBChannels, Decoupled(new NetworkWord(params)))))

    // East edge network ports
    val eChannelsIn = Vec(params.kRows, Vec(params.jRows,
      Vec(params.nAChannels + params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))))
    val eChannelsOut = Vec(params.kRows, Vec(params.jRows,
      Vec(params.nAChannels + params.nBChannels, Decoupled(new NetworkWord(params)))))

    // West edge network ports
    val wChannelsIn = Vec(params.kRows, Vec(params.jRows,
      Vec(params.nAChannels + params.nBChannels, Flipped(Decoupled(new NetworkWord(params))))))
    val wChannelsOut = Vec(params.kRows, Vec(params.jRows,
      Vec(params.nAChannels + params.nBChannels, Decoupled(new NetworkWord(params)))))

    // Sync network external ports - organized by edge and direction
    // North edge: N, NE, NW directions for all kCols positions
    val nSyncN = Vec(params.kCols, new SyncIO)
    val nSyncNE = Vec(params.kCols, new SyncIO)
    val nSyncNW = Vec(params.kCols, new SyncIO)

    // South edge: S, SE, SW directions for all kCols positions
    val sSyncS = Vec(params.kCols, new SyncIO)
    val sSyncSE = Vec(params.kCols, new SyncIO)
    val sSyncSW = Vec(params.kCols, new SyncIO)

    // East edge: E for all kRows, NE/SE for kRows-1 (excluding corners covered by N/S edges)
    val eSyncE = Vec(params.kRows, new SyncIO)
    val eSyncNE = Vec(params.kRows - 1, new SyncIO)  // rows 1 to kRows-1
    val eSyncSE = Vec(params.kRows - 1, new SyncIO)  // rows 0 to kRows-2

    // West edge: W for all kRows, NW/SW for kRows-1 (excluding corners covered by N/S edges)
    val wSyncW = Vec(params.kRows, new SyncIO)
    val wSyncNW = Vec(params.kRows - 1, new SyncIO)  // rows 1 to kRows-1
    val wSyncSW = Vec(params.kRows - 1, new SyncIO)  // rows 0 to kRows-2
  })

  // ============================================================
  // Calculate neighbor configuration for each kamlet position
  // ============================================================

  // Helper to check if a north boundary position has external neighbors
  def hasNorthExternal(col: Int): Boolean = {
    if (col == 0) edgeNeighbors.nwCorner
    else if (col == params.kCols - 1) edgeNeighbors.neCorner
    else edgeNeighbors.nEdge(col - 1)
  }

  // Helper to check if a south boundary position has external neighbors
  def hasSouthExternal(col: Int): Boolean = {
    if (col == 0) edgeNeighbors.swCorner
    else if (col == params.kCols - 1) edgeNeighbors.seCorner
    else edgeNeighbors.sEdge(col - 1)
  }

  // Helper to check if an east boundary position has external neighbors
  def hasEastExternal(row: Int): Boolean = {
    if (row == 0) edgeNeighbors.neCorner
    else if (row == params.kRows - 1) edgeNeighbors.seCorner
    else edgeNeighbors.eEdge(row - 1)
  }

  // Helper to check if a west boundary position has external neighbors
  def hasWestExternal(row: Int): Boolean = {
    if (row == 0) edgeNeighbors.nwCorner
    else if (row == params.kRows - 1) edgeNeighbors.swCorner
    else edgeNeighbors.wEdge(row - 1)
  }

  def getNeighbors(kX: Int, kY: Int): SyncNeighbors = {
    // Internal neighbors (within the mesh)
    val hasNInternal = kY > 0
    val hasSInternal = kY < params.kRows - 1
    val hasEInternal = kX < params.kCols - 1
    val hasWInternal = kX > 0
    val hasNEInternal = kY > 0 && kX < params.kCols - 1
    val hasNWInternal = kY > 0 && kX > 0
    val hasSEInternal = kY < params.kRows - 1 && kX < params.kCols - 1
    val hasSWInternal = kY < params.kRows - 1 && kX > 0

    // External neighbors: check where each direction exits the mesh boundary
    // N: exits through north boundary at column kX
    val hasNExternal = kY == 0 && hasNorthExternal(kX)

    // S: exits through south boundary at column kX
    val hasSExternal = kY == params.kRows - 1 && hasSouthExternal(kX)

    // E: exits through east boundary at row kY
    val hasEExternal = kX == params.kCols - 1 && hasEastExternal(kY)

    // W: exits through west boundary at row kY
    val hasWExternal = kX == 0 && hasWestExternal(kY)

    // NE: target is (kX+1, kY-1), external if on north edge or east edge
    val hasNEExternal = {
      val onNorthEdge = kY == 0
      val onEastEdge = kX == params.kCols - 1
      if (onNorthEdge && onEastEdge) {
        // NE corner: diagonal exit, check neCorner
        edgeNeighbors.neCorner
      } else if (onNorthEdge) {
        // Exits through north boundary at column kX+1
        hasNorthExternal(kX + 1)
      } else if (onEastEdge) {
        // Exits through east boundary at row kY-1
        hasEastExternal(kY - 1)
      } else false
    }

    // NW: target is (kX-1, kY-1), external if on north edge or west edge
    val hasNWExternal = {
      val onNorthEdge = kY == 0
      val onWestEdge = kX == 0
      if (onNorthEdge && onWestEdge) {
        // NW corner: diagonal exit, check nwCorner
        edgeNeighbors.nwCorner
      } else if (onNorthEdge) {
        // Exits through north boundary at column kX-1
        hasNorthExternal(kX - 1)
      } else if (onWestEdge) {
        // Exits through west boundary at row kY-1
        hasWestExternal(kY - 1)
      } else false
    }

    // SE: target is (kX+1, kY+1), external if on south edge or east edge
    val hasSEExternal = {
      val onSouthEdge = kY == params.kRows - 1
      val onEastEdge = kX == params.kCols - 1
      if (onSouthEdge && onEastEdge) {
        // SE corner: diagonal exit, check seCorner
        edgeNeighbors.seCorner
      } else if (onSouthEdge) {
        // Exits through south boundary at column kX+1
        hasSouthExternal(kX + 1)
      } else if (onEastEdge) {
        // Exits through east boundary at row kY+1
        hasEastExternal(kY + 1)
      } else false
    }

    // SW: target is (kX-1, kY+1), external if on south edge or west edge
    val hasSWExternal = {
      val onSouthEdge = kY == params.kRows - 1
      val onWestEdge = kX == 0
      if (onSouthEdge && onWestEdge) {
        // SW corner: diagonal exit, check swCorner
        edgeNeighbors.swCorner
      } else if (onSouthEdge) {
        // Exits through south boundary at column kX-1
        hasSouthExternal(kX - 1)
      } else if (onWestEdge) {
        // Exits through west boundary at row kY+1
        hasWestExternal(kY + 1)
      } else false
    }

    SyncNeighbors(
      hasN = hasNInternal || hasNExternal,
      hasS = hasSInternal || hasSExternal,
      hasE = hasEInternal || hasEExternal,
      hasW = hasWInternal || hasWExternal,
      hasNE = hasNEInternal || hasNEExternal,
      hasNW = hasNWInternal || hasNWExternal,
      hasSE = hasSEInternal || hasSEExternal,
      hasSW = hasSWInternal || hasSWExternal
    )
  }

  // ============================================================
  // Instantiate kamlets - indexed as kamlets(kX)(kY)
  // ============================================================
  val kamlets = Seq.tabulate(params.kCols, params.kRows) { (kX, kY) =>
    val neighbors = getNeighbors(kX, kY)
    val k = Module(new Kamlet(params, neighbors))
    k.io.kX := kX.U
    k.io.kY := kY.U
    k
  }

  // ============================================================
  // Connect network ports between kamlets and to external edges
  // ============================================================
  val totalChannels = params.nAChannels + params.nBChannels

  for (kX <- 0 until params.kCols) {
    for (kY <- 0 until params.kRows) {
      val k = kamlets(kX)(kY)

      // North connections
      if (kY == 0) {
        // Edge: connect to external north ports
        for (j <- 0 until params.jCols) {
          for (ch <- 0 until totalChannels) {
            k.io.nChannelsIn(j)(ch) <> io.nChannelsIn(kX)(j)(ch)
            k.io.nChannelsOut(j)(ch) <> io.nChannelsOut(kX)(j)(ch)
          }
        }
      } else {
        // Internal: connect to southern ports of neighbor above
        val neighbor = kamlets(kX)(kY - 1)
        for (j <- 0 until params.jCols) {
          for (ch <- 0 until totalChannels) {
            k.io.nChannelsIn(j)(ch) <> neighbor.io.sChannelsOut(j)(ch)
            k.io.nChannelsOut(j)(ch) <> neighbor.io.sChannelsIn(j)(ch)
          }
        }
      }

      // South connections
      if (kY == params.kRows - 1) {
        // Edge: connect to external south ports
        for (j <- 0 until params.jCols) {
          for (ch <- 0 until totalChannels) {
            k.io.sChannelsIn(j)(ch) <> io.sChannelsIn(kX)(j)(ch)
            k.io.sChannelsOut(j)(ch) <> io.sChannelsOut(kX)(j)(ch)
          }
        }
      }
      // Internal south connections handled by north connections of neighbor below

      // East connections
      if (kX == params.kCols - 1) {
        // Edge: connect to external east ports
        for (j <- 0 until params.jRows) {
          for (ch <- 0 until totalChannels) {
            k.io.eChannelsIn(j)(ch) <> io.eChannelsIn(kY)(j)(ch)
            k.io.eChannelsOut(j)(ch) <> io.eChannelsOut(kY)(j)(ch)
          }
        }
      } else {
        // Internal: connect to western ports of neighbor to the right
        val neighbor = kamlets(kX + 1)(kY)
        for (j <- 0 until params.jRows) {
          for (ch <- 0 until totalChannels) {
            k.io.eChannelsIn(j)(ch) <> neighbor.io.wChannelsOut(j)(ch)
            k.io.eChannelsOut(j)(ch) <> neighbor.io.wChannelsIn(j)(ch)
          }
        }
      }

      // West connections
      if (kX == 0) {
        // Edge: connect to external west ports
        for (j <- 0 until params.jRows) {
          for (ch <- 0 until totalChannels) {
            k.io.wChannelsIn(j)(ch) <> io.wChannelsIn(kY)(j)(ch)
            k.io.wChannelsOut(j)(ch) <> io.wChannelsOut(kY)(j)(ch)
          }
        }
      }
      // Internal west connections handled by east connections of neighbor to the left
    }
  }

  // ============================================================
  // Connect sync network between kamlets
  // ============================================================
  for (kX <- 0 until params.kCols) {
    for (kY <- 0 until params.kRows) {
      val k = kamlets(kX)(kY)

      // N/S connections
      if (kY > 0) {
        val neighbor = kamlets(kX)(kY - 1)
        k.io.syncPortIn(SyncDirection.N) := neighbor.io.syncPortOut(SyncDirection.S)
        neighbor.io.syncPortIn(SyncDirection.S) := k.io.syncPortOut(SyncDirection.N)
      }

      // E/W connections
      if (kX < params.kCols - 1) {
        val neighbor = kamlets(kX + 1)(kY)
        k.io.syncPortIn(SyncDirection.E) := neighbor.io.syncPortOut(SyncDirection.W)
        neighbor.io.syncPortIn(SyncDirection.W) := k.io.syncPortOut(SyncDirection.E)
      }

      // Diagonal connections
      // NE
      if (kY > 0 && kX < params.kCols - 1) {
        val neighbor = kamlets(kX + 1)(kY - 1)
        k.io.syncPortIn(SyncDirection.NE) := neighbor.io.syncPortOut(SyncDirection.SW)
        neighbor.io.syncPortIn(SyncDirection.SW) := k.io.syncPortOut(SyncDirection.NE)
      }

      // NW
      if (kY > 0 && kX > 0) {
        val neighbor = kamlets(kX - 1)(kY - 1)
        k.io.syncPortIn(SyncDirection.NW) := neighbor.io.syncPortOut(SyncDirection.SE)
        neighbor.io.syncPortIn(SyncDirection.SE) := k.io.syncPortOut(SyncDirection.NW)
      }

    }
  }

  // ============================================================
  // Sync network edge connections
  // ============================================================

  // Helper to connect a kamlet's sync port to an external SyncIO
  def connectSyncExternal(k: Kamlet, dir: Int, extIO: SyncIO): Unit = {
    extIO.out := k.io.syncPortOut(dir)
    k.io.syncPortIn(dir) := extIO.in
  }

  // North edge (kY=0): N, NE, NW for all kCols positions
  for (kX <- 0 until params.kCols) {
    val k = kamlets(kX)(0)
    connectSyncExternal(k, SyncDirection.N, io.nSyncN(kX))
    connectSyncExternal(k, SyncDirection.NE, io.nSyncNE(kX))
    connectSyncExternal(k, SyncDirection.NW, io.nSyncNW(kX))
  }

  // South edge (kY=kRows-1): S, SE, SW for all kCols positions
  for (kX <- 0 until params.kCols) {
    val k = kamlets(kX)(params.kRows - 1)
    connectSyncExternal(k, SyncDirection.S, io.sSyncS(kX))
    connectSyncExternal(k, SyncDirection.SE, io.sSyncSE(kX))
    connectSyncExternal(k, SyncDirection.SW, io.sSyncSW(kX))
  }

  // East edge (kX=kCols-1): E for all kRows
  for (kY <- 0 until params.kRows) {
    val k = kamlets(params.kCols - 1)(kY)
    connectSyncExternal(k, SyncDirection.E, io.eSyncE(kY))
  }

  // East edge NE: rows 1 to kRows-1 (index i corresponds to row i+1)
  for (i <- 0 until params.kRows - 1) {
    val kY = i + 1
    val k = kamlets(params.kCols - 1)(kY)
    connectSyncExternal(k, SyncDirection.NE, io.eSyncNE(i))
  }

  // East edge SE: rows 0 to kRows-2 (index i corresponds to row i)
  for (i <- 0 until params.kRows - 1) {
    val kY = i
    val k = kamlets(params.kCols - 1)(kY)
    connectSyncExternal(k, SyncDirection.SE, io.eSyncSE(i))
  }

  // West edge (kX=0): W for all kRows
  for (kY <- 0 until params.kRows) {
    val k = kamlets(0)(kY)
    connectSyncExternal(k, SyncDirection.W, io.wSyncW(kY))
  }

  // West edge NW: rows 1 to kRows-1 (index i corresponds to row i+1)
  for (i <- 0 until params.kRows - 1) {
    val kY = i + 1
    val k = kamlets(0)(kY)
    connectSyncExternal(k, SyncDirection.NW, io.wSyncNW(i))
  }

  // West edge SW: rows 0 to kRows-2 (index i corresponds to row i)
  for (i <- 0 until params.kRows - 1) {
    val kY = i
    val k = kamlets(0)(kY)
    connectSyncExternal(k, SyncDirection.SW, io.wSyncSW(i))
  }
}

object KamletMeshGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <configFile>")
      System.exit(1)
    }
    val params = ZamletParams.fromFile(args(0))
    val edgeNeighbors = MeshEdgeNeighbors.isolated(params.kCols, params.kRows)
    new KamletMesh(params, edgeNeighbors)
  }
}

object KamletMeshMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  KamletMeshGenerator.generate(outputDir, Seq(configFile))
}
