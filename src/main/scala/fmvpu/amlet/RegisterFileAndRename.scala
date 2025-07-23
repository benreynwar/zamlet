package fmvpu.amlet

import chisel3._
import chisel3.util._
import scala.math.max


class LoopState(params: AmletParams) extends Bundle {
  val start = UInt(params.aWidth.W)
  val index = UInt(params.aWidth.W)
  val resolved = Bool()
  val length = UInt(params.aWidth.W)
}

class TagAllocation(params: AmletParams) extends Bundle {
  // The updated registers.
  val registers = new State(params)
  // The write reg with the assigned rename tag.
  val writeReg = new BTaggedReg(params)
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
  
  /** True if this register has been written locally (e.g. loop index) */
  val isLocal = Bool()
}

class ARegisterState(params: AmletParams) extends Bundle {
  /** Current value stored in the register */
  val value = UInt(params.aWidth.W)
  
  /** Bit vector indicating which rename tags are pending */
  val pendingTags = UInt(params.nWriteIdents.W)
  
  /** The last rename tag that was issued for this register */
  val lastIdent = UInt(params.regTagWidth.W)
  
  /** True if this register has been written locally (e.g. loop index) */
  val isLocal = Bool()
}

class State(params: AmletParams) extends Bundle {
  val dRegs = Vec(params.nDRegs, new DRegisterState(params))
  val aRegs = Vec(params.nARegs, new ARegisterState(params))
  val loopIndices = Vec(params.nLoopLevels, UInt(params.aWidth.W))
  val loopLevel = UInt(log2Ceil(params.nLoopLevels).W)
  val loopActive = Bool()
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

    val instr = Flipped(Decoupled(new VLIWInstr.Base(params)))

    // Write inputs from ALU, load/store, and packets
    val resultBus = Input(Vec(params.nResultPorts, new WriteResult(params)))
    
    // Instruction outputs to reservation stations
    val aluInstr = Decoupled(new ALUInstr.Resolving(params))
    val aluliteInstr = Decoupled(new ALULiteInstr.Resolving(params))
    val ldstInstr = Decoupled(new LoadStoreInstr.Resolving(params))
    val sendPacketInstr = Decoupled(new PacketInstr.SendResolving(params))
    val recvPacketInstr = Decoupled(new PacketInstr.ReceiveResolving(params))
  })

  val stateInitial = Wire(new State(params))
  // Initialize all registers to 0 with no in-flight writes
  for (i <- 0 until params.nDRegs) {
    stateInitial.dRegs(i).value := 0.U
    stateInitial.dRegs(i).pendingTags := 0.U  // No writes currently pending
    stateInitial.dRegs(i).lastIdent := 0.U  // No rename tags issued yet
    stateInitial.dRegs(i).isLocal := false.B  // Not written by local operations (loops)
  }
  for (i <- 0 until params.nARegs) {
    stateInitial.aRegs(i).value := 0.U
    stateInitial.aRegs(i).pendingTags := 0.U
    stateInitial.aRegs(i).lastIdent := 0.U  // No rename tags issued yet
    stateInitial.aRegs(i).isLocal := false.B
  }
  for (i <- 0 until params.nLoopLevels) {
    stateInitial.loopIndices(i) := 0.U
  }
  stateInitial.loopLevel := 0.U
  stateInitial.loopActive := false.B
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

  when (io.instr.valid) {
    switch (io.instr.bits.control.mode) {
      is (ControlInstr.Modes.Loop) {
        // Start a new nested loop level
        val loopLevelNew = Wire(UInt(log2Ceil(params.nLoopLevels).W))
        when (!statePreControl.loopActive) {
          loopLevelNew := 0.U  // First loop starts at level 0
        } .otherwise {
          loopLevelNew := statePreControl.loopLevel + 1.U  // Nested loop
        }
        statePostControl.loopActive := true.B
        statePostControl.loopLevel := loopLevelNew
        statePostControl.loopIndices(loopLevelNew) := 0.U  // Initialize new loop index to 0
      }
      is (ControlInstr.Modes.Incr) {
        // Increment the loop index at the current loop level
        statePostControl.loopIndices(statePreControl.loopLevel) := statePreControl.loopIndices(statePreControl.loopLevel) + 1.U
      }
      is (ControlInstr.Modes.If) {
        // TODO: Need to implement conditional execution
      }
    }
  }

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
      packetSend := false.B
      packetRead1Enable := false.B
      packetRead2Enable := false.B
      packetWriteEnable := true.B
    }
    is (PacketInstr.Modes.ForwardAndAppend) {
      packetReceive := false.B
      packetForward := true.B
      packetAppend := true.B
      packetAppendContinuously := false.B
      packetSend := false.B
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
    is (PacketInstr.Modes.GetPacketWord) {
      packetReceive := false.B
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
      packetAppend := false.B
      packetAppendContinuously := true.B
      packetSend := false.B
      packetRead1Enable := false.B
      packetRead2Enable := false.B
      packetWriteEnable := true.B
    }
    is (PacketInstr.Modes.ForwardAndAppendContinuously) {
      packetReceive := false.B
      packetForward := true.B
      packetAppend := false.B
      packetAppendContinuously := true.B
      packetSend := false.B
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
  val packetTagAlloc = assignWrite(statePrePacket, io.instr.bits.packet.result)
  val packetWriteInfo = packetTagAlloc.writeReg
  // Update register state if packet instruction writes to a register
  when (io.instr.valid && packetWriteEnable) {
    statePostPacket := packetTagAlloc.registers
  } .otherwise {
    statePostPacket := statePrePacket
  }

  // Send
  io.sendPacketInstr.valid := io.instr.valid && packetSend
  io.sendPacketInstr.bits.mode := io.instr.bits.packet.mode
  io.sendPacketInstr.bits.length := packetReadLength
  io.sendPacketInstr.bits.target := packetReadTarget
  io.sendPacketInstr.bits.result := packetWriteInfo
  io.sendPacketInstr.bits.channel := io.instr.bits.packet.channel
  io.sendPacketInstr.bits.mask := DontCare

  // Receive
  io.recvPacketInstr.valid := io.instr.valid && packetReceive
  io.recvPacketInstr.bits.mode := io.instr.bits.packet.mode
  io.recvPacketInstr.bits.result := packetWriteInfo
  io.recvPacketInstr.bits.target := DontCare
  io.recvPacketInstr.bits.mask := DontCare


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

  // For load operations, allocate a rename tag for the destination register
  val ldstTagAlloc = assignWrite(statePreLdSt, io.instr.bits.loadStore.reg)
  val ldstWriteInfo = ldstTagAlloc.writeReg

  // Update register state if load operation writes to a register
  when (io.instr.valid && isLoadOp) {
    statePostLdSt := ldstTagAlloc.registers
  } .otherwise {
    statePostLdSt := statePreLdSt
  }

  // Output to load/store reservation station
  io.ldstInstr.valid := io.instr.valid && isLdStValid
  io.ldstInstr.bits.mode := io.instr.bits.loadStore.mode
  io.ldstInstr.bits.addr := ldstReadAddress
  io.ldstInstr.bits.src := ldstReadData
  io.ldstInstr.bits.dst := ldstWriteInfo
  io.ldstInstr.bits.mask := DontCare

  // 3) ALU Processing
  // -----------------
  val statePreALU = Wire(new State(params))
  val statePostALU = Wire(new State(params))
  statePostALU := statePreALU

  // Determine if this is a valid ALU operation
  val isALUValid = io.instr.bits.alu.mode =/= ALUInstr.Modes.None

  // Read operands for ALU operations
  val aluReadSrc1 = readDReg(statePreALU, io.instr.bits.alu.src1)
  val aluReadSrc2 = readDReg(statePreALU, io.instr.bits.alu.src2)

  // Allocate a rename tag for the destination register
  val aluTagAlloc = assignWrite(statePreALU, io.instr.bits.alu.dst)
  val aluWriteInfo = aluTagAlloc.writeReg

  // Update register state for ALU write
  when (io.instr.valid && isALUValid) {
    statePostALU := aluTagAlloc.registers
  } .otherwise {
    statePostALU := statePreALU
  }

  // Output to ALU reservation station
  io.aluInstr.valid := io.instr.valid && isALUValid
  io.aluInstr.bits.mode := io.instr.bits.alu.mode
  io.aluInstr.bits.src1 := aluReadSrc1
  io.aluInstr.bits.src2 := aluReadSrc2
  io.aluInstr.bits.dst := aluWriteInfo
  io.aluInstr.bits.mask := DontCare

  // 4) ALULite Processing
  // -----------------
  val statePreALULite = Wire(new State(params))
  val statePostALULite = Wire(new State(params))
  statePostALULite := statePreALULite

  // Determine if this is a valid ALULite operation
  val isALULiteValid = io.instr.bits.aluLite.mode =/= ALULiteInstr.Modes.None

  // Read operands for ALULite operations (uses A-registers)
  val aluliteReadSrc1 = readAReg(statePreALULite, io.instr.bits.aluLite.src1)
  val aluliteReadSrc2 = readAReg(statePreALULite, io.instr.bits.aluLite.src2)

  // Allocate a rename tag for the destination register
  val aluliteTagAlloc = assignWrite(statePreALULite, io.instr.bits.aluLite.dst)
  val aluliteWriteInfo = aluliteTagAlloc.writeReg

  // Update register state for ALULite write
  when (io.instr.valid && isALULiteValid) {
    statePostALULite := aluliteTagAlloc.registers
  } .otherwise {
    statePostALULite := statePreALULite
  }

  // Output to ALULite reservation station
  io.aluliteInstr.valid := io.instr.valid && isALULiteValid
  io.aluliteInstr.bits.mode := io.instr.bits.aluLite.mode
  io.aluliteInstr.bits.src1 := aluliteReadSrc1
  io.aluliteInstr.bits.src2 := aluliteReadSrc2
  io.aluliteInstr.bits.dst := aluliteWriteInfo
  io.aluliteInstr.bits.mask := DontCare

  // If the reservation stations can't accept the instruction then we stall.
  val blockedALU = isALUValid && aluTagAlloc.stallRequired
  val blockedLdSt = isLoadOp && ldstTagAlloc.stallRequired
  val blockedALULite = isALULiteValid && aluliteTagAlloc.stallRequired
  val blockedPacket = packetWriteEnable && packetTagAlloc.stallRequired

  val hasALUInstr = io.instr.bits.alu.mode =/= ALUInstr.Modes.None
  val hasLdStInstr = io.instr.bits.loadStore.mode =/= LoadStoreInstr.Modes.None
  val hasALULiteInstr = io.instr.bits.aluLite.mode =/= ALULiteInstr.Modes.None  
  val hasPacketInstr = io.instr.bits.packet.mode =/= PacketInstr.Modes.Null

  val stallALU = hasALUInstr && (!io.aluInstr.ready || blockedALU)
  val stallLdSt = hasLdStInstr && (!io.ldstInstr.ready || blockedLdSt)
  val stallPacket = hasPacketInstr && ((!io.sendPacketInstr.ready && packetSend) || (!io.recvPacketInstr.ready && packetReceive) || blockedPacket)
  val stallALULite = hasALULiteInstr && (!io.aluliteInstr.ready || blockedALULite)
  io.instr.ready := !stallALU && !stallALULite && !stallLdSt && !stallPacket
  val fire = io.instr.valid && io.instr.ready

  // Chain register state updates through all instruction types
  val stateFromTagging = Wire(new State(params))
  statePreControl := state // Start with current register state
  statePrePacket := statePostControl 
  statePreLdSt := statePostPacket  // Load/store sees packet updates
  statePreALU := statePostLdSt     // ALU sees load/store updates  
  statePreALULite := statePostALU  // ALULite sees ALU updates
  stateFromTagging := statePostALULite  // Final state after all instruction processing

  when (fire) {
    // Update the state
    stateNext := stateFromTagging
  } .otherwise {
    stateNext := state
  }
  
  // Update register state on writes from execution units
  for (i <- 0 until params.nResultPorts) {
    when (io.resultBus(i).valid) {
      val regAddr = io.resultBus(i).address.addr
      val renameTag = io.resultBus(i).address.tag
      val isForceWrite = io.resultBus(i).force
      val cutoff = max(params.nARegs, params.nDRegs)
      
      when (regAddr <  cutoff.U) {
        // A-register write: only update if rename tag matches expected or force write
        val aIndex = regAddr(log2Ceil(params.nARegs)-1, 0)  // Truncate to A-register width
        when ((renameTag === stateFromTagging.aRegs(aIndex).lastIdent && !stateFromTagging.aRegs(aIndex).isLocal) || isForceWrite) {
          stateNext.aRegs(aIndex).value := io.resultBus(i).value
        }
        // Clear in-flight bit for this rename tag (normal writes only)
        when (!isForceWrite) {
          stateNext.aRegs(aIndex).pendingTags := stateFromTagging.aRegs(aIndex).pendingTags & ~UIntToOH(renameTag)
        }
      } .otherwise {
        // D-register write: same logic as A-registers
        val dIndex = regAddr(log2Ceil(params.nDRegs)-1, 0)  // Truncate to D-register width
        when ((renameTag === stateFromTagging.dRegs(dIndex).lastIdent && !stateFromTagging.dRegs(dIndex).isLocal) || isForceWrite) {
          stateNext.dRegs(dIndex).value := io.resultBus(i).value
        }
        when (!isForceWrite) {
          stateNext.dRegs(dIndex).pendingTags := stateFromTagging.dRegs(dIndex).pendingTags & ~UIntToOH(renameTag)
        }
      }
    }
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
      val isLocalReg = state.aRegs(aIndex).isLocal
      
      // Return resolved value if no pending writes or register is written locally (loop indices)
      when (!hasPendingTags || isLocalReg) {
        result.resolved := true.B
        result.value := state.aRegs(aIndex).value
      } .otherwise {
        // Return unresolved reference with rename tag for dependency tracking
        result.resolved := false.B
        result.value := Cat(state.aRegs(aIndex).lastIdent, index)
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
      val isLocalReg = state.dRegs(dIndex).isLocal
      
      // Return resolved value if no pending writes or register is written locally (loop indices)
      when (!hasPendingTags || isLocalReg) {
        result.resolved := true.B
        result.value := state.dRegs(dIndex).value
      } .otherwise {
        // Return unresolved reference with rename tag for dependency tracking
        result.resolved := false.B
        result.value := Cat(state.dRegs(dIndex).lastIdent, index)
      }
    }
    result
  }

  // Helper function to read B-register (can be A-reg or D-reg based on upper bit)
  def readBReg(state: State, index: UInt): BTaggedSource = {
    val result = Wire(new BTaggedSource(params))
    val cutoff = max(params.nARegs, params.nDRegs)
    
    when (index < cutoff.U) {
      // A-register read - use readAReg and convert to BTaggedSource
      val aRead = readAReg(state, index)
      result.addr := aRead.addr
      result.tag := aRead.tag
      result.resolved := aRead.resolved
      result.value := aRead.value
    } .otherwise {
      // D-register read - use readDReg and convert to BTaggedSource
      val dRead = readDReg(state, index)
      result.addr := dRead.addr
      result.tag := dRead.tag
      result.resolved := dRead.resolved
      result.value := dRead.value
    }
    result
  }

  // Assign a new rename tag for register write, checking for conflicts
  def assignWrite(state: State, index: UInt): TagAllocation = {
    val result = Wire(new TagAllocation(params))
    result.writeReg.addr := index
    val cutoff = max(params.nARegs, params.nDRegs)
    result.registers := state
    
    when (index < cutoff.U) {
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
      println("Usage: <command> <outputDir> RegisterFileAndRename <laneParamsFileName>")
      null
    } else {
      val params = AmletParams.fromFile(args(0))
      new RegisterFileAndRename(params)
    }
  }
}
