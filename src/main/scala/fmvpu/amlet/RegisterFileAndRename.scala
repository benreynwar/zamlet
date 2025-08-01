package fmvpu.amlet

import chisel3._
import chisel3.util._
import scala.math.max


class LoopState(params: AmletParams) extends Bundle {
  val index = UInt(params.aWidth.W)
  val iterations = new ATaggedSource(params)
  // Whether we've reported the resolved loop iterations back to the 
  // bamlet control already.
  val reported = Bool()
  
  // NOTE: Bamlet Control is the authoritative source for loop state.
  // This Amlet loop state exists solely to track which A-register
  // gets the loop index written to it during loop execution.
}

class TagAllocation(params: AmletParams) extends Bundle {
  // The updated registers.
  val registers = new State(params)
  // The write reg with the assigned rename tag.
  val writeReg = new BTaggedReg(params)
  // Stall required if we were unable to assign a rename tag.
  val stallRequired = Bool()
}

class PTagAllocation(params: AmletParams) extends Bundle {
  // The updated registers.
  val registers = new State(params)
  // The write reg with the assigned rename tag.
  val writeReg = new PTaggedReg(params)
  // Stall required if we were unable to assign a rename tag.
  val stallRequired = Bool()
}


/**
 * State information for a single register in the register file
 */
class DRegisterState(params: AmletParams) extends Bundle {
  /** Current value stored in the register */
  val value = UInt(params.width.W)
  
  /** Bit vector indicating which rename tags are pending */
  val pendingTags = UInt(params.nWriteIdents.W)
  
  /** The last rename tag that was issued for this register */
  val lastIdent = UInt(params.regTagWidth.W)
}

class ARegisterState(params: AmletParams) extends Bundle {
  /** Current value stored in the register */
  val value = UInt(params.aWidth.W)
  
  /** Bit vector indicating which rename tags are pending */
  val pendingTags = UInt(params.nWriteIdents.W)
  
  /** The last rename tag that was issued for this register */
  val lastIdent = UInt(params.regTagWidth.W)
}

class PRegisterState(params: AmletParams) extends Bundle {
  /** Current value stored in the register */
  val value = Bool()
  
  /** Bit vector indicating which rename tags are pending */
  val pendingTags = UInt(params.nPTags.W)
  
  /** The last rename tag that was issued for this register */
  val lastIdent = UInt(log2Ceil(params.nPTags).W)
}

class State(params: AmletParams) extends Bundle {
  val dRegs = Vec(params.nDRegs, new DRegisterState(params))
  val aRegs = Vec(params.nARegs, new ARegisterState(params))
  val pRegs = Vec(params.nPRegs, new PRegisterState(params))
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
  val io = IO(new Bundle {

    val instr = Flipped(Decoupled(new VLIWInstr.Expanded(params)))

    // Write inputs from ALU, load/store, and packets
    val resultBus = Input(new ResultBus(params))
    
    // Instruction outputs to reservation stations
    val aluInstr = Decoupled(new ALUInstr.Resolving(params))
    val aluliteInstr = Decoupled(new ALULiteInstr.Resolving(params))
    val aluPredicateInstr = Decoupled(new PredicateInstr.Resolving(params))
    val ldstInstr = Decoupled(new LoadStoreInstr.Resolving(params))
    val sendPacketInstr = Decoupled(new PacketInstr.SendResolving(params))
    val recvPacketInstr = Decoupled(new PacketInstr.ReceiveResolving(params))

    // Tells the Bamlet control how many iterations there are in a loop.
    val loopIterations = Output(Valid(UInt(params.aWidth.W)))
  })

  val stateInitial = Wire(new State(params))
  // Initialize all registers to 0 with no in-flight writes
  for (i <- 0 until params.nDRegs) {
    stateInitial.dRegs(i).value := 0.U
    stateInitial.dRegs(i).pendingTags := 0.U  // No writes currently pending
    stateInitial.dRegs(i).lastIdent := 0.U  // No rename tags issued yet
  }
  for (i <- 0 until params.nARegs) {
    stateInitial.aRegs(i).value := 0.U
    stateInitial.aRegs(i).pendingTags := 0.U
    stateInitial.aRegs(i).lastIdent := 0.U  // No rename tags issued yet
  }
  for (i <- 0 until params.nPRegs) {
    stateInitial.pRegs(i).value := false.B
    stateInitial.pRegs(i).pendingTags := 0.U
    stateInitial.pRegs(i).lastIdent := 0.U  // No rename tags issued yet
  }
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
  
  // For register 0 (packet output), always increment - order matters for packet assembly
  // For other registers, find first available write identifier
  //
  // To Claude: Let's make a function for processing each of these instructlets that
  // takes the registers as an input, and returns new registers and a Resolving instruction.

  // Update the registers for each of the instructlet.
  //
  // 1) Control
  // --------------
  val statePreControl = Wire(new State(params))
  val statePostControl = Wire(new State(params))
  statePostControl := statePreControl

  val controlIterations = readAReg(statePreControl, io.instr.bits.control.iterations.addr)

  switch (io.instr.bits.control.mode) {
    is (ControlInstr.Modes.LoopLocal, ControlInstr.Modes.LoopGlobal, ControlInstr.Modes.LoopImmediate) {
      statePostControl.loopStates(io.instr.bits.control.level).index := 0.U  // Initialize new loop index to 0
      // We also set the destination register.
      // We do this directly rather than going through the resultBus.
      // May become a timing problem.
      statePostControl.aRegs(io.instr.bits.control.dst).value := 0.U
      statePostControl.aRegs(io.instr.bits.control.dst).lastIdent := statePreControl.aRegs(io.instr.bits.control.dst).lastIdent + 1.U
      // We don't need to report iterations do the bamlet control if we received the values already
      // from the bamlet control.
      statePostControl.loopStates(io.instr.bits.control.level).reported := io.instr.bits.control.iterations.resolved
      when (io.instr.bits.control.iterations.resolved) {
        statePostControl.loopStates(io.instr.bits.control.level).iterations.value := io.instr.bits.control.iterations.value
        statePostControl.loopStates(io.instr.bits.control.level).iterations.resolved := true.B
      } .otherwise {
        statePostControl.loopStates(io.instr.bits.control.level).iterations := controlIterations
      }
    }
    is (ControlInstr.Modes.Incr) {
      // Increment the loop index at the current loop level
      val newIndex = statePreControl.loopStates(io.instr.bits.control.level).index + 1.U
      statePostControl.loopStates(io.instr.bits.control.level).index := newIndex
      // Set register.
      statePostControl.aRegs(io.instr.bits.control.dst).value := newIndex
      statePostControl.aRegs(io.instr.bits.control.dst).lastIdent := statePreControl.aRegs(io.instr.bits.control.dst).lastIdent + 1.U
    }
  }
  

  // Predicate
  // ---------
  val statePrePredicate = Wire(new State(params))
  val statePostPredicate = Wire(new State(params))
  statePostPredicate := statePrePredicate

  val predicateSrc2 = readAReg(statePrePredicate, io.instr.bits.predicate.src2)
  val predicateBase = readPReg(statePrePredicate, io.instr.bits.predicate.base)
  val predicateTagAlloc = assignPWrite(statePrePredicate, io.instr.bits.predicate.dst)
  val predicateWriteInfo = predicateTagAlloc.writeReg

  val predicateValid = io.instr.bits.predicate.mode =/= PredicateInstr.Modes.None
  when (predicateValid) {
    statePostPredicate := predicateTagAlloc.registers
  } .otherwise {
    statePostPredicate := statePrePredicate
  }
  io.aluPredicateInstr.valid := io.instr.valid && io.instr.ready && predicateValid
  io.aluPredicateInstr.bits.mode := io.instr.bits.predicate.mode
  io.aluPredicateInstr.bits.src1 := io.instr.bits.predicate.src1
  io.aluPredicateInstr.bits.src2 := predicateSrc2
  io.aluPredicateInstr.bits.base := predicateBase
  io.aluPredicateInstr.bits.notBase := io.instr.bits.predicate.notBase
  io.aluPredicateInstr.bits.dst := predicateWriteInfo

  // 1) Packet Processing
  // --------------------
  val statePrePacket = Wire(new State(params))
  val statePostPacket = Wire(new State(params))
  statePostPacket := statePrePacket

  // Packet control signals
  val packetReceive = Wire(Bool())
  val packetForward = Wire(Bool())
  val packetAppend = Wire(Bool())
  val packetAppendContinuously = Wire(Bool())
  val packetSend = Wire(Bool())
  val packetRead1Enable = Wire(Bool())
  val packetRead2Enable = Wire(Bool())
  val packetWriteEnable = Wire(Bool())
  
  // Initialize with default values
  packetReceive := false.B
  packetForward := false.B  
  packetAppend := false.B
  packetAppendContinuously := false.B
  packetSend := false.B
  packetRead1Enable := false.B
  packetRead2Enable := false.B
  packetWriteEnable := false.B

  switch (io.instr.bits.packet.mode) {
    is (PacketInstr.Modes.Null) {
      packetReceive := false.B
      packetForward := false.B
      packetAppend := false.B
      packetAppendContinuously := false.B
      packetSend := false.B
      packetRead1Enable := false.B
      packetRead2Enable := false.B
      packetWriteEnable := false.B
    }
    is (PacketInstr.Modes.Receive) {
      packetReceive := true.B
      packetForward := false.B
      packetAppend := false.B
      packetAppendContinuously := false.B
      packetSend := false.B
      packetRead1Enable := false.B
      packetRead2Enable := false.B
      packetWriteEnable := true.B
    }
    is (PacketInstr.Modes.ReceiveAndForward) {
      packetReceive := true.B
      packetForward := true.B
      packetAppend := false.B
      packetAppendContinuously := false.B
      packetSend := false.B
      packetRead1Enable := false.B
      packetRead2Enable := false.B
      packetWriteEnable := true.B
    }
    is (PacketInstr.Modes.ReceiveForwardAndAppend) {
      packetReceive := true.B
      packetForward := true.B
      packetAppend := true.B
      packetAppendContinuously := false.B
      packetSend := true.B
      packetRead1Enable := false.B
      packetRead2Enable := false.B
      packetWriteEnable := true.B
    }
    is (PacketInstr.Modes.ForwardAndAppend) {
      packetReceive := false.B
      packetForward := true.B
      packetAppend := true.B
      packetAppendContinuously := false.B
      packetSend := true.B
      packetRead1Enable := true.B
      packetRead2Enable := false.B
      packetWriteEnable := false.B
    }
    is (PacketInstr.Modes.Send) {
      packetReceive := false.B
      packetForward := false.B
      packetAppend := false.B
      packetAppendContinuously := false.B
      packetSend := true.B
      packetRead1Enable := true.B
      packetRead2Enable := true.B
      packetWriteEnable := false.B
    }
    is (PacketInstr.Modes.GetWord) {
      packetReceive := true.B
      packetForward := false.B
      packetAppend := false.B
      packetAppendContinuously := false.B
      packetSend := false.B
      packetRead1Enable := false.B
      packetRead2Enable := false.B
      packetWriteEnable := true.B
    }
    is (PacketInstr.Modes.Broadcast) {
      packetReceive := false.B
      packetForward := false.B
      packetAppend := false.B
      packetAppendContinuously := false.B
      packetSend := true.B
      packetRead1Enable := true.B
      packetRead2Enable := true.B
      packetWriteEnable := false.B
    }
    is (PacketInstr.Modes.ReceiveAndForwardContinuously) {
      packetReceive := true.B
      packetForward := true.B
      packetAppend := false.B
      packetAppendContinuously := true.B
      packetSend := false.B
      packetRead1Enable := false.B
      packetRead2Enable := false.B
      packetWriteEnable := true.B
    }
    is (PacketInstr.Modes.ReceiveForwardAndAppendContinuously) {
      packetReceive := true.B
      packetForward := true.B
      packetAppend := true.B
      packetAppendContinuously := true.B
      packetSend := true.B
      packetRead1Enable := false.B
      packetRead2Enable := false.B
      packetWriteEnable := true.B
    }
    is (PacketInstr.Modes.ForwardAndAppendContinuously) {
      packetReceive := false.B
      packetForward := true.B
      packetAppend := false.B
      packetAppendContinuously := true.B
      packetSend := true.B
      packetRead1Enable := true.B
      packetRead2Enable := false.B
      packetWriteEnable := false.B
    }
    is (PacketInstr.Modes.SendAndForwardAgain) {
      packetReceive := false.B
      packetForward := true.B
      packetAppend := false.B
      packetAppendContinuously := false.B
      packetSend := true.B
      packetRead1Enable := true.B
      packetRead2Enable := true.B
      packetWriteEnable := false.B
    }
  }

  val packetReadLength = readAReg(statePrePacket, io.instr.bits.packet.length)
  val packetReadTarget = readAReg(statePrePacket, io.instr.bits.packet.target)
  val packetPredicate = readPReg(statePrePacket, io.instr.bits.packet.predicate)
  val packetTagAlloc = assignWrite(statePrePacket, io.instr.bits.packet.result)
  val packetWriteInfo = packetTagAlloc.writeReg
  // Update register state if packet instruction writes to a register
  when (packetWriteEnable) {
    statePostPacket := packetTagAlloc.registers
  } .otherwise {
    statePostPacket := statePrePacket
  }

  // Send
  io.sendPacketInstr.valid := io.instr.valid && io.instr.ready && packetSend
  io.sendPacketInstr.bits.mode := io.instr.bits.packet.mode
  io.sendPacketInstr.bits.length := packetReadLength
  io.sendPacketInstr.bits.target := packetReadTarget
  io.sendPacketInstr.bits.result := packetWriteInfo
  io.sendPacketInstr.bits.channel := io.instr.bits.packet.channel
  io.sendPacketInstr.bits.predicate := packetPredicate

  // Receive
  io.recvPacketInstr.valid := io.instr.valid && io.instr.ready && packetReceive
  io.recvPacketInstr.bits.mode := io.instr.bits.packet.mode
  io.recvPacketInstr.bits.result := packetWriteInfo
  // Only resolve target for receive modes that include forwarding
  val receiveNeedsTarget = io.instr.bits.packet.mode === PacketInstr.Modes.ReceiveAndForward ||
                          io.instr.bits.packet.mode === PacketInstr.Modes.ReceiveForwardAndAppend ||
                          io.instr.bits.packet.mode === PacketInstr.Modes.ReceiveAndForwardContinuously ||
                          io.instr.bits.packet.mode === PacketInstr.Modes.ReceiveForwardAndAppendContinuously ||
                          io.instr.bits.packet.mode === PacketInstr.Modes.ForwardAndAppend ||
                          io.instr.bits.packet.mode === PacketInstr.Modes.ForwardAndAppendContinuously
  when (receiveNeedsTarget) {
    io.recvPacketInstr.bits.target := packetReadTarget
  } .otherwise {
    io.recvPacketInstr.bits.target.value := DontCare
    io.recvPacketInstr.bits.target.resolved := true.B
    io.recvPacketInstr.bits.target.addr := DontCare
    io.recvPacketInstr.bits.target.tag := DontCare
  }
  io.recvPacketInstr.bits.predicate := packetPredicate


  // 2) Load/Store Processing
  // ------------------------

  val statePreLdSt = Wire(new State(params))
  val statePostLdSt = Wire(new State(params))
  statePostLdSt := statePreLdSt

  // Determine if this is a load or store operation that needs processing
  val isLdStValid = io.instr.bits.loadStore.mode =/= LoadStoreInstr.Modes.None
  val isLoadOp = io.instr.bits.loadStore.mode === LoadStoreInstr.Modes.Load
  val isStoreOp = io.instr.bits.loadStore.mode === LoadStoreInstr.Modes.Store

  // Read operands for load/store operations
  val ldstReadAddress = readAReg(statePreLdSt, io.instr.bits.loadStore.addr)
  val ldstReadData = readBReg(statePreLdSt, io.instr.bits.loadStore.reg)
  val ldstPredicate = readPReg(statePreLdSt, io.instr.bits.loadStore.predicate)

  // For load operations, allocate a rename tag for the destination register
  val ldstTagAlloc = assignWrite(statePreLdSt, io.instr.bits.loadStore.reg)
  val ldstWriteInfo = ldstTagAlloc.writeReg

  // Update register state if load operation writes to a register
  when (isLoadOp) {
    statePostLdSt := ldstTagAlloc.registers
  } .otherwise {
    statePostLdSt := statePreLdSt
  }

  // Output to load/store reservation station
  io.ldstInstr.valid := io.instr.valid && io.instr.ready && isLdStValid
  io.ldstInstr.bits.mode := io.instr.bits.loadStore.mode
  io.ldstInstr.bits.addr := ldstReadAddress
  io.ldstInstr.bits.src := ldstReadData
  io.ldstInstr.bits.dst := ldstWriteInfo
  io.ldstInstr.bits.predicate := ldstPredicate

  // 3) ALU Processing
  // -----------------
  val statePreALU = Wire(new State(params))
  val statePostALU = Wire(new State(params))
  statePostALU := statePreALU

  // Determine if this is a valid ALU operation
  val isALUValid = io.instr.bits.alu.mode =/= ALUInstr.Modes.None

  // Read operands for ALU operations
  val aluReadSrc1 = readDReg(statePreALU, io.instr.bits.alu.src1)
  val aluReadSrc2 = Wire(new DTaggedSource(params))
  val aluPredicate = readPReg(statePreALU, io.instr.bits.alu.predicate)
  
  // For immediate instructions (ADDI, SUBI), src2 is an immediate value, not a register
  val isImmediateInstr = (io.instr.bits.alu.mode === ALUInstr.Modes.Addi) || 
                        (io.instr.bits.alu.mode === ALUInstr.Modes.Subi)
  
  aluReadSrc2 := readDReg(statePreALU, io.instr.bits.alu.src2)
  when (isImmediateInstr) {
    aluReadSrc2.resolved := true.B
    aluReadSrc2.value := io.instr.bits.alu.src2  // Use src2 field as immediate value
  }

  // Allocate a rename tag for the destination register
  val aluTagAlloc = assignWrite(statePreALU, io.instr.bits.alu.dst)
  val aluWriteInfo = aluTagAlloc.writeReg

  // Update register state for ALU write
  when (isALUValid) {
    statePostALU := aluTagAlloc.registers
  } .otherwise {
    statePostALU := statePreALU
  }

  // Output to ALU reservation station
  io.aluInstr.valid := io.instr.valid && io.instr.ready && isALUValid
  io.aluInstr.bits.mode := io.instr.bits.alu.mode
  io.aluInstr.bits.src1 := aluReadSrc1
  io.aluInstr.bits.src2 := aluReadSrc2
  io.aluInstr.bits.dst := aluWriteInfo
  io.aluInstr.bits.predicate := aluPredicate

  // 4) ALULite Processing
  // -----------------
  val statePreALULite = Wire(new State(params))
  val statePostALULite = Wire(new State(params))
  statePostALULite := statePreALULite

  // Determine if this is a valid ALULite operation
  val isALULiteValid = io.instr.bits.aluLite.mode =/= ALULiteInstr.Modes.None

  // Read operands for ALULite operations (uses A-registers)
  val aluliteReadSrc1 = readAReg(statePreALULite, io.instr.bits.aluLite.src1)
  val aluliteReadSrc2 = Wire(new ATaggedSource(params))
  val alulitePredicate = readPReg(statePreALULite, io.instr.bits.aluLite.predicate)
  
  // For immediate instructions (ADDI, SUBI), src2 is an immediate value, not a register
  val isALULiteImmediateInstr = (io.instr.bits.aluLite.mode === ALULiteInstr.Modes.Addi) || 
                               (io.instr.bits.aluLite.mode === ALULiteInstr.Modes.Subi)
  
  aluliteReadSrc2 := readAReg(statePreALULite, io.instr.bits.aluLite.src2)
  when (isALULiteImmediateInstr) {
    aluliteReadSrc2.resolved := true.B
    aluliteReadSrc2.value := io.instr.bits.aluLite.src2  // Use src2 field as immediate value
  }

  // Allocate a rename tag for the destination register
  val aluliteTagAlloc = assignWrite(statePreALULite, io.instr.bits.aluLite.dst)
  val aluliteWriteInfo = aluliteTagAlloc.writeReg

  // Update register state for ALULite write
  when (isALULiteValid) {
    statePostALULite := aluliteTagAlloc.registers
  } .otherwise {
    statePostALULite := statePreALULite
  }

  // Output to ALULite reservation station
  io.aluliteInstr.valid := io.instr.valid && io.instr.ready && isALULiteValid
  io.aluliteInstr.bits.mode := io.instr.bits.aluLite.mode
  io.aluliteInstr.bits.src1 := aluliteReadSrc1
  io.aluliteInstr.bits.src2 := aluliteReadSrc2
  io.aluliteInstr.bits.dst := aluliteWriteInfo
  io.aluliteInstr.bits.predicate := alulitePredicate

  // If the reservation stations can't accept the instruction then we stall.
  val blockedALU = isALUValid && aluTagAlloc.stallRequired
  val blockedLdSt = isLoadOp && ldstTagAlloc.stallRequired
  val blockedALULite = isALULiteValid && aluliteTagAlloc.stallRequired
  val blockedPacket = packetWriteEnable && packetTagAlloc.stallRequired
  val blockedPredicate = predicateValid && predicateTagAlloc.stallRequired

  val hasALUInstr = io.instr.bits.alu.mode =/= ALUInstr.Modes.None
  val hasLdStInstr = io.instr.bits.loadStore.mode =/= LoadStoreInstr.Modes.None
  val hasALULiteInstr = io.instr.bits.aluLite.mode =/= ALULiteInstr.Modes.None  
  val hasPacketInstr = io.instr.bits.packet.mode =/= PacketInstr.Modes.Null
  val hasPredicateInstr = io.instr.bits.predicate.mode =/= PredicateInstr.Modes.None

  val stallALU = hasALUInstr && (!io.aluInstr.ready || blockedALU)
  val stallLdSt = hasLdStInstr && (!io.ldstInstr.ready || blockedLdSt)
  val stallPacket = hasPacketInstr && ((!io.sendPacketInstr.ready && packetSend) || (!io.recvPacketInstr.ready && packetReceive) || blockedPacket)
  val stallALULite = hasALULiteInstr && (!io.aluliteInstr.ready || blockedALULite)
  val stallPredicate = hasPredicateInstr && (!io.aluPredicateInstr.ready || blockedPredicate)
  dontTouch(stallALU)
  dontTouch(stallALULite)
  dontTouch(stallLdSt)
  dontTouch(stallPacket)
  dontTouch(stallPredicate)
  io.instr.ready := !stallALU && !stallALULite && !stallLdSt && !stallPacket && !stallPredicate

  // Chain register state updates through all instruction types
  val stateFromTagging = Wire(new State(params))
  statePreControl := state // Start with current register state
  statePrePredicate := statePostControl
  statePrePacket := statePostPredicate 
  statePreLdSt := statePostPacket  // Load/store sees packet updates
  statePreALU := statePostLdSt     // ALU sees load/store updates  
  statePreALULite := statePostALU  // ALULite sees ALU updates
  stateFromTagging := statePostALULite  // Final state after all instruction processing

  when (io.instr.valid && io.instr.ready) {
    // Update the state
    stateNext := stateFromTagging
  } .otherwise {
    stateNext := state
  }
  
  // Update register state on writes from execution units
  for (i <- 0 until params.nResultPorts) {
    when (io.resultBus.writes(i).valid) {
      val regAddr = io.resultBus.writes(i).bits.address.addr
      val renameTag = io.resultBus.writes(i).bits.address.tag
      val isForceWrite = io.resultBus.writes(i).bits.force
      val isDRegWrite = regAddr(params.bRegWidth-1)  // Upper bit = 1 for D-registers
      
      when (!isDRegWrite) {
        // A-register write: only update if rename tag matches expected or force write
        val aIndex = regAddr(log2Ceil(params.nARegs)-1, 0)  // Truncate to A-register width
        when ((renameTag === stateFromTagging.aRegs(aIndex).lastIdent) || isForceWrite) {
          stateNext.aRegs(aIndex).value := io.resultBus.writes(i).bits.value
        }
        // Clear in-flight bit for this rename tag (normal writes only)
        when (!isForceWrite) {
          stateNext.aRegs(aIndex).pendingTags := stateFromTagging.aRegs(aIndex).pendingTags & ~UIntToOH(renameTag)
        }
      } .otherwise {
        // D-register write: same logic as A-registers
        val dIndex = regAddr(log2Ceil(params.nDRegs)-1, 0)  // Truncate to D-register width
        when ((renameTag === stateFromTagging.dRegs(dIndex).lastIdent) || isForceWrite) {
          stateNext.dRegs(dIndex).value := io.resultBus.writes(i).bits.value
        }
        when (!isForceWrite) {
          stateNext.dRegs(dIndex).pendingTags := stateFromTagging.dRegs(dIndex).pendingTags & ~UIntToOH(renameTag)
        }
      }
    }
  }

  // Update loop iterations on writes from execution units
  for (i <- 0 until params.nResultPorts) {
    when (io.resultBus.writes(i).valid) {
      val regAddr = io.resultBus.writes(i).bits.address.addr
      val renameTag = io.resultBus.writes(i).bits.address.tag
      val isForceWrite = io.resultBus.writes(i).bits.force
      for (j <- 0 until params.nLoopLevels) {
        when ((state.loopStates(j).iterations.addr === regAddr) &&
              ((state.loopStates(j).iterations.tag === renameTag) || isForceWrite)) {
          stateNext.loopStates(j).iterations.resolved := true.B
          stateNext.loopStates(j).iterations.value := io.resultBus.writes(i).bits.value
        }
      }
    }
  }

  // Update predicate register state on predicate results
  for (i <- 0 until 2) {
    when (io.resultBus.predicate(i).valid) {
      val pRegAddr = io.resultBus.predicate(i).bits.address.addr
      val pRenameTag = io.resultBus.predicate(i).bits.address.tag
      val pIndex = pRegAddr(log2Ceil(params.nPRegs)-1, 0)  // Truncate to P-register width
      
      // Update predicate register if rename tag matches
      when (pRenameTag === stateFromTagging.pRegs(pIndex).lastIdent) {
        stateNext.pRegs(pIndex).value := io.resultBus.predicate(i).bits.value
      }
      // Clear in-flight bit for this rename tag
      stateNext.pRegs(pIndex).pendingTags := stateFromTagging.pRegs(pIndex).pendingTags & ~UIntToOH(pRenameTag)
    }
  }

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
  io.loopIterations.valid := foundUnreportedLoop
  io.loopIterations.bits := state.loopStates(unreportedLoopLevel).iterations.value
  
  // Mark the loop level as reported in next state
  when (foundUnreportedLoop) {
    stateNext.loopStates(unreportedLoopLevel).reported := true.B
  }




  // Helper function to read A-register and return read info with dependency tracking
  def readAReg(state: State, index: UInt): ATaggedSource = {
    val result = Wire(new ATaggedSource(params))
    
    // Always set addr and tag fields
    val aIndex = index(log2Ceil(params.nARegs)-1, 0)  // Truncate to A-register width
    result.addr := index
    result.tag := state.aRegs(aIndex).lastIdent
    
    // Register 0 always returns 0 (hardwired constant)
    when (index === 0.U) {
      result.resolved := true.B
      result.value := 0.U
    } .otherwise {
      val hasPendingTags = state.aRegs(aIndex).pendingTags.orR
      
      // Return resolved value if no pending writes
      when (!hasPendingTags) {
        result.resolved := true.B
        result.value := state.aRegs(aIndex).value
      } .otherwise {
        // Return unresolved reference with rename tag for dependency tracking
        result.resolved := false.B
        result.value := DontCare
      }
    }
    result
  }

  // Helper function to read D-register and return read info with dependency tracking
  def readDReg(state: State, index: UInt): DTaggedSource = {
    val result = Wire(new DTaggedSource(params))
    
    // Always set addr and tag fields
    val dIndex = index(log2Ceil(params.nDRegs)-1, 0)  // Truncate to D-register width
    result.addr := index
    result.tag := state.dRegs(dIndex).lastIdent
    
    // Register 0 always returns 0 (hardwired constant)
    when (index === 0.U) {
      result.resolved := true.B
      result.value := 0.U
    } .otherwise {
      val hasPendingTags = state.dRegs(dIndex).pendingTags.orR
      
      // Return resolved value if no pending writes
      when (!hasPendingTags) {
        result.resolved := true.B
        result.value := state.dRegs(dIndex).value
      } .otherwise {
        // Return unresolved reference with rename tag for dependency tracking
        result.resolved := false.B
        result.value := DontCare
      }
    }
    result
  }

  def readPReg(state: State, index: UInt): PTaggedSource = {
    val result = Wire(new PTaggedSource(params))
    
    // Always set addr and tag fields
    val pIndex = index(log2Ceil(params.nPRegs)-1, 0)  // Truncate to P-register width
    result.addr := index
    result.tag := state.pRegs(pIndex).lastIdent
    
    // Register 0 always returns true (hardwired constant)
    when (index === 0.U) {
      result.resolved := true.B
      result.value := true.B
    } .otherwise {
      val mostRecentTagPending = state.pRegs(pIndex).pendingTags(state.pRegs(pIndex).lastIdent)
      
      // Return resolved value if most recent tag is not pending
      when (!mostRecentTagPending) {
        result.resolved := true.B
        result.value := state.pRegs(pIndex).value
      } .otherwise {
        // Return unresolved reference - value will be resolved through dependency tracking
        result.resolved := false.B
        result.value := DontCare
      }
    }
    result
  }

  // Helper function to read B-register (can be A-reg or D-reg based on upper bit)
  def readBReg(state: State, index: UInt): BTaggedSource = {
    val result = Wire(new BTaggedSource(params))
    val isDRegRead = index(params.bRegWidth-1)  // Upper bit = 1 for D-registers
    
    when (!isDRegRead) {
      // A-register read - use readAReg and convert to BTaggedSource
      val aRead = readAReg(state, index)
      result.addr := aRead.addr
      result.tag := aRead.tag
      result.resolved := aRead.resolved
      result.value := aRead.value
    } .otherwise {
      // D-register read - use readDReg and convert to BTaggedSource
      val dIndex = index(params.dRegWidth-1, 0)  // Extract lower bits for D-register index
      val dRead = readDReg(state, dIndex)
      result.addr := index  // Keep original address with upper bit set
      result.tag := dRead.tag
      result.resolved := dRead.resolved
      result.value := dRead.value
    }
    result
  }

  // Assign a new rename tag for register write, checking for conflicts
  // Tags increment and wrap around. If the next tag is still pending, we stall.
  def assignWrite(state: State, index: UInt): TagAllocation = {
    val result = Wire(new TagAllocation(params))
    result.writeReg.addr := index
    val isDRegWrite = index(params.bRegWidth-1)  // Upper bit = 1 for D-registers
    result.registers := state
    
    when (!isDRegWrite) {
      // A-register write
      val aIndex = index(log2Ceil(params.nARegs)-1, 0)  // Truncate to A-register width
      val newRenameTag = state.aRegs(aIndex).lastIdent + 1.U
      result.writeReg.tag := newRenameTag
      result.registers.aRegs(aIndex).lastIdent := newRenameTag
      result.registers.aRegs(aIndex).pendingTags := state.aRegs(aIndex).pendingTags | UIntToOH(newRenameTag)
      // Stall if this rename tag is already pending (prevents reuse before completion)
      result.stallRequired := state.aRegs(aIndex).pendingTags(newRenameTag)
    } .otherwise {
      // D-register write
      val dIndex = index(log2Ceil(params.nDRegs)-1, 0)  // Truncate to D-register width
      val newRenameTag = state.dRegs(dIndex).lastIdent + 1.U
      result.writeReg.tag := newRenameTag
      result.registers.dRegs(dIndex).lastIdent := newRenameTag
      result.registers.dRegs(dIndex).pendingTags := state.dRegs(dIndex).pendingTags | UIntToOH(newRenameTag)
      result.stallRequired := state.dRegs(dIndex).pendingTags(newRenameTag)
    }
    result
  }

  // Assign a new rename tag for predicate write
  // Tags increment and wrap around. If the next tag is still pending, we stall.
  def assignPWrite(state: State, index: UInt): PTagAllocation = {
    val result = Wire(new PTagAllocation(params))
    result.writeReg.addr := index
    result.registers := state
    val newRenameTag = state.pRegs(index).lastIdent + 1.U
    result.writeReg.tag := newRenameTag
    result.registers.pRegs(index).lastIdent := newRenameTag
    result.registers.pRegs(index).pendingTags := state.pRegs(index).pendingTags | UIntToOH(newRenameTag)
    // Stall if this rename tag is already pending (prevents reuse before completion)
    result.stallRequired := state.pRegs(index).pendingTags(newRenameTag)
    result
  }
  
}

/** Generator object for creating RegisterFileAndRename modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of RegisterFileAndRename modules with configurable parameters.
  */
object RegisterFileAndRenameGenerator extends fmvpu.ModuleGenerator {
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
