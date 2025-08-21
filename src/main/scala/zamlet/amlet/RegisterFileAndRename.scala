package zamlet.amlet

import chisel3._
import chisel3.util._
import scala.math.max
import zamlet.utils.{DoubleBuffer, DecoupledBuffer, RFBuilderParams, RegisterFileBuilder, WriteAccessOut, ReadAccessOut, ResetStage, HasRoom, HasRoomForwardBuffer, ValidBuffer}


class LoopState(params: AmletParams) extends Bundle {
  val index = UInt(params.aWidth.W)
  val iterations = new ATaggedSource(params)
  // Whether we've reported the resolved loop iterations back to the 
  // bamlet control already.
  val reported = Bool()
}


class State(params: AmletParams) extends Bundle {
  val loopStates = Vec(params.nLoopLevels, new LoopState(params))
}


/**
 * Register File and Rename Unit - handles register file, renaming, and instruction dispatch
 * 
 * This module implements:
 * - Register file with rename tag-based dependency tracking
 * - Instruction dispatch to reservation stations
 * - Register dependency tracking and operand resolution
 */
class RegisterFileAndRename(params: AmletParams) extends Module {
  val regUtils = new RegUtils(params)

  val rfOutputLatency = if (params.rfParams.aoBuffer) 1 else 0
  val outputLatency: Int = rfOutputLatency
  
  val io = IO(new Bundle {

    val instr = Flipped(Decoupled(new VLIWInstr.Expanded(params)))

    // Write inputs from ALU, load/store, and packets
    // Result bus carries completed results back to register files for dependency resolution
    val resultBus = Input(new NamedResultBus(params))

    // Instruction outputs to reservation stations
    val aluInstr = HasRoom(new ALUInstr.Resolving(params), outputLatency)
    val aluliteInstr = HasRoom(new ALULiteInstr.Resolving(params), outputLatency)
    val aluPredicateInstr = HasRoom(new PredicateInstr.Resolving(params), outputLatency)
    val ldstInstr = HasRoom(new LoadStoreInstr.Resolving(params), outputLatency)
    val sendPacketInstr = HasRoom(new PacketInstr.SendResolving(params), outputLatency)
    val recvPacketInstr = HasRoom(new PacketInstr.ReceiveResolving(params), outputLatency)

    // Tells the Bamlet control how many iterations there are in a loop.
    val loopIterations = Output(Valid(UInt(params.aWidth.W)))
  })

  val resetBuffered = ResetStage(clock, reset)

  withReset(resetBuffered) {

    // The RFBuilder's are objects that let us create ports on register files
    // and once all the ports have been registers then we create the modules.

    val pRFBuilderParams = RFBuilderParams( 
      width=1,
      nRegs=params.nPRegs,
      nTags=params.nPTags,
      iaForwardBuffer=params.rfParams.iaForwardBuffer,
      iaBackwardBuffer=params.rfParams.iaBackwardBuffer,
      iaResultsBuffer=params.rfParams.iaResultsBuffer,
      aoBuffer=params.rfParams.aoBuffer,
      zeroValue=1
    )
    val pRFBuilder = RegisterFileBuilder(pRFBuilderParams)

    val aRFBuilderParams = RFBuilderParams( 
      width=params.aWidth,
      nRegs=params.nARegs,
      nTags=params.nATags,
      iaForwardBuffer=params.rfParams.iaForwardBuffer,
      iaBackwardBuffer=params.rfParams.iaBackwardBuffer,
      iaResultsBuffer=params.rfParams.iaResultsBuffer,
      aoBuffer=params.rfParams.aoBuffer,
      zeroValue=0
    )
    val aRFBuilder = RegisterFileBuilder(aRFBuilderParams)

    val dRFBuilderParams = RFBuilderParams( 
      width=params.width,
      nRegs=params.nDRegs,
      nTags=params.nDTags,
      iaForwardBuffer=params.rfParams.iaForwardBuffer,
      iaBackwardBuffer=params.rfParams.iaBackwardBuffer,
      iaResultsBuffer=params.rfParams.iaResultsBuffer,
      aoBuffer=params.rfParams.aoBuffer,
      zeroValue=0
    )
    val dRFBuilder = RegisterFileBuilder(dRFBuilderParams)

    val stalled = Wire(Bool())

    // Create instruction pipeline buffers (moved early for use in control logic)
    // Pipeline stages: iInstr -> [input buffer] -> aInstr -> [register file reads/writes] -> [output buffer] -> oInstr
    // - iInstr: Instruction going into input buffer
    // - aInstr: Instruction coming out of input buffer, goes through register file reads/writes
    // - oInstr: Instruction coming out of output buffer
    val iInstr = Wire(Decoupled(new VLIWInstr.Expanded(params)))
    val aInstr = DoubleBuffer(iInstr, params.rfParams.iaForwardBuffer, params.rfParams.iaBackwardBuffer)
    val aInstrHR = Wire(HasRoom(new VLIWInstr.Expanded(params)))
    aInstrHR.valid := aInstr.valid && !stalled && aInstrHR.hasRoom
    aInstrHR.bits := aInstr.bits
    aInstr.ready := !stalled && aInstrHR.hasRoom
    val oInstr = HasRoomForwardBuffer(aInstrHR, params.rfParams.aoBuffer)

    // State management: tracks loop indices and iteration counts
    // Uses stateNext/state pattern: stateNext is computed combinationally, 
    // state holds the registered version from the previous cycle
    val stateInitial = Wire(new State(params))
    for (i <- 0 until params.nLoopLevels) {
      stateInitial.loopStates(i).index := 0.U
      stateInitial.loopStates(i).iterations.resolved := false.B
      stateInitial.loopStates(i).iterations.value := 0.U
      stateInitial.loopStates(i).iterations.addr := 0.U
      stateInitial.loopStates(i).iterations.tag := 0.U
      stateInitial.loopStates(i).reported := true.B // Default to true so we don't report loop levels that aren't used.
    }
    val stateNext = Wire(new State(params))
    val state = RegNext(stateNext, stateInitial)
    
    // Output valid when all register files have valid output and instruction pipeline has valid output
    val outputValid = Wire(Bool())
    
    // For register 0 (packet output), always increment - order matters for packet assembly
    // For other registers, find first available write identifier

    // Initialize stateNext with current state by default
    stateNext := state
    
    // 1) Control
    // --------------

    //val mode = Modes()
    //val iterations = new ExtendedSrcType(params) // Where the number of iterations comes from.
    //val dst = params.aReg()                      // Where the loop index goes.
    //val level = UInt(log2Ceil(params.nLoopLevels).W)

    val aControlIterationsRead = aRFBuilder.makeReadPort()
    aControlIterationsRead.input.valid := io.instr.valid && io.instr.bits.control.mode === ControlInstr.Modes.LoopLocal
    aControlIterationsRead.input.bits := io.instr.bits.control.iterations.addr

    val aControlLoopIndexWrite = aRFBuilder.makeWritePort()
    // The write is just a fake since the result is forced.
    aControlLoopIndexWrite.input.valid := io.instr.valid && ControlInstr.modeWrites(io.instr.bits.control.mode)
    aControlLoopIndexWrite.input.bits := io.instr.bits.control.dst
    aControlLoopIndexWrite.result.valid := oInstr.valid && aControlLoopIndexWrite.output.valid
    aControlLoopIndexWrite.result.bits.addr := aControlLoopIndexWrite.output.bits.addr
    aControlLoopIndexWrite.result.bits.tag := aControlLoopIndexWrite.output.bits.tag
    aControlLoopIndexWrite.result.bits.force := false.B
    aControlLoopIndexWrite.result.bits.value := 0.U // Default value, overridden in switch statement

    // The loopstates should be updated with the output from the register file.
    when (oInstr.valid) {
      switch (oInstr.bits.control.mode) {
        is (ControlInstr.Modes.LoopLocal, ControlInstr.Modes.LoopGlobal, ControlInstr.Modes.LoopImmediate) {
          // Initialize the new loop index to 0.
          aControlLoopIndexWrite.result.bits.value := 0.U
          stateNext.loopStates(oInstr.bits.control.level).index := 0.U
          // We don't need to report iterations to the bamlet control if we received the values already
          // from the bamlet control.
          stateNext.loopStates(oInstr.bits.control.level).reported := aControlIterationsRead.output.bits.resolved
          when (oInstr.bits.control.iterations.resolved) {
            stateNext.loopStates(oInstr.bits.control.level).iterations.value := oInstr.bits.control.iterations.value
            stateNext.loopStates(oInstr.bits.control.level).iterations.resolved := true.B
          } .otherwise {
            stateNext.loopStates(oInstr.bits.control.level).reported := false.B
            stateNext.loopStates(oInstr.bits.control.level).iterations := aControlIterationsRead.output.bits
          }
        }
        is (ControlInstr.Modes.Incr) {
          val newIndex = state.loopStates(oInstr.bits.control.level).index + 1.U
          aControlLoopIndexWrite.result.bits.value := newIndex
          stateNext.loopStates(oInstr.bits.control.level).index := newIndex
        }
      }
    }
    

    // Predicate
    // ---------

    //  val mode = Modes()
    //  val src1 = new Src1Type(params)
    //  val src2 = params.aReg()
    //  val base = params.pReg()
    //  val notBase = Bool()
    //  val dst = params.pReg()

    val aPredicateSrc2Read = aRFBuilder.makeReadPort()
    val pPredicateBaseRead = pRFBuilder.makeReadPort()
    val pPredicateDstWrite = pRFBuilder.makeWritePort()
    val pPacketCommandWrite = pRFBuilder.makeWritePort()

    val predicateValid = io.instr.valid && io.instr.bits.predicate.mode =/= PredicateInstr.Modes.None

    aPredicateSrc2Read.input.valid := predicateValid
    aPredicateSrc2Read.input.bits := io.instr.bits.predicate.src2
    pPredicateBaseRead.input.valid := predicateValid
    pPredicateBaseRead.input.bits := io.instr.bits.predicate.base
    pPredicateDstWrite.input.valid := predicateValid
    pPredicateDstWrite.input.bits := io.instr.bits.predicate.dst

    pPredicateDstWrite.result := regUtils.toPResult(io.resultBus.aluPredicate)

    // Packet command predicate write port (not connected to instruction input, only result)
    pPacketCommandWrite.input.valid := false.B
    pPacketCommandWrite.input.bits := DontCare
    pPacketCommandWrite.result := regUtils.toPResult(io.resultBus.packetPredicate)

    // Predicate instruction output uses the delayed instruction from register file pipeline
    val aluPredicateNone = (oInstr.bits.predicate.mode === PredicateInstr.Modes.None)
    val aluPredicateHasRoom = io.aluPredicateInstr.hasRoom || aluPredicateNone
    io.aluPredicateInstr.valid := outputValid && !aluPredicateNone
    io.aluPredicateInstr.bits.mode := oInstr.bits.predicate.mode
    // src1 handling based on src1Mode

    io.aluPredicateInstr.bits.src1 := oInstr.bits.predicate.src1
    io.aluPredicateInstr.bits.src2 := aPredicateSrc2Read.output.bits
    io.aluPredicateInstr.bits.base := pPredicateBaseRead.output.bits
    io.aluPredicateInstr.bits.notBase := oInstr.bits.predicate.notBase
    io.aluPredicateInstr.bits.dst := pPredicateDstWrite.output.bits

    // 1) Packet Processing
    // --------------------

    // val mode = Modes()
    // val result = params.bReg()
    // val length = params.aReg()
    // val target = params.aReg()
    // val predicate = params.pReg()
    // val channel = UInt(log2Ceil(params.nChannels).W)

    val aPacketLengthRead = aRFBuilder.makeReadPort()
    val aPacketTargetRead = aRFBuilder.makeReadPort()
    val pPacketPredicateRead = pRFBuilder.makeReadPort()

    val aPacketResultRead = aRFBuilder.makeReadPort()
    val aPacketResultWrite = aRFBuilder.makeWritePort()
    val dPacketResultRead = dRFBuilder.makeReadPort()
    val dPacketResultWrite = dRFBuilder.makeWritePort()

    // Packet control signals
    val packetWriteEnable = Wire(Bool())
    val packetResultIsA = Wire(Bool())
    
    packetWriteEnable := PacketInstr.modeWrites(io.instr.bits.packet.mode)
    packetResultIsA := regUtils.bRegIsA(io.instr.bits.packet.result)

    aPacketLengthRead.input.valid := io.instr.valid && PacketInstr.modeUsesLength(io.instr.bits.packet.mode)
    aPacketLengthRead.input.bits := io.instr.bits.packet.length
    aPacketTargetRead.input.valid := io.instr.valid && PacketInstr.modeUsesTarget(io.instr.bits.packet.mode)
    aPacketTargetRead.input.bits := io.instr.bits.packet.target
    pPacketPredicateRead.input.valid := io.instr.valid && io.instr.bits.packet.mode =/= PacketInstr.Modes.None
    pPacketPredicateRead.input.bits := io.instr.bits.packet.predicate

    aPacketResultRead.input.valid := packetWriteEnable && packetResultIsA
    aPacketResultRead.input.bits := regUtils.bRegToA(io.instr.bits.packet.result)
    dPacketResultRead.input.valid := packetWriteEnable && !packetResultIsA
    dPacketResultRead.input.bits := regUtils.bRegToD(io.instr.bits.packet.result)

    aPacketResultWrite.input.valid := packetWriteEnable && packetResultIsA
    aPacketResultWrite.input.bits := regUtils.bRegToA(io.instr.bits.packet.result)
    dPacketResultWrite.input.valid := packetWriteEnable && !packetResultIsA
    dPacketResultWrite.input.bits := regUtils.bRegToD(io.instr.bits.packet.result)

    aPacketResultWrite.result := regUtils.toAResult(io.resultBus.packet)
    dPacketResultWrite.result := regUtils.toDResult(io.resultBus.packet)

    // Send
    val sendPacketNone = !PacketInstr.modeGoesToSend(oInstr.bits.packet.mode)
    val sendPacketHasRoom = io.sendPacketInstr.hasRoom || sendPacketNone
    io.sendPacketInstr.valid := outputValid && !sendPacketNone
    io.sendPacketInstr.bits.mode := oInstr.bits.packet.mode
    io.sendPacketInstr.bits.length := aPacketLengthRead.output.bits
    io.sendPacketInstr.bits.target := aPacketTargetRead.output.bits
    io.sendPacketInstr.bits.channel := oInstr.bits.packet.channel
    io.sendPacketInstr.bits.predicate := pPacketPredicateRead.output.bits
    // We use the write address as an immediate to store the append length (send doesn't write)
    io.sendPacketInstr.bits.appendLength := aPacketResultWrite.output.bits.addr

    // Receive
    val recvPacketNone = !PacketInstr.modeGoesToReceive(oInstr.bits.packet.mode)
    val recvPacketHasRoom = io.recvPacketInstr.hasRoom || recvPacketNone
    io.recvPacketInstr.valid := outputValid && !recvPacketNone
    io.recvPacketInstr.bits.mode := oInstr.bits.packet.mode
    io.recvPacketInstr.bits.result := regUtils.toBWrite(oInstr.bits.packet.result, aPacketResultWrite.output.bits, dPacketResultWrite.output.bits)
    io.recvPacketInstr.bits.old := regUtils.toBRead(oInstr.bits.packet.result, aPacketResultRead.output.bits, dPacketResultRead.output.bits)
    io.recvPacketInstr.bits.target := aPacketTargetRead.output.bits
    io.recvPacketInstr.bits.predicate := pPacketPredicateRead.output.bits


    // 2) Load/Store Processing
    // ------------------------

    // Determine if this is a load or store operation that needs processing
    val isLdStValid = io.instr.bits.loadStore.mode =/= LoadStoreInstr.Modes.None
    val isLoadOp = io.instr.bits.loadStore.mode === LoadStoreInstr.Modes.Load
    val isStoreOp = io.instr.bits.loadStore.mode === LoadStoreInstr.Modes.Store
    val regIsA = regUtils.bRegIsA(io.instr.bits.loadStore.reg)

    val aLdStRegRead = aRFBuilder.makeReadPort()
    val dLdStRegRead = dRFBuilder.makeReadPort()
    val aLdStAddrRead = aRFBuilder.makeReadPort()
    val pLdStPredicateRead = pRFBuilder.makeReadPort()

    val aLdStRegWrite = aRFBuilder.makeWritePort()
    val dLdStRegWrite = dRFBuilder.makeWritePort()

    aLdStRegRead.input.valid := io.instr.valid && (isLoadOp || isStoreOp) && regIsA
    aLdStRegRead.input.bits := regUtils.bRegToA(io.instr.bits.loadStore.reg)
    dLdStRegRead.input.valid := io.instr.valid && (isLoadOp || isStoreOp) && !regIsA
    dLdStRegRead.input.bits := regUtils.bRegToD(io.instr.bits.loadStore.reg)
    aLdStAddrRead.input.valid := io.instr.valid && (isLoadOp || isStoreOp)
    aLdStAddrRead.input.bits := io.instr.bits.loadStore.addr
    pLdStPredicateRead.input.valid := io.instr.valid && (isLoadOp || isStoreOp)
    pLdStPredicateRead.input.bits := io.instr.bits.loadStore.predicate

    aLdStRegWrite.input.valid := io.instr.valid && isLoadOp && regIsA
    aLdStRegWrite.input.bits := regUtils.bRegToA(io.instr.bits.loadStore.reg)
    dLdStRegWrite.input.valid := io.instr.valid && isLoadOp && !regIsA
    dLdStRegWrite.input.bits := regUtils.bRegToD(io.instr.bits.loadStore.reg)

    aLdStRegWrite.result := regUtils.toAResult(io.resultBus.ldSt)
    dLdStRegWrite.result := regUtils.toDResult(io.resultBus.ldSt)

    // Output to load/store reservation station
    val ldstNone = (oInstr.bits.loadStore.mode ===  LoadStoreInstr.Modes.None)
    val ldstHasRoom = io.ldstInstr.hasRoom || ldstNone
    io.ldstInstr.valid := outputValid && !ldstNone
    io.ldstInstr.bits.mode := oInstr.bits.loadStore.mode
    io.ldstInstr.bits.addr := aLdStAddrRead.output.bits
    io.ldstInstr.bits.src := regUtils.toBRead(oInstr.bits.loadStore.reg, aLdStRegRead.output.bits, dLdStRegRead.output.bits)
    io.ldstInstr.bits.dst := regUtils.toBWrite(oInstr.bits.loadStore.reg, aLdStRegWrite.output.bits, dLdStRegWrite.output.bits)
    io.ldstInstr.bits.predicate := pLdStPredicateRead.output.bits

    // 3) ALU Processing
    // -----------------
    // Determine if this is a valid ALU operation
    val isALUValid = io.instr.bits.alu.mode =/= ALUInstr.Modes.None

    val dALUSrc1Read = dRFBuilder.makeReadPort()
    val dALUSrc2Read = dRFBuilder.makeReadPort()
    val aALUDstRead = aRFBuilder.makeReadPort()
    val dALUDstRead = dRFBuilder.makeReadPort()
    val pALUPredicateRead = pRFBuilder.makeReadPort()

    val aALURegWrite = aRFBuilder.makeWritePort()
    val dALURegWrite = dRFBuilder.makeWritePort()

    val dstIsA = regUtils.bRegIsA(io.instr.bits.alu.dst)
    
    dALUSrc1Read.input.valid := io.instr.valid && isALUValid
    dALUSrc1Read.input.bits := io.instr.bits.alu.src1
    dALUSrc2Read.input.valid := io.instr.valid && isALUValid && !ALUInstr.modeIsImmediate(io.instr.bits.alu.mode)
    dALUSrc2Read.input.bits := io.instr.bits.alu.src2
    aALUDstRead.input.valid := io.instr.valid && isALUValid && dstIsA
    aALUDstRead.input.bits := regUtils.bRegToA(io.instr.bits.alu.dst)
    dALUDstRead.input.valid := io.instr.valid && isALUValid && !dstIsA
    dALUDstRead.input.bits := regUtils.bRegToD(io.instr.bits.alu.dst)
    pALUPredicateRead.input.valid := io.instr.valid && isALUValid
    pALUPredicateRead.input.bits := io.instr.bits.alu.predicate

    aALURegWrite.input.valid := io.instr.valid && isALUValid && dstIsA
    aALURegWrite.input.bits := regUtils.bRegToA(io.instr.bits.alu.dst)
    dALURegWrite.input.valid := io.instr.valid && isALUValid && !dstIsA
    dALURegWrite.input.bits := regUtils.bRegToD(io.instr.bits.alu.dst)

    aALURegWrite.result := regUtils.toAResult(io.resultBus.alu)
    dALURegWrite.result := regUtils.toDResult(io.resultBus.alu)

    // Output to ALU reservation station
    val aluNone = oInstr.bits.alu.mode === ALUInstr.Modes.None
    val aluHasRoom = io.aluInstr.hasRoom || aluNone
    io.aluInstr.valid := outputValid && !aluNone
    io.aluInstr.bits.mode := oInstr.bits.alu.mode
    io.aluInstr.bits.src1 := dALUSrc1Read.output.bits
    when (ALUInstr.modeIsImmediate(oInstr.bits.alu.mode)) {
      io.aluInstr.bits.src2.resolved := true.B
      io.aluInstr.bits.src2.value := oInstr.bits.alu.src2
      io.aluInstr.bits.src2.addr := DontCare
      io.aluInstr.bits.src2.tag := DontCare
    } .otherwise {
      io.aluInstr.bits.src2 := dALUSrc2Read.output.bits
    }
    io.aluInstr.bits.dst := regUtils.toBWrite(oInstr.bits.alu.dst, aALURegWrite.output.bits, dALURegWrite.output.bits)
    io.aluInstr.bits.old := regUtils.toBRead(oInstr.bits.alu.dst, aALUDstRead.output.bits, dALUDstRead.output.bits)
    io.aluInstr.bits.predicate := pALUPredicateRead.output.bits

    // 4) ALULite Processing
    // --------------------

    // Determine if this is a valid ALULite operation
    val isALULiteValid = io.instr.bits.aluLite.mode =/= ALULiteInstr.Modes.None

    val aALULiteSrc1Read = aRFBuilder.makeReadPort()
    val aALULiteSrc2Read = aRFBuilder.makeReadPort()
    val aALULiteDstRead = aRFBuilder.makeReadPort()
    val dALULiteDstRead = dRFBuilder.makeReadPort()
    val pALULitePredicateRead = pRFBuilder.makeReadPort()

    val aALULiteDstWrite = aRFBuilder.makeWritePort()
    val dALULiteDstWrite = dRFBuilder.makeWritePort()

    val aluLiteDstIsA = regUtils.bRegIsA(io.instr.bits.aluLite.dst)
    
    aALULiteSrc1Read.input.valid := io.instr.valid && isALULiteValid
    aALULiteSrc1Read.input.bits := io.instr.bits.aluLite.src1
    aALULiteSrc2Read.input.valid := io.instr.valid && isALULiteValid && !ALULiteInstr.modeIsImmediate(io.instr.bits.aluLite.mode)
    aALULiteSrc2Read.input.bits := io.instr.bits.aluLite.src2
    aALULiteDstRead.input.valid := io.instr.valid && isALULiteValid && aluLiteDstIsA
    aALULiteDstRead.input.bits := regUtils.bRegToA(io.instr.bits.aluLite.dst)
    dALULiteDstRead.input.valid := io.instr.valid && isALULiteValid && !aluLiteDstIsA
    dALULiteDstRead.input.bits := regUtils.bRegToD(io.instr.bits.aluLite.dst)
    pALULitePredicateRead.input.valid := io.instr.valid && isALULiteValid
    pALULitePredicateRead.input.bits := io.instr.bits.aluLite.predicate

    aALULiteDstWrite.input.valid := io.instr.valid && isALULiteValid && aluLiteDstIsA
    aALULiteDstWrite.input.bits := regUtils.bRegToA(io.instr.bits.aluLite.dst)
    dALULiteDstWrite.input.valid := io.instr.valid && isALULiteValid && !aluLiteDstIsA
    dALULiteDstWrite.input.bits := regUtils.bRegToD(io.instr.bits.aluLite.dst)

    aALULiteDstWrite.result := regUtils.toAResult(io.resultBus.alulite)
    dALULiteDstWrite.result := regUtils.toDResult(io.resultBus.alulite)

    // Output to ALULite reservation station
    val aluliteNone = oInstr.bits.aluLite.mode === ALULiteInstr.Modes.None
    val aluliteHasRoom = io.aluliteInstr.hasRoom || aluliteNone
    io.aluliteInstr.valid := outputValid && !aluliteNone
    io.aluliteInstr.bits.mode := oInstr.bits.aluLite.mode
    io.aluliteInstr.bits.src1 := aALULiteSrc1Read.output.bits
    when (ALULiteInstr.modeIsImmediate(oInstr.bits.aluLite.mode)) {
      io.aluliteInstr.bits.src2.resolved := true.B
      io.aluliteInstr.bits.src2.value := oInstr.bits.aluLite.src2
      io.aluliteInstr.bits.src2.addr := DontCare
      io.aluliteInstr.bits.src2.tag := DontCare
    } .otherwise {
      io.aluliteInstr.bits.src2 := aALULiteSrc2Read.output.bits
    }
    io.aluliteInstr.bits.dst := regUtils.toBWrite(oInstr.bits.aluLite.dst, aALULiteDstWrite.output.bits, dALULiteDstWrite.output.bits)
    io.aluliteInstr.bits.old := regUtils.toBRead(oInstr.bits.aluLite.dst, aALULiteDstRead.output.bits, dALULiteDstRead.output.bits)
    io.aluliteInstr.bits.predicate := pALULitePredicateRead.output.bits

    // Make the register Files
    val pRF = pRFBuilder.makeModule()
    val aRF = aRFBuilder.makeModule()
    val dRF = dRFBuilder.makeModule()
    
    // Ready/Valid Protocol Coordination:
    // Input side: Accept new instruction only when all register files and pipeline are ready
    // Output side: Advance pipeline only when all downstream reservation stations (for which the instruction has valid slots) are ready
    
    val outputHasRoom = Wire(Bool())
    outputHasRoom :=             aluHasRoom && aluliteHasRoom && ldstHasRoom && sendPacketHasRoom && recvPacketHasRoom && aluPredicateHasRoom

    io.instr.ready := aRF.io.iAccess.ready && dRF.io.iAccess.ready && pRF.io.iAccess.ready && iInstr.ready

    // Connect instruction pipeline input
    iInstr.bits := io.instr.bits
    iInstr.valid := io.instr.valid && aRF.io.iAccess.ready && dRF.io.iAccess.ready && pRF.io.iAccess.ready
    
    // We send data into a register file if there is valid input and the other places are ready.
    pRF.io.iAccess.valid := io.instr.valid && aRF.io.iAccess.ready && dRF.io.iAccess.ready && iInstr.ready
    aRF.io.iAccess.valid := io.instr.valid && pRF.io.iAccess.ready && dRF.io.iAccess.ready && iInstr.ready
    dRF.io.iAccess.valid := io.instr.valid && pRF.io.iAccess.ready && aRF.io.iAccess.ready && iInstr.ready

    // We remove data when there is data is all outputs.
    outputValid := aRF.io.oAccess.valid && dRF.io.oAccess.valid && pRF.io.oAccess.valid && oInstr.valid
    pRF.io.oAccess.hasRoom := outputHasRoom
    dRF.io.oAccess.hasRoom := outputHasRoom
    aRF.io.oAccess.hasRoom := outputHasRoom
    pRF.io.externalStall := dRF.io.localStall || aRF.io.localStall
    aRF.io.externalStall := dRF.io.localStall || pRF.io.localStall
    dRF.io.externalStall := aRF.io.localStall || pRF.io.localStall
    stalled := aRF.io.localStall || dRF.io.localStall || pRF.io.localStall
    oInstr.hasRoom := outputHasRoom


    // Send resolved loop iterations to the Bamlet Control
    val unreportedLoopLevel = Wire(UInt(log2Ceil(params.nLoopLevels).W))
    val foundUnreportedLoop = Wire(Bool())
    
    // Find the lowest loop level that needs reporting using priority encoder
    val needsReporting = Wire(Vec(params.nLoopLevels, Bool()))
    for (i <- 0 until params.nLoopLevels) {
      needsReporting(i) := !state.loopStates(i).reported && 
                           state.loopStates(i).iterations.resolved
    }
    dontTouch(needsReporting)
    
    foundUnreportedLoop := needsReporting.asUInt =/= 0.U
    unreportedLoopLevel := PriorityEncoder(needsReporting)
    
    // Send loop iterations if we found an unreported resolved loop
    val loopIterationsToBuffer = Wire(Valid(UInt(params.aWidth.W)))
    loopIterationsToBuffer.valid := foundUnreportedLoop
    loopIterationsToBuffer.bits := state.loopStates(unreportedLoopLevel).iterations.value

    io.loopIterations := ValidBuffer(loopIterationsToBuffer)
    
    // Mark the loop level as reported in next state
    when (foundUnreportedLoop) {
      stateNext.loopStates(unreportedLoopLevel).reported := true.B
    }
  }
}

/** Generator object for creating RegisterFileAndRename modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of RegisterFileAndRename modules with configurable parameters.
  */
object RegisterFileAndRenameGenerator extends zamlet.ModuleGenerator {
  /** Create a RegisterFileAndRename module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return RegisterFileAndRename module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> RegisterFileAndRename <amletParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new RegisterFileAndRename(params)
    }
  }
}
