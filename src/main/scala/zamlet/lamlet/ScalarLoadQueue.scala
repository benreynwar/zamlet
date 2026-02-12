package zamlet.lamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.{KInstr, KInstrOpcode, LoadImmInstr}

/**
 * TileLink-style Get request (simplified, no diplomacy).
 */
class TileLinkGetReq(addrWidth: Int) extends Bundle {
  val address = UInt(addrWidth.W)
  val size = UInt(3.W)    // log2(bytes)
  val source = UInt(8.W)  // Transaction ID
}

/**
 * TileLink-style Get response (simplified, no diplomacy).
 */
class TileLinkGetResp(dataWidth: Int) extends Bundle {
  val data = UInt(dataWidth.W)
  val source = UInt(8.W)  // Transaction ID
  val error = Bool()
}

/**
 * TileLink-style Put request (simplified, no diplomacy).
 */
class TileLinkPutReq(addrWidth: Int, dataWidth: Int) extends Bundle {
  val address = UInt(addrWidth.W)
  val data = UInt(dataWidth.W)
  val size = UInt(3.W)    // log2(bytes)
  val source = UInt(8.W)  // Transaction ID
  val mask = UInt((dataWidth / 8).W)  // Byte mask
}

/**
 * TileLink-style Put response (simplified, no diplomacy).
 */
class TileLinkPutResp extends Bundle {
  val source = UInt(8.W)  // Transaction ID
  val error = Bool()
}

/**
 * Scalar memory load request from IssueUnit.
 *
 * For Phase 2 (ew=64 only): each element is one 8-byte word.
 */
class ScalarLoadReq(params: ZamletParams) extends Bundle {
  val paddr = UInt(params.memAddrWidth.W)   // Physical base address
  val vd = params.rfAddr()                   // Destination register
  val startIndex = params.elementIndex()     // First element index
  val nElements = UInt(16.W)                 // Number of elements to load
  val instrIdent = UInt(params.identWidth.W) // Instruction identifier (for tracking)
}

/**
 * ScalarLoadQueue issues TileLink reads to scalar memory, generates LoadImm kinstrs.
 *
 * Phase 2 simplifications:
 * - ew=64 only (one element = one 8-byte word)
 * - Single load at a time (no pipelining)
 * - One TileLink Get per word
 * - Two LoadImm kinstrs per word (lower and upper 32 bits)
 *
 * Flow:
 * 1. Receive request with paddr, vd, startIndex, nElements
 * 2. For each element:
 *    a. Issue TileLink Get for 8-byte word
 *    b. Generate 2 LoadImm kinstrs with embedded data
 *    c. Send kinstrs to dispatch
 * 3. Signal load_complete when done
 */
class ScalarLoadQueue(params: ZamletParams) extends Module {
  val io = IO(new Bundle {
    // Request input
    val req = Flipped(Decoupled(new ScalarLoadReq(params)))

    // TileLink interface (simplified)
    val tlA = Decoupled(new TileLinkGetReq(params.memAddrWidth))
    val tlD = Flipped(Decoupled(new TileLinkGetResp(params.wordWidth)))

    // Kinstr output to DispatchQueue
    val kinstrOut = Decoupled(new KinstrWithTarget(params))

    // Completion signal
    val loadComplete = Valid(UInt(params.identWidth.W))

    // Status
    val busy = Output(Bool())
  })

  // State machine
  object State extends ChiselEnum {
    val Idle, IssueGet, WaitResp, SendKinstrLo, SendKinstrHi = Value
  }
  import State._

  val state = RegInit(Idle)

  // Request registers
  val paddr = Reg(UInt(params.memAddrWidth.W))
  val vd = Reg(params.rfAddr())
  val startIndex = Reg(params.elementIndex())
  val nElements = Reg(UInt(16.W))
  val instrIdent = Reg(UInt(params.identWidth.W))

  // Progress tracking
  val currentElement = RegInit(0.U(16.W))

  // Response data register
  val respData = Reg(UInt(params.wordWidth.W))

  // Compute target jamlet for current element
  val elementIndex = startIndex + currentElement
  val jamletIndex = elementIndex(log2Ceil(params.jInL) - 1, 0)  // element_index % jInL
  val kIndex = jamletIndex / params.jInK.U                       // kamlet index
  val jInKIndex = jamletIndex % params.jInK.U                    // jamlet within kamlet
  val rfWordOffset = elementIndex / params.jInL.U                // word offset from vd
  val rfAddr = vd + rfWordOffset(params.rfAddrWidth - 1, 0)

  // Compute address for current element (8 bytes per element for ew=64)
  val currentAddr = paddr + (currentElement << 3.U)

  // Default outputs
  io.req.ready := false.B
  io.tlA.valid := false.B
  io.tlA.bits := DontCare
  io.tlD.ready := false.B
  io.kinstrOut.valid := false.B
  io.kinstrOut.bits := DontCare
  io.loadComplete.valid := false.B
  io.loadComplete.bits := instrIdent
  io.busy := (state =/= Idle)

  // Build LoadImm kinstr
  def makeLoadImmKinstr(jInK: UInt, rfAddr: UInt, section: UInt, data: UInt): UInt = {
    val instr = Wire(new LoadImmInstr(params))
    instr.opcode := KInstrOpcode.LoadImm
    instr.jInKIndex := jInK
    instr.rfAddr := rfAddr
    instr.section := section
    instr.byteMask := 0xF.U  // All 4 bytes of section
    instr.data := data
    instr.reserved := 0.U
    instr.asUInt
  }

  switch(state) {
    is(Idle) {
      io.req.ready := true.B
      when(io.req.fire) {
        paddr := io.req.bits.paddr
        vd := io.req.bits.vd
        startIndex := io.req.bits.startIndex
        nElements := io.req.bits.nElements
        instrIdent := io.req.bits.instrIdent
        currentElement := 0.U
        state := IssueGet
      }
    }

    is(IssueGet) {
      io.tlA.valid := true.B
      io.tlA.bits.address := currentAddr
      io.tlA.bits.size := 3.U  // 8 bytes
      io.tlA.bits.source := 0.U  // Single in-flight for Phase 2

      when(io.tlA.fire) {
        state := WaitResp
      }
    }

    is(WaitResp) {
      io.tlD.ready := true.B

      when(io.tlD.fire) {
        respData := io.tlD.bits.data
        state := SendKinstrLo
      }
    }

    is(SendKinstrLo) {
      io.kinstrOut.valid := true.B
      io.kinstrOut.bits.kinstr := makeLoadImmKinstr(
        jInKIndex, rfAddr, 0.U, respData(31, 0))
      io.kinstrOut.bits.kIndex := kIndex
      io.kinstrOut.bits.isBroadcast := false.B

      when(io.kinstrOut.fire) {
        state := SendKinstrHi
      }
    }

    is(SendKinstrHi) {
      io.kinstrOut.valid := true.B
      io.kinstrOut.bits.kinstr := makeLoadImmKinstr(
        jInKIndex, rfAddr, 1.U, respData(63, 32))
      io.kinstrOut.bits.kIndex := kIndex
      io.kinstrOut.bits.isBroadcast := false.B

      when(io.kinstrOut.fire) {
        currentElement := currentElement + 1.U

        when(currentElement + 1.U >= nElements) {
          // Done with all elements
          io.loadComplete.valid := true.B
          state := Idle
        } .otherwise {
          // More elements to process
          state := IssueGet
        }
      }
    }
  }
}

object ScalarLoadQueueGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <configFile>")
      System.exit(1)
    }
    val params = ZamletParams.fromFile(args(0))
    new ScalarLoadQueue(params)
  }
}

object ScalarLoadQueueMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  ScalarLoadQueueGenerator.generate(outputDir, Seq(configFile))
}
