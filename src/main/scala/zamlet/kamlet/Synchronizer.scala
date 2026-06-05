package zamlet.kamlet

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import zamlet.utils.ValidBuffer
import zamlet.{SynchronizerParams, ZamletParams}
import io.circe._
import io.circe.generic.semiauto._
import io.circe.parser._
import scala.io.Source

case class SynchronizerTestParams(
  neighbors: SyncNeighbors = SyncNeighbors(),
  syncIdentWidth: Int = 3,
  sync: SynchronizerParams = SynchronizerParams()
)

object SynchronizerTestParams {
  implicit val synchronizerParamsDecoder: Decoder[SynchronizerParams] = deriveDecoder[SynchronizerParams]
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
 * Synchronizer for zamlet-wide synchronization with optional MIN value aggregation.
 *
 * Used by kamlets and lamlet for:
 * - IdentQuery: Find oldest active ident across all kamlets (MIN aggregation)
 * - Future: Barrier synchronization, reduction operations
 *
 * Network topology: Each node connects to up to 8 neighbors (N, S, E, W, NE, NW, SE, SW)
 * via 9-bit buses. The lamlet sits at position (0, -1) and only connects S to kamlet (0, 0).
 *
 * Bus format: [8] = last_byte, [7:0] = data byte
 * Packet format: Byte 0 = sync_ident, Byte 1 = value[7:0],
 * Byte 2 = value[15:8].
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

class SyncEvent(params: ZamletParams) extends Bundle {
  val syncIdent = params.syncIdent()
  val value = params.syncValue()
  val includeActiveMask = Bool()
  val mustDrainValid = Bool()
  val mustDrainSyncIdent = params.syncIdent()
}

class SyncEntry(params: ZamletParams) extends Bundle {
  val valid = Bool()
  // Note: syncIdent is NOT stored - it equals the entry index
  val includeActiveMask = Bool()
  val localSeen = Bool()
  val localValue = params.syncValue()
  val pendingLocal = Bool()
  val pendingMustDrainSyncIdent = params.syncIdent()

  val quadrantSynced = Vec(4, Bool())  // NE, NW, SE, SW (indices 0-3)
  val columnSynced = Vec(2, Bool())    // N, S (indices 0-1)
  val rowSynced = Vec(2, Bool())       // E, W (indices 0-1)

  val quadrantValues = Vec(4, params.syncValue())
  val columnValues = Vec(2, params.syncValue())
  val rowValues = Vec(2, params.syncValue())

  val sent = Vec(SyncDirection.count, Bool())
}

class SynchronizerIO(params: ZamletParams) extends Bundle {
  val localEvent = Flipped(Valid(new SyncEvent(params)))
  val result = Valid(new SyncEvent(params))

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
  params: ZamletParams = ZamletParams()
) extends Module {

  require(params.syncValueWidth == 16,
    s"Synchronizer packet format currently carries 16-bit values, got ${params.syncValueWidth}")
  require(params.syncIdentWidth == 3,
    s"Synchronizer packet header currently carries 3-bit sync idents, got ${params.syncIdentWidth}")

  val syncParams = params.synchronizerParams
  val maxConcurrentSyncs = params.maxConcurrentSyncs
  private val syncHeaderModeBit = 3
  private val syncHeaderIdentMsb = 2
  private val syncHeaderIdentLsb = 0

  val io = IO(new SynchronizerIO(params))

  import SyncDirection._

  val hasNeighbor = VecInit(Seq(
    neighbors.hasN.B, neighbors.hasS.B, neighbors.hasE.B, neighbors.hasW.B,
    neighbors.hasNE.B, neighbors.hasNW.B, neighbors.hasSE.B, neighbors.hasSW.B
  ))

  // Entry state - syncIdent IS the index, so no need for syncIdent field
  val entries = RegInit(VecInit(Seq.fill(maxConcurrentSyncs)(0.U.asTypeOf(new SyncEntry(params)))))

  val rxHasByte0 = RegInit(VecInit(Seq.fill(SyncDirection.count)(false.B)))
  val rxHasByte1 = RegInit(VecInit(Seq.fill(SyncDirection.count)(false.B)))
  val rxByte0 = Reg(Vec(SyncDirection.count, UInt(8.W)))
  val rxByte1 = Reg(Vec(SyncDirection.count, UInt(8.W)))
  val rxIncludeActiveMask = Reg(Vec(SyncDirection.count, Bool()))

  val txActive = RegInit(VecInit(Seq.fill(SyncDirection.count)(false.B)))
  val txSyncIdx = Reg(Vec(SyncDirection.count, UInt(log2Ceil(maxConcurrentSyncs).W)))
  val txByteIdx = Reg(Vec(SyncDirection.count, UInt(2.W)))

  val idxWidth = log2Ceil(maxConcurrentSyncs).W

  // Create a fresh initialized entry
  def freshEntry(): SyncEntry = {
    val e = Wire(new SyncEntry(params))
    e.valid := true.B
    e.includeActiveMask := false.B
    e.localSeen := false.B
    e.localValue := 0.U
    e.pendingLocal := false.B
    e.pendingMustDrainSyncIdent := 0.U
    e.quadrantSynced := VecInit(Seq(
      (!neighbors.hasNE).B, (!neighbors.hasNW).B, (!neighbors.hasSE).B, (!neighbors.hasSW).B
    ))
    e.columnSynced := VecInit(Seq((!neighbors.hasN).B, (!neighbors.hasS).B))
    e.rowSynced := VecInit(Seq((!neighbors.hasE).B, (!neighbors.hasW).B))
    e.quadrantValues := VecInit(Seq.fill(4)(((BigInt(1) << params.syncValueWidth) - 1).U(params.syncValueWidth.W)))
    e.columnValues := VecInit(Seq.fill(2)(((BigInt(1) << params.syncValueWidth) - 1).U(params.syncValueWidth.W)))
    e.rowValues := VecInit(Seq.fill(2)(((BigInt(1) << params.syncValueWidth) - 1).U(params.syncValueWidth.W)))
    e.sent := VecInit(hasNeighbor.map(!_))
    e
  }

  // Handle RX state machine. A packet has sync id, low value byte, high value
  // byte. Entry update happens when the high byte arrives.
  for (dir <- 0 until SyncDirection.count) {
    when (io.portIn(dir).valid && hasNeighbor(dir)) {
      when (!rxHasByte0(dir)) {
        rxByte0(dir) := io.portIn(dir).bits(7, 0)
        rxIncludeActiveMask(dir) := io.portIn(dir).bits(syncHeaderModeBit)
        rxHasByte0(dir) := true.B
      }.elsewhen (!rxHasByte1(dir)) {
        rxByte1(dir) := io.portIn(dir).bits(7, 0)
        rxHasByte1(dir) := true.B
      }.otherwise {
        rxHasByte0(dir) := false.B
        rxHasByte1(dir) := false.B
      }
    }
  }

  // Compute RX active signals and indices
  val rxIdx = Wire(Vec(SyncDirection.count, UInt(idxWidth)))
  val rxValue = Wire(Vec(SyncDirection.count, params.syncValue()))
  val rxActive = Wire(Vec(SyncDirection.count, Bool()))

  for (dir <- 0 until SyncDirection.count) {
    rxIdx(dir) := rxByte0(dir)(syncHeaderIdentMsb, syncHeaderIdentLsb)
    rxValue(dir) := Cat(io.portIn(dir).bits(7, 0), rxByte1(dir))
    rxActive(dir) := io.portIn(dir).valid && hasNeighbor(dir) && rxHasByte0(dir) && rxHasByte1(dir)
  }

  // Local event signals
  val localIdx = Wire(UInt(idxWidth))
  localIdx := io.localEvent.bits.syncIdent(idxWidth.get - 1, 0)
  val localActive = Wire(Bool())
  localActive := io.localEvent.valid

  // Process each entry through a chain of stages:
  // reg -> after_dir[0] -> after_dir[1] -> ... -> after_dir[7] -> after_local -> next
  for (entryIdx <- 0 until maxConcurrentSyncs) {
    val entryIdxU = entryIdx.U(idxWidth)

    // Start with current register value
    val stages = Wire(Vec(SyncDirection.count + 2, new SyncEntry(params)))  // +2 for initial and after-local
    stages(0) := entries(entryIdx)

    // Process each direction
    for (dir <- 0 until SyncDirection.count) {
      val prev = stages(dir)
      val next = Wire(new SyncEntry(params))

      val thisRxActive = Wire(Bool())
      thisRxActive := rxActive(dir) && rxIdx(dir) === entryIdxU

      // If this RX targets this entry
      when (thisRxActive) {
        // Initialize if not valid
        when (!prev.valid) {
          next := freshEntry()
        }.otherwise {
          next := prev
        }
        next.includeActiveMask := rxIncludeActiveMask(dir)
        // Update direction-specific synced flag and value
        dir match {
          case N  => next.columnSynced(0) := true.B; next.columnValues(0) := rxValue(dir)
          case S  => next.columnSynced(1) := true.B; next.columnValues(1) := rxValue(dir)
          case E  => next.rowSynced(0) := true.B; next.rowValues(0) := rxValue(dir)
          case W  => next.rowSynced(1) := true.B; next.rowValues(1) := rxValue(dir)
          case NE => next.quadrantSynced(0) := true.B; next.quadrantValues(0) := rxValue(dir)
          case NW => next.quadrantSynced(1) := true.B; next.quadrantValues(1) := rxValue(dir)
          case SE => next.quadrantSynced(2) := true.B; next.quadrantValues(2) := rxValue(dir)
          case SW => next.quadrantSynced(3) := true.B; next.quadrantValues(3) := rxValue(dir)
        }
      }.otherwise {
        next := prev
      }
      stages(dir + 1) := next
    }

    // Process local event and delayed local trigger (last stage, so local
    // events have priority over received packets for the target entry).
    val afterDirs = stages(SyncDirection.count)
    val afterLocal = Wire(new SyncEntry(params))

    val thisLocalActive = Wire(Bool())
    thisLocalActive := localActive && localIdx === entryIdxU
    val localDrainBlocked = io.localEvent.bits.mustDrainValid &&
      entries(io.localEvent.bits.mustDrainSyncIdent).valid
    val pendingDrainBlocked = afterDirs.pendingLocal &&
      entries(afterDirs.pendingMustDrainSyncIdent).valid
    val activeMaskAtTrigger = VecInit(entries.map(_.valid)).asUInt |
      Mux(thisLocalActive, UIntToOH(localIdx, maxConcurrentSyncs), 0.U(maxConcurrentSyncs.W))

    when (thisLocalActive) {
      when (!afterDirs.valid) {
        afterLocal := freshEntry()
      }.otherwise {
        afterLocal := afterDirs
      }
      afterLocal.includeActiveMask := io.localEvent.bits.includeActiveMask
      afterLocal.localValue := io.localEvent.bits.value
      afterLocal.pendingLocal := localDrainBlocked
      afterLocal.pendingMustDrainSyncIdent := io.localEvent.bits.mustDrainSyncIdent
      afterLocal.localSeen := !localDrainBlocked
      when (!localDrainBlocked && io.localEvent.bits.includeActiveMask) {
        afterLocal.localValue := Cat(
          io.localEvent.bits.value(params.syncValueWidth - 1, maxConcurrentSyncs),
          activeMaskAtTrigger)
      }
    }.elsewhen (afterDirs.pendingLocal && !pendingDrainBlocked) {
      afterLocal := afterDirs
      afterLocal.localSeen := true.B
      afterLocal.pendingLocal := false.B
      when (afterDirs.includeActiveMask) {
        afterLocal.localValue := Cat(
          afterDirs.localValue(params.syncValueWidth - 1, maxConcurrentSyncs),
          activeMaskAtTrigger)
      }
    }.otherwise {
      afterLocal := afterDirs
    }

    stages(SyncDirection.count + 1) := afterLocal

    // Write final state to register
    entries(entryIdx) := stages(SyncDirection.count + 1)
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

  def aggregateValues(e: SyncEntry, values: Vec[UInt]): UInt = {
    val maskWidth = params.maxConcurrentSyncs
    val minDistance = values.map(_(params.syncValueWidth - 1, maskWidth)).reduce(_ min _)
    val neutralValue = ((BigInt(1) << params.syncValueWidth) - 1).U(params.syncValueWidth.W)
    val activeMask = values.map { value =>
      Mux(value === neutralValue, 0.U(maskWidth.W), value(maskWidth - 1, 0))
    }.reduce(_ | _)
    Mux(e.includeActiveMask, Cat(minDistance, activeMask), values.reduceTree(_ min _))
  }

  def neutralSyncValue(e: SyncEntry): UInt = {
    val maskWidth = params.maxConcurrentSyncs
    val maxDistance = ((BigInt(1) << (params.syncValueWidth - maskWidth)) - 1)
      .U((params.syncValueWidth - maskWidth).W)
    Mux(e.includeActiveMask,
      Cat(maxDistance, 0.U(maskWidth.W)),
      ((BigInt(1) << params.syncValueWidth) - 1).U(params.syncValueWidth.W))
  }

  def valueForDirection(e: SyncEntry, dir: Int): UInt = {
    val values = Wire(Vec(4, params.syncValue()))
    values(0) := e.localValue
    val neutral = neutralSyncValue(e)

    dir match {
      case N =>
        values(1) := e.columnValues(1)
        values(2) := neutral
        values(3) := neutral
      case S =>
        values(1) := e.columnValues(0)
        values(2) := neutral
        values(3) := neutral
      case E =>
        values(1) := e.rowValues(1)
        values(2) := neutral
        values(3) := neutral
      case W =>
        values(1) := e.rowValues(0)
        values(2) := neutral
        values(3) := neutral
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

    aggregateValues(e, values)
  }

  val portOutInternal = Wire(Vec(SyncDirection.count, new SyncPort))

  for (dir <- 0 until SyncDirection.count) {
    portOutInternal(dir).valid := false.B
    portOutInternal(dir).bits := 0.U

    when (txActive(dir)) {
      val idx = txSyncIdx(dir)
      val e = entries(idx)
      portOutInternal(dir).valid := true.B

      when (txByteIdx(dir) === 0.U) {
        // Byte 0: syncIdent (which equals the index) plus aggregation mode.
        val txHeader = Wire(UInt(8.W))
        txHeader := Cat(0.U(4.W), e.includeActiveMask, idx)
        portOutInternal(dir).bits := Cat(0.U(1.W), txHeader)
        txByteIdx(dir) := 1.U
      }.elsewhen (txByteIdx(dir) === 1.U) {
        val minVal = valueForDirection(e, dir)
        portOutInternal(dir).bits := Cat(0.U(1.W), minVal(7, 0))
        txByteIdx(dir) := 2.U
      }.otherwise {
        val minVal = valueForDirection(e, dir)
        portOutInternal(dir).bits := Cat(1.U(1.W), minVal(15, 8))
        txActive(dir) := false.B
        entries(idx).sent(dir) := true.B
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

  if (syncParams.portOutOutputReg) {
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
    val syncIdent = UInt(params.syncIdentWidth.W)
    val includeActiveMask = Bool()
    val values = Vec(9, params.syncValue())
  }

  val preMin = Wire(Valid(new PreMinBundle))
  preMin.valid := anyComplete
  preMin.bits.syncIdent := completeIdx  // syncIdent equals the index
  val e = entries(completeIdx)
  preMin.bits.includeActiveMask := e.includeActiveMask
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
  val preMinBuffered = ValidBuffer(preMin, syncParams.minPipelineReg)

  // Compute MIN and produce result
  val resultInternal = Wire(Valid(new SyncEvent(params)))
  resultInternal.valid := preMinBuffered.valid
  resultInternal.bits.syncIdent := preMinBuffered.bits.syncIdent
  resultInternal.bits.includeActiveMask := preMinBuffered.bits.includeActiveMask
  resultInternal.bits.mustDrainValid := false.B
  resultInternal.bits.mustDrainSyncIdent := 0.U
  val preMinEntry = Wire(new SyncEntry(params))
  preMinEntry := 0.U.asTypeOf(new SyncEntry(params))
  preMinEntry.includeActiveMask := preMinBuffered.bits.includeActiveMask
  resultInternal.bits.value := aggregateValues(preMinEntry, preMinBuffered.bits.values)

  io.result := ValidBuffer(resultInternal, syncParams.resultOutputReg)
}

object SynchronizerGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <outputDir> <configFile>")
      System.exit(1)
    }
    val testParams = SynchronizerTestParams.fromFile(args(0))
    new Synchronizer(testParams.neighbors,
      ZamletParams(syncIdentWidth = testParams.syncIdentWidth,
                   synchronizerParams = testParams.sync))
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
