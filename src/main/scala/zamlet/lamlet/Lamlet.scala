package zamlet.lamlet

import chisel3._
import chisel3.util._
import zamlet.LamletParams
import zamlet.kamlet.{Synchronizer, SyncNeighbors, SyncPort, SyncDirection}
import zamlet.jamlet.NetworkWord

/**
 * Lamlet top module - wires together IssueUnit, IdentTracker, DispatchQueue, and Synchronizer.
 *
 * External interfaces:
 * - ex: Instruction input from scalar core
 * - tlbReq/tlbResp: TLB interface
 * - com: Completion signals to scalar core
 * - mesh: Packet output to mesh network
 * - syncPortS: Sync network port (south, to kamlet 0,0)
 * - backendBusy: Status signal
 * - kill: Kill signal from scalar core
 */
class Lamlet(params: LamletParams) extends Module {
  val io = IO(new Bundle {
    // Scalar core interface
    val ex = Flipped(Decoupled(new IssueUnitExData))
    val tlbReq = Decoupled(new IssueUnitTlbReq)
    val tlbResp = Input(new IssueUnitTlbResp)
    val com = Output(new IssueUnitCom)
    val kill = Input(Bool())

    // Status
    val backendBusy = Output(Bool())

    // Mesh network output
    val mesh = Decoupled(new NetworkWord(params))

    // Sync network (only S port used - lamlet at 0,-1 connects S to kamlet 0,0)
    val syncPortSOut = Output(new SyncPort)
    val syncPortSIn = Input(new SyncPort)
  })

  // Submodules
  val issueUnit = Module(new IssueUnit(params))
  val identTracker = Module(new IdentTracker(params))
  val dispatchQueue = Module(new DispatchQueue(params))

  // Lamlet only connects south to kamlet (0,0)
  val syncNeighbors = SyncNeighbors(
    hasN = false, hasS = true, hasE = false, hasW = false,
    hasNE = false, hasNW = false, hasSE = false, hasSW = false
  )
  val synchronizer = Module(new Synchronizer(syncNeighbors, params.synchronizerParams))

  // External interface → IssueUnit
  issueUnit.io.ex <> io.ex
  issueUnit.io.tlbReq <> io.tlbReq
  issueUnit.io.tlbResp := io.tlbResp
  io.com := issueUnit.io.com
  issueUnit.io.kill := io.kill

  // IssueUnit → IdentTracker
  identTracker.io.in <> issueUnit.io.toIdentTracker

  // IdentTracker → DispatchQueue
  dispatchQueue.io.in <> identTracker.io.out

  // DispatchQueue → Mesh
  io.mesh <> dispatchQueue.io.out

  // IdentTracker ↔ Synchronizer
  synchronizer.io.localEvent := identTracker.io.syncLocalEvent
  identTracker.io.syncResult := synchronizer.io.result

  // Synchronizer sync network (only S port connected)
  io.syncPortSOut := synchronizer.io.portOut(SyncDirection.S)
  synchronizer.io.portIn(SyncDirection.S) := io.syncPortSIn

  // Tie off unused sync ports
  for (dir <- 0 until SyncDirection.count if dir != SyncDirection.S) {
    synchronizer.io.portIn(dir).valid := false.B
    synchronizer.io.portIn(dir).bits := 0.U
  }

  // Status
  io.backendBusy := identTracker.io.backendBusy
}

object LamletGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <configFile>")
      System.exit(1)
    }
    val params = LamletParams.fromFile(args(0))
    new Lamlet(params)
  }
}

object LamletMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  LamletGenerator.generate(outputDir, Seq(configFile))
}
