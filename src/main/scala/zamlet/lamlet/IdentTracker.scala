package zamlet.lamlet

import chisel3._
import chisel3.util._
import zamlet.LamletParams
import zamlet.kamlet.SyncEvent
import zamlet.jamlet.{KInstrOpcode, IdentQueryInstr}
import zamlet.utils.DoubleBuffer

/**
 * Kinstr entry with target kamlet index.
 */
class KinstrWithTarget(params: LamletParams) extends Bundle {
  val kinstr = UInt(64.W)
  val kIndex = UInt(params.kIndexWidth.W)
  val isBroadcast = Bool()
}

/**
 * IdentTracker tracks instruction identifiers and per-kamlet tokens for flow control.
 *
 * This module is a stream processor that:
 * 1. Accepts kinstrs from IssueUnit with empty ident field
 * 2. Fills in the ident field from the allocator
 * 3. Can inject IdentQuery instructions into the output stream
 * 4. Tracks per-kamlet tokens for backpressure
 * 5. Reports backend_busy based on outstanding work
 *
 * IdentQuery flow:
 * - When idents or tokens run low, transitions to READY_TO_SEND
 * - Injects IdentQuery instruction into output stream (priority over regular kinstrs)
 * - Participates in sync network with local distance value
 * - When sync result arrives, updates oldest_active_ident and returns tokens
 */
class IdentTracker(params: LamletParams) extends Module {
  val io = IO(new Bundle {
    // Kinstr input (from IssueUnit, ident field empty)
    val in = Flipped(Decoupled(new KinstrWithTarget(params)))

    // Kinstr output (to DispatchQueue, ident field filled)
    val out = Decoupled(new KinstrWithTarget(params))

    // Sync network interface
    val syncLocalEvent = Valid(new SyncEvent)
    val syncResult = Flipped(Valid(new SyncEvent))

    // Status
    val backendBusy = Output(Bool())
  })

  // Output buffer to break combinatorial paths
  val outInternal = Wire(Decoupled(new KinstrWithTarget(params)))
  io.out <> DoubleBuffer(outInternal,
    params.identTrackerOutForwardBuffer, params.identTrackerOutBackwardBuffer)

  // IdentQuery state machine
  object IQState extends ChiselEnum {
    val Dormant, ReadyToSend, WaitingForResponse = Value
  }

  // Ident allocation
  val nextInstrIdent = RegInit(0.U(params.identWidth.W))
  val oldestActiveIdent = RegInit(0.U(params.identWidth.W))
  val oldestActiveValid = RegInit(false.B)
  val lastSentInstrIdent = RegInit((params.maxResponseTags - 2).U(params.identWidth.W))

  // Per-kamlet tokens
  val availableTokens = RegInit(VecInit(
    Seq.fill(params.kInL)(params.instructionQueueLength.U(8.W))))
  val tokensUsedSinceQuery = RegInit(VecInit(Seq.fill(params.kInL)(0.U(8.W))))
  val tokensInActiveQuery = RegInit(VecInit(Seq.fill(params.kInL)(0.U(8.W))))

  // IdentQuery state
  val iqState = RegInit(IQState.Dormant)
  val iqBaseline = Reg(UInt(params.identWidth.W))
  val iqLamletDist = Reg(UInt(8.W))

  // IdentQuery uses a dedicated ident (max_response_tags, outside normal range)
  val identQueryIdent = params.maxResponseTags.U(8.W)

  // Available idents calculation (modular arithmetic)
  val availableIdents = Wire(UInt(params.identWidth.W))
  when (oldestActiveValid) {
    // (oldest - next) mod max_tags - 1
    availableIdents := (oldestActiveIdent - nextInstrIdent)(params.identWidth - 1, 0) - 1.U
  } .otherwise {
    // No query response yet - how many we've used since start
    availableIdents := (params.maxResponseTags.U - nextInstrIdent - 1.U)
  }

  // Token availability check for input
  // Regular instructions need > 1 token (last reserved for IdentQuery)
  // Use conservative check (all kamlets have tokens) to avoid combinatorial path from in.bits to ready
  val haveTokensForInput = availableTokens.forall(_ > 1.U)

  // Should we send an IdentQuery?
  val identThreshold = (params.maxResponseTags / 2).U
  val tokenThreshold = (params.instructionQueueLength / 2).U
  val shouldSendQuery = (iqState === IQState.Dormant) && (
    (availableIdents < identThreshold) ||
    availableTokens.exists(_ < tokenThreshold)
  )

  // Output control
  val sendingIdentQuery = (iqState === IQState.ReadyToSend) && outInternal.ready
  val passingThrough = io.in.valid && !sendingIdentQuery

  // Input ready when: idents available, tokens available, output ready, not sending IdentQuery
  val canAcceptInput = (availableIdents >= 1.U) &&
                       haveTokensForInput &&
                       outInternal.ready &&
                       !sendingIdentQuery

  io.in.ready := canAcceptInput

  // Output valid when passing through input or sending IdentQuery
  outInternal.valid := passingThrough || sendingIdentQuery

  // Construct output kinstr
  when (sendingIdentQuery) {
    // Inject IdentQuery using proper Bundle format
    val identQueryInstr = Wire(new IdentQueryInstr)
    identQueryInstr.opcode := KInstrOpcode.IdentQuery
    identQueryInstr.baseline := iqBaseline
    identQueryInstr.syncIdent := identQueryIdent
    identQueryInstr.reserved := 0.U
    outInternal.bits.kinstr := identQueryInstr.asUInt
    outInternal.bits.kIndex := 0.U
    outInternal.bits.isBroadcast := true.B
  } .otherwise {
    // Pass through with ident filled in
    // Ident goes in bits [7:0] of kinstr
    val kinstrWithIdent = Cat(io.in.bits.kinstr(63, 8), nextInstrIdent)
    outInternal.bits.kinstr := kinstrWithIdent
    outInternal.bits.kIndex := io.in.bits.kIndex
    outInternal.bits.isBroadcast := io.in.bits.isBroadcast
  }

  // Update state on regular kinstr pass-through
  when (io.in.fire) {
    nextInstrIdent := (nextInstrIdent + 1.U)(params.identWidth - 1, 0)
    lastSentInstrIdent := nextInstrIdent

    // Use token for target kamlet(s)
    when (io.in.bits.isBroadcast) {
      for (k <- 0 until params.kInL) {
        availableTokens(k) := availableTokens(k) - 1.U
        tokensUsedSinceQuery(k) := tokensUsedSinceQuery(k) + 1.U
      }
    } .otherwise {
      val k = io.in.bits.kIndex
      availableTokens(k) := availableTokens(k) - 1.U
      tokensUsedSinceQuery(k) := tokensUsedSinceQuery(k) + 1.U
    }
  }

  // IdentQuery state machine transitions
  when (shouldSendQuery) {
    iqState := IQState.ReadyToSend
    iqBaseline := (nextInstrIdent - 1.U)(params.identWidth - 1, 0)
    // Lamlet's distance: conservative estimate using allocated - oldest
    iqLamletDist := Mux(oldestActiveValid,
      (nextInstrIdent - oldestActiveIdent)(params.identWidth - 1, 0),
      nextInstrIdent
    )
  }

  when (sendingIdentQuery) {
    // Move tokens to active query tracker
    for (k <- 0 until params.kInL) {
      tokensInActiveQuery(k) := tokensUsedSinceQuery(k) + 1.U  // +1 for IdentQuery itself
      tokensUsedSinceQuery(k) := 0.U
      availableTokens(k) := availableTokens(k) - 1.U  // IdentQuery uses a token
    }
    iqState := IQState.WaitingForResponse
  }

  // Sync local event (fires when sending IdentQuery)
  io.syncLocalEvent.valid := sendingIdentQuery
  io.syncLocalEvent.bits.syncIdent := identQueryIdent
  io.syncLocalEvent.bits.value := iqLamletDist

  // Handle IdentQuery response from sync network
  when (io.syncResult.valid && io.syncResult.bits.syncIdent === identQueryIdent) {
    val minDistance = io.syncResult.bits.value

    // Update oldest_active_ident
    when (minDistance === params.maxResponseTags.U) {
      // All idents free
      oldestActiveIdent := iqBaseline
    } .otherwise {
      oldestActiveIdent := (iqBaseline + minDistance)(params.identWidth - 1, 0)
    }
    oldestActiveValid := true.B

    // Return tokens from completed query
    for (k <- 0 until params.kInL) {
      availableTokens(k) := availableTokens(k) + tokensInActiveQuery(k)
    }

    iqState := IQState.Dormant
  }

  // Backend busy when any outstanding work
  io.backendBusy := (nextInstrIdent =/= oldestActiveIdent) || !oldestActiveValid
}

object IdentTrackerGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <configFile>")
      System.exit(1)
    }
    val params = LamletParams.fromFile(args(0))
    new IdentTracker(params)
  }
}

object IdentTrackerMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  IdentTrackerGenerator.generate(outputDir, Seq(configFile))
}
