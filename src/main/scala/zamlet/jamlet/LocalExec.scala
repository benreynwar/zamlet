package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.LamletParams

/**
 * LocalExec handles immediate kinstr execution (LoadImm, StoreScalar, etc.)
 *
 * These are kinstrs that can be executed immediately without waiting for cache
 * or protocol coordination. The kamlet sends them directly to the target jamlet.
 *
 * StoreScalar flow:
 * 1. Compute vwIndex from coordinates
 * 2. Check if this jamlet has an active element (in range)
 * 3. Read RF word
 * 4. Build WriteMemWord packet (header + paddr + data)
 * 5. Send packet to Lamlet
 */
class LocalExec(params: LamletParams) extends Module {
  val io = IO(new Bundle {
    // Jamlet position
    val thisX = Input(params.xPos())
    val thisY = Input(params.yPos())

    // Immediate kinstr input (from kamlet via Jamlet)
    val kinstrIn = Flipped(Valid(new KinstrWithParams(params)))

    // RfSlice read/write port
    val rfReq = Decoupled(new RfReq(params))
    val rfResp = Flipped(Decoupled(new RfResp(params)))

    // Packet output (to network, for WriteMemWord)
    val packetOut = Decoupled(new NetworkWord(params))

    // Store completion signal (to kamlet, for ident tracking)
    val storeComplete = Valid(UInt(params.identWidth.W))
  })

  // State machine for StoreScalar
  object State extends ChiselEnum {
    val Idle, ReadRF, WaitRfResp, SendHeader, SendPaddr, SendData = Value
  }
  import State._

  val state = RegInit(Idle)

  // Registers for StoreScalar execution
  val savedInstr = Reg(new StoreScalarInstr(params))
  val savedBasePaddr = Reg(UInt(params.memAddrWidth.W))
  val savedRfData = Reg(UInt(params.wordWidth.W))
  val savedVwIndex = Reg(UInt(log2Ceil(params.jInL).W))
  val savedIdent = Reg(UInt(params.identWidth.W))

  // Compute vwIndex from coordinates (standard word order)
  val vwIndex = io.thisY * params.jTotalCols.U + io.thisX

  // Decode the kinstr
  val base = io.kinstrIn.bits.kinstr.asTypeOf(new KInstrBase)
  val isLoadImm = io.kinstrIn.valid && base.opcode === KInstrOpcode.LoadImm && state === Idle
  val isStoreScalar = io.kinstrIn.valid && base.opcode === KInstrOpcode.StoreScalar && state === Idle

  // StoreScalar decode
  val storeInstr = io.kinstrIn.bits.kinstr.asTypeOf(new StoreScalarInstr(params))
  val basePaddr = io.kinstrIn.bits.param0

  // Check if this jamlet participates in the store
  val elementActive = (vwIndex >= storeInstr.startIndex) &&
                      (vwIndex < (storeInstr.startIndex + storeInstr.nElements))

  // Compute physical address for this element
  val relativeIndex = vwIndex - storeInstr.startIndex
  val paddr = basePaddr + (relativeIndex << 3)  // * 8 bytes per element

  // Lamlet position (y = -1 as unsigned = 0xFF for 8-bit coordinates)
  val lamletX = 0.U(params.xPosWidth.W)
  val lamletY = ((1 << params.yPosWidth) - 1).U(params.yPosWidth.W)

  // Build WriteMemWordHeader
  val header = Wire(new WriteMemWordHeader(params))
  header.targetX := lamletX
  header.targetY := lamletY
  header.sourceX := io.thisX
  header.sourceY := io.thisY
  header.length := 3.U  // header + paddr + data
  header.messageType := MessageType.WriteMemWordReq
  header.sendType := SendType.Single
  header.ident := savedIdent
  header.tag := 0.U  // No tag needed for scalar stores
  header.dstByteInWord := 0.U  // Full word aligned
  header.nBytes := 8.U  // Full 8-byte word

  // Default outputs
  io.rfReq.valid := false.B
  io.rfReq.bits := DontCare
  io.rfResp.ready := false.B
  io.packetOut.valid := false.B
  io.packetOut.bits.data := 0.U
  io.packetOut.bits.isHeader := false.B
  io.storeComplete.valid := false.B
  io.storeComplete.bits := savedIdent

  switch(state) {
    is(Idle) {
      io.rfResp.ready := true.B

      when(isLoadImm) {
        val instr = io.kinstrIn.bits.kinstr.asTypeOf(new LoadImmInstr(params))

        // Compute full 64-bit write data from 32-bit section
        val sectionShift = instr.section * 32.U
        val fullWriteData = instr.data << sectionShift

        io.rfReq.valid := true.B
        io.rfReq.bits.addr := instr.rfAddr
        io.rfReq.bits.isWrite := true.B
        io.rfReq.bits.writeData := fullWriteData
      }

      when(isStoreScalar && elementActive) {
        // Save instruction state
        savedInstr := storeInstr
        savedBasePaddr := basePaddr
        savedVwIndex := vwIndex
        savedIdent := 0.U  // TODO: extract ident from kinstr or witemInfo

        state := ReadRF
      }
    }

    is(ReadRF) {
      io.rfReq.valid := true.B
      io.rfReq.bits.addr := savedInstr.dataReg
      io.rfReq.bits.isWrite := false.B
      io.rfReq.bits.writeData := 0.U

      when(io.rfReq.ready) {
        state := WaitRfResp
      }
    }

    is(WaitRfResp) {
      io.rfResp.ready := true.B

      when(io.rfResp.valid) {
        savedRfData := io.rfResp.bits.readData
        state := SendHeader
      }
    }

    is(SendHeader) {
      io.packetOut.valid := true.B
      io.packetOut.bits.data := header.asUInt
      io.packetOut.bits.isHeader := true.B

      when(io.packetOut.ready) {
        state := SendPaddr
      }
    }

    is(SendPaddr) {
      // Compute paddr using saved values
      val storedRelIndex = savedVwIndex - savedInstr.startIndex
      val storedPaddr = savedBasePaddr + (storedRelIndex << 3)

      io.packetOut.valid := true.B
      io.packetOut.bits.data := storedPaddr
      io.packetOut.bits.isHeader := false.B

      when(io.packetOut.ready) {
        state := SendData
      }
    }

    is(SendData) {
      io.packetOut.valid := true.B
      io.packetOut.bits.data := savedRfData
      io.packetOut.bits.isHeader := false.B

      when(io.packetOut.ready) {
        io.storeComplete.valid := true.B
        state := Idle
      }
    }
  }
}

/** Generator for LocalExec module */
object LocalExecGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> LocalExec <lamletParamsFileName>")
      null
    } else {
      val params = LamletParams.fromFile(args(0))
      new LocalExec(params)
    }
  }
}

object LocalExecMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  LocalExecGenerator.generate(args(0), Seq(args(1)))
}
