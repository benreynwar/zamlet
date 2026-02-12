package zamlet.lamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.{NetworkWord, PacketHeader, WriteMemWordHeader, MessageType}

/**
 * VpuToScalarMem handles WriteMemWord messages from kamlets, converts to TileLink writes.
 *
 * WriteMemWord packet format:
 * - Word 0: WriteMemWordHeader (target, source, messageType, ident, tag, dstByteInWord, nBytes)
 * - Word 1: Physical address
 * - Word 2: Data
 *
 * For Phase 2 (ew=64, single store at a time):
 * - Each WriteMemWord is one 8-byte word
 * - Track completion by counting words received vs expected
 *
 * Flow:
 * 1. Receive WriteMemWord packet from mesh
 * 2. Parse header, address, data
 * 3. Issue TileLink Put
 * 4. When all elements complete, signal storeComplete
 */
class VpuToScalarMem(params: ZamletParams) extends Module {
  val io = IO(new Bundle {
    // WriteMemWord packets from mesh (from kamlets)
    val meshIn = Flipped(Decoupled(new NetworkWord(params)))

    // TileLink Put interface
    val tlPutReq = Decoupled(new TileLinkPutReq(params.memAddrWidth, params.wordWidth))
    val tlPutResp = Flipped(Decoupled(new TileLinkPutResp))

    // Store completion signal (to IssueUnit)
    val storeComplete = Valid(UInt(params.identWidth.W))

    // Expected word count for current store (from IssueUnit, set when store dispatched)
    val storeWordCount = Flipped(Valid(new Bundle {
      val ident = UInt(params.identWidth.W)
      val nWords = UInt(16.W)
    }))

    // Status
    val busy = Output(Bool())
  })

  // State machine
  object State extends ChiselEnum {
    val Idle, ReceiveAddr, ReceiveData, IssuePut, WaitPutResp = Value
  }
  import State._

  val state = RegInit(Idle)

  // Current packet registers
  val header = Reg(new WriteMemWordHeader(params))
  val paddr = Reg(UInt(params.memAddrWidth.W))
  val data = Reg(UInt(params.wordWidth.W))

  // Completion tracking
  val activeIdent = Reg(UInt(params.identWidth.W))
  val expectedWords = Reg(UInt(16.W))
  val completedWords = RegInit(0.U(16.W))
  val trackingActive = RegInit(false.B)

  // Capture expected word count when store starts
  when(io.storeWordCount.valid && !trackingActive) {
    activeIdent := io.storeWordCount.bits.ident
    expectedWords := io.storeWordCount.bits.nWords
    completedWords := 0.U
    trackingActive := true.B
  }

  // Default outputs
  io.meshIn.ready := false.B
  io.tlPutReq.valid := false.B
  io.tlPutReq.bits.address := paddr
  io.tlPutReq.bits.data := data
  io.tlPutReq.bits.size := 3.U  // 8 bytes
  io.tlPutReq.bits.source := 0.U
  io.tlPutReq.bits.mask := 0xFF.U  // All bytes
  io.tlPutResp.ready := false.B
  io.storeComplete.valid := false.B
  io.storeComplete.bits := activeIdent
  io.busy := (state =/= Idle) || trackingActive

  switch(state) {
    is(Idle) {
      io.meshIn.ready := true.B
      when(io.meshIn.fire && io.meshIn.bits.isHeader) {
        val hdr = io.meshIn.bits.data.asTypeOf(new WriteMemWordHeader(params))
        when(hdr.messageType === MessageType.WriteMemWordReq) {
          header := hdr
          state := ReceiveAddr
        }
      }
    }

    is(ReceiveAddr) {
      io.meshIn.ready := true.B
      when(io.meshIn.fire) {
        paddr := io.meshIn.bits.data
        state := ReceiveData
      }
    }

    is(ReceiveData) {
      io.meshIn.ready := true.B
      when(io.meshIn.fire) {
        data := io.meshIn.bits.data
        state := IssuePut
      }
    }

    is(IssuePut) {
      io.tlPutReq.valid := true.B
      when(io.tlPutReq.ready) {
        state := WaitPutResp
      }
    }

    is(WaitPutResp) {
      io.tlPutResp.ready := true.B
      when(io.tlPutResp.fire) {
        // Increment completion counter
        when(trackingActive) {
          completedWords := completedWords + 1.U
        }
        state := Idle
      }
    }
  }

  // Check for store completion
  when(trackingActive && completedWords === expectedWords && expectedWords > 0.U) {
    io.storeComplete.valid := true.B
    trackingActive := false.B
    completedWords := 0.U
  }
}

object VpuToScalarMemGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <configFile>")
      System.exit(1)
    }
    val params = ZamletParams.fromFile(args(0))
    new VpuToScalarMem(params)
  }
}

object VpuToScalarMemMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  val outputDir = args(0)
  val configFile = args(1)
  VpuToScalarMemGenerator.generate(outputDir, Seq(configFile))
}
