package zamlet.kamlet

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import zamlet.utils.ValidBuffer
import io.circe._
import io.circe.generic.semiauto._
import io.circe.parser._
import scala.io.Source

case class SynchronizerParams(
  maxConcurrentSyncs: Int = 4,
  resultOutputReg: Boolean = false,
  portOutOutputReg: Boolean = false,
  minPipelineReg: Boolean = false
)

object SynchronizerParams {
  implicit val decoder: Decoder[SynchronizerParams] = deriveDecoder[SynchronizerParams]
}

case class SynchronizerTestParams(
  neighbors: SyncNeighbors = SyncNeighbors(),
  sync: SynchronizerParams = SynchronizerParams()
)

object SynchronizerTestParams {
  implicit val neighborsDecoder: Decoder[SyncNeighbors] = deriveDecoder[SyncNeighbors]
  implicit val decoder: Decoder[SynchronizerTestParams] = deriveDecoder[SynchronizerTestParams]

  def fromFile(fileName: String): SynchronizerTestParams = {
    val jsonContent = Source.fromFile(fileName).mkString
    decode[SynchronizerTestParams](jsonContent) match {
      case Right(params) => params
      case Left(error) =>
        println(s"Failed to parse JSON: ${error}")
        System.exit(1)
        null
    }
  }
}

/**
 * Synchronizer for lamlet-wide synchronization with optional MIN value aggregation.
 *
 * Used by kamlets and lamlet for:
 * - IdentQuery: Find oldest active ident across all kamlets (MIN aggregation)
 * - Future: Barrier synchronization, reduction operations
 *
 * Network topology: Each node connects to up to 8 neighbors (N, S, E, W, NE, NW, SE, SW)
 * via 9-bit buses. The lamlet sits at position (0, -1) and only connects S to kamlet (0, 0).
 *
 * Bus format: [8] = last_byte, [7:0] = data byte
 * Packet format: Byte 0 = sync_ident, Byte 1 = value (for MIN aggregation)
 */

object SyncDirection {
  val N  = 0
  val S  = 1
  val E  = 2
  val W  = 3
  val NE = 4
  val NW = 5
  val SE = 6
  val SW = 7
  val count = 8
}

class SyncPort extends Bundle {
  val valid = Bool()
  val bits = UInt(9.W)
}

class SyncEvent extends Bundle {
  val syncIdent = UInt(8.W)
  val value = UInt(8.W)
}

class SyncEntry extends Bundle {
  val valid = Bool()
  val syncIdent = UInt(8.W)
  val localSeen = Bool()
  val localValue = UInt(8.W)

  val quadrantSynced = Vec(4, Bool())  // NE, NW, SE, SW (indices 0-3)
  val columnSynced = Vec(2, Bool())    // N, S (indices 0-1)
  val rowSynced = Vec(2, Bool())       // E, W (indices 0-1)

  val quadrantValues = Vec(4, UInt(8.W))
  val columnValues = Vec(2, UInt(8.W))
  val rowValues = Vec(2, UInt(8.W))

  val sent = Vec(SyncDirection.count, Bool())
}

class SynchronizerIO(maxConcurrentSyncs: Int) extends Bundle {
  val localEvent = Flipped(Valid(new SyncEvent))
  val result = Valid(new SyncEvent)

  val portOut = Output(Vec(SyncDirection.count, new SyncPort))
  val portIn = Input(Vec(SyncDirection.count, new SyncPort))
}

case class SyncNeighbors(
  hasN: Boolean = true,
  hasS: Boolean = true,
  hasE: Boolean = true,
  hasW: Boolean = true,
  hasNE: Boolean = true,
  hasNW: Boolean = true,
  hasSE: Boolean = true,
  hasSW: Boolean = true
)

class Synchronizer(
  neighbors: SyncNeighbors,
  params: SynchronizerParams = SynchronizerParams()
) extends Module {

  val io = IO(new SynchronizerIO(params.maxConcurrentSyncs))
  val maxConcurrentSyncs = params.maxConcurrentSyncs

  import SyncDirection._

  val hasNeighbor = VecInit(Seq(
    neighbors.hasN.B, neighbors.hasS.B, neighbors.hasE.B, neighbors.hasW.B,
    neighbors.hasNE.B, neighbors.hasNW.B, neighbors.hasSE.B, neighbors.hasSW.B
  ))

  val entries = RegInit(VecInit(Seq.fill(maxConcurrentSyncs)(0.U.asTypeOf(new SyncEntry))))

  val rxHasByte0 = RegInit(VecInit(Seq.fill(SyncDirection.count)(false.B)))
  val rxByte0 = Reg(Vec(SyncDirection.count, UInt(8.W)))

  val txActive = RegInit(VecInit(Seq.fill(SyncDirection.count)(false.B)))
  val txSyncIdx = Reg(Vec(SyncDirection.count, UInt(log2Ceil(maxConcurrentSyncs).W)))
  val txByteIdx = Reg(Vec(SyncDirection.count, UInt(1.W)))

  def findEntry(ident: UInt): (Bool, UInt) = {
    val found = VecInit(entries.map(e => e.valid && e.syncIdent === ident))
    val idx = OHToUInt(found.asUInt)
    (found.asUInt.orR, idx)
  }

  def allocEntry(ident: UInt): (Bool, UInt) = {
    val free = VecInit(entries.map(!_.valid))
    val idx = PriorityEncoder(free.asUInt)
    (free.asUInt.orR, idx)
  }

  def initTopology(e: SyncEntry): Unit = {
    e.quadrantSynced(0) := (!neighbors.hasNE).B
    e.quadrantSynced(1) := (!neighbors.hasNW).B
    e.quadrantSynced(2) := (!neighbors.hasSE).B
    e.quadrantSynced(3) := (!neighbors.hasSW).B
    e.columnSynced(0) := (!neighbors.hasN).B
    e.columnSynced(1) := (!neighbors.hasS).B
    e.rowSynced(0) := (!neighbors.hasE).B
    e.rowSynced(1) := (!neighbors.hasW).B
    for (i <- 0 until SyncDirection.count) {
      e.sent(i) := !hasNeighbor(i)
    }
    e.quadrantValues := VecInit(Seq.fill(4)(255.U(8.W)))
    e.columnValues := VecInit(Seq.fill(2)(255.U(8.W)))
    e.rowValues := VecInit(Seq.fill(2)(255.U(8.W)))
  }

  when (io.localEvent.valid) {
    val (found, foundIdx) = findEntry(io.localEvent.bits.syncIdent)
    val (canAlloc, allocIdx) = allocEntry(io.localEvent.bits.syncIdent)
    val idx = Mux(found, foundIdx, allocIdx)

    when (!found && canAlloc) {
      entries(idx).valid := true.B
      entries(idx).syncIdent := io.localEvent.bits.syncIdent
      entries(idx).localSeen := false.B
      initTopology(entries(idx))
    }

    when (found || canAlloc) {
      entries(idx).localSeen := true.B
      entries(idx).localValue := io.localEvent.bits.value
    }
  }

  for (dir <- 0 until SyncDirection.count) {
    when (io.portIn(dir).valid && hasNeighbor(dir)) {
      val data = io.portIn(dir).bits(7, 0)
      val lastByte = io.portIn(dir).bits(8)

      when (!rxHasByte0(dir)) {
        rxByte0(dir) := data
        rxHasByte0(dir) := true.B
      }.otherwise {
        rxHasByte0(dir) := false.B

        val ident = rxByte0(dir)
        val value = data

        val (found, foundIdx) = findEntry(ident)
        val (canAlloc, allocIdx) = allocEntry(ident)
        val idx = Mux(found, foundIdx, allocIdx)

        when (!found && canAlloc) {
          entries(idx).valid := true.B
          entries(idx).syncIdent := ident
          entries(idx).localSeen := false.B
          initTopology(entries(idx))
        }

        when (found || canAlloc) {
          val e = entries(idx)
          switch (dir.U) {
            is (N.U)  { e.columnSynced(0) := true.B; e.columnValues(0) := value }
            is (S.U)  { e.columnSynced(1) := true.B; e.columnValues(1) := value }
            is (E.U)  { e.rowSynced(0) := true.B; e.rowValues(0) := value }
            is (W.U)  { e.rowSynced(1) := true.B; e.rowValues(1) := value }
            is (NE.U) { e.quadrantSynced(0) := true.B; e.quadrantValues(0) := value }
            is (NW.U) { e.quadrantSynced(1) := true.B; e.quadrantValues(1) := value }
            is (SE.U) { e.quadrantSynced(2) := true.B; e.quadrantValues(2) := value }
            is (SW.U) { e.quadrantSynced(3) := true.B; e.quadrantValues(3) := value }
          }
        }
      }
    }
  }

  def canSend(e: SyncEntry, dir: Int): Bool = {
    val base = e.localSeen
    dir match {
      case N  => base && e.columnSynced(1)
      case S  => base && e.columnSynced(0)
      case E  => base && e.rowSynced(1)
      case W  => base && e.rowSynced(0)
      case NE => base && e.quadrantSynced(3) && e.columnSynced(1) && e.rowSynced(1)
      case NW => base && e.quadrantSynced(2) && e.columnSynced(1) && e.rowSynced(0)
      case SE => base && e.quadrantSynced(1) && e.columnSynced(0) && e.rowSynced(1)
      case SW => base && e.quadrantSynced(0) && e.columnSynced(0) && e.rowSynced(0)
    }
  }

  def valueForDirection(e: SyncEntry, dir: Int): UInt = {
    val values = Wire(Vec(4, UInt(8.W)))
    values(0) := e.localValue

    dir match {
      case N =>
        values(1) := e.columnValues(1)
        values(2) := 255.U
        values(3) := 255.U
      case S =>
        values(1) := e.columnValues(0)
        values(2) := 255.U
        values(3) := 255.U
      case E =>
        values(1) := e.rowValues(1)
        values(2) := 255.U
        values(3) := 255.U
      case W =>
        values(1) := e.rowValues(0)
        values(2) := 255.U
        values(3) := 255.U
      case NE =>
        values(1) := e.quadrantValues(3)
        values(2) := e.columnValues(1)
        values(3) := e.rowValues(1)
      case NW =>
        values(1) := e.quadrantValues(2)
        values(2) := e.columnValues(1)
        values(3) := e.rowValues(0)
      case SE =>
        values(1) := e.quadrantValues(1)
        values(2) := e.columnValues(0)
        values(3) := e.rowValues(1)
      case SW =>
        values(1) := e.quadrantValues(0)
        values(2) := e.columnValues(0)
        values(3) := e.rowValues(0)
    }

    values.reduceTree(_ min _)
  }

  val portOutInternal = Wire(Vec(SyncDirection.count, new SyncPort))

  for (dir <- 0 until SyncDirection.count) {
    portOutInternal(dir).valid := false.B
    portOutInternal(dir).bits := 0.U

    when (txActive(dir)) {
      val e = entries(txSyncIdx(dir))
      portOutInternal(dir).valid := true.B

      when (txByteIdx(dir) === 0.U) {
        portOutInternal(dir).bits := Cat(0.U(1.W), e.syncIdent)
        txByteIdx(dir) := 1.U
      }.otherwise {
        val minVal = valueForDirection(e, dir)
        portOutInternal(dir).bits := Cat(1.U(1.W), minVal)
        txActive(dir) := false.B
        e.sent(dir) := true.B
      }
    }.otherwise {
      for (i <- 0 until maxConcurrentSyncs) {
        val e = entries(i)
        when (e.valid && hasNeighbor(dir) && !e.sent(dir) && canSend(e, dir)) {
          txActive(dir) := true.B
          txSyncIdx(dir) := i.U
          txByteIdx(dir) := 0.U
        }
      }
    }
  }

  if (params.portOutOutputReg) {
    io.portOut := RegNext(portOutInternal)
  } else {
    io.portOut := portOutInternal
  }

  def isComplete(e: SyncEntry): Bool = {
    val allRegionsSynced = e.quadrantSynced.asUInt.andR &&
                           e.columnSynced.asUInt.andR &&
                           e.rowSynced.asUInt.andR

    val allSendsComplete = (e.sent.asUInt | (~hasNeighbor.asUInt)) === 0xFF.U

    e.valid && e.localSeen && allRegionsSynced && allSendsComplete
  }

  val completeMask = VecInit(entries.map(isComplete))
  val anyComplete = completeMask.asUInt.orR
  val completeIdx = PriorityEncoder(completeMask.asUInt)

  // Stage before MIN: bundle the values needed for MIN computation
  class PreMinBundle extends Bundle {
    val syncIdent = UInt(8.W)
    val values = Vec(9, UInt(8.W))
  }

  val preMin = Wire(Valid(new PreMinBundle))
  preMin.valid := anyComplete
  preMin.bits.syncIdent := entries(completeIdx).syncIdent
  val e = entries(completeIdx)
  preMin.bits.values := VecInit(Seq(
    e.localValue,
    e.quadrantValues(0), e.quadrantValues(1), e.quadrantValues(2), e.quadrantValues(3),
    e.columnValues(0), e.columnValues(1),
    e.rowValues(0), e.rowValues(1)
  ))

  when (anyComplete) {
    entries(completeIdx).valid := false.B
  }

  // Optional pipeline stage before MIN computation
  val preMinBuffered = ValidBuffer(preMin, params.minPipelineReg)

  // Compute MIN and produce result
  val resultInternal = Wire(Valid(new SyncEvent))
  resultInternal.valid := preMinBuffered.valid
  resultInternal.bits.syncIdent := preMinBuffered.bits.syncIdent
  resultInternal.bits.value := preMinBuffered.bits.values.reduceTree(_ min _)

  io.result := ValidBuffer(resultInternal, params.resultOutputReg)
}

object SynchronizerGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <outputDir> <configFile>")
      System.exit(1)
    }
    val testParams = SynchronizerTestParams.fromFile(args(0))
    new Synchronizer(testParams.neighbors, testParams.sync)
  }
}

object SynchronizerMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  SynchronizerGenerator.generate(outputDir, Seq(configFile))
}
