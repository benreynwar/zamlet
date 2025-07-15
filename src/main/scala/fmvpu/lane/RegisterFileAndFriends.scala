package fmvpu.lane

import chisel3._
import chisel3.util._

/**
 * Instruction types
 */
object InstrTypes extends ChiselEnum {
  val Packet = Value(0.U)
  val LdSt = Value(1.U)
  val ALU = Value(2.U)
  val Loop = Value(3.U)
}

/**
 * Loop instruction subtypes
 */
object LoopSubtypes extends ChiselEnum {
  val Control = Value(0.U)
  val Halt = Value(1.U)
  val Reserved2 = Value(2.U)
  val Reserved3 = Value(3.U)
}

/**
 * Loop control modes
 */
object LoopControlModes extends ChiselEnum {
  val StartLoop = Value(0.U)
  val Reserved1 = Value(1.U)
  val Reserved2 = Value(2.U)
  val LoopSize = Value(3.U)
}

/**
 * Write result bundle for register file writes from execution units
 */
class WriteResult(params: LaneParams) extends Bundle {
  val valid = Bool()
  val value = UInt(params.width.W)
  val address = new RegWithIdent(params)
  val force = Bool() // from command packet, bypasses writeIdent system
}

/**
 * State information for a single register in the register file
 */
class RegisterState(params: LaneParams) extends Bundle {
  /** Current value stored in the register */
  val value = UInt(params.width.W)
  
  /** Bit vector indicating which write identifiers are in flight */
  val inFlight = UInt(params.nWriteIdents.W)
  
  /** The last write identifier that was issued for this register */
  val lastIdent = UInt(params.writeIdentWidth.W)
  
  /** True if this register has been written locally (e.g. loop index) */
  val isLocal = Bool()
}

/**
 * Register File and Friends - handles register file, program counter, and instruction dispatch
 * 
 * This module implements:
 * - Register file with write identifier-based renaming
 * - Program counter management with loop support
 * - Instruction dispatch to reservation stations
 * - Register dependency tracking
 */
class RegisterFileAndFriends(params: LaneParams) extends Module {
  val io = IO(new Bundle {
    // Start signals
    val startValid = Input(Bool())
    val startPC = Input(UInt(params.instrAddrWidth.W))
    
    // Instruction input
    val instrValid = Input(Bool())
    val instruction = Input(UInt(16.W)) // 16-bit instruction
    
    // Write inputs from ALU, load/store, and packets
    val writeInputs = Input(Vec(params.nWritePorts, new WriteResult(params)))
    
    
    // Instruction outputs to reservation stations
    val aluInstr = Decoupled(new ALUInstrUnresolved(params))
    val ldstInstr = Decoupled(new LdStInstrUnresolved(params))
    val packetInstr = Decoupled(new PacketInstrUnresolved(params))
    
    // Instruction memory interface
    val imReadValid = Output(Bool())
    val imReadAddress = Output(UInt(params.instrAddrWidth.W))
  })

  // Register file storage
  val registers = Reg(Vec(params.nRegs, new RegisterState(params)))
  // The contents of the registers after new writes have been noted, but write backs haven't
  // been processed
  val registersIntermed = Wire(Vec(params.nRegs, new RegisterState(params)))
  registersIntermed := registers   // Initial value is just the old value

  // Track if last write to accumulator was from MultAcc (for local accumulator optimization)
  val lastAccumWasMultAcc = RegInit(false.B)
  
  // Program counter and loop state
  val pc = RegInit(0.U(params.instrAddrWidth.W))
  val active = RegInit(false.B)
  // We're currently in a loop.
  val loopActive = RegInit(false.B)
  // This is the PC of the first instruction of the loop
  val loopStartPC = Reg(UInt(params.instrAddrWidth.W))
  // This is the PC of the last instruction of the loop
  val loopEndPC = Reg(UInt(params.instrAddrWidth.W))
  // This is high when we are on the last instruction
  val loopLast = RegInit(false.B)
  // This is loopIndex'th time around the loop
  val loopIndex = Reg(UInt(params.width.W))
  // We go around the loop loopLength times
  val loopLength = Reg(UInt(params.width.W))
  // We're waiting for the loopLength to get written to the register file.
  val waitingForLoopLength = RegInit(false.B)

  // Standard instruction format - all instructions use same bit positions for register addresses
  val instrType = io.instruction(15, 14)
  val instrMode = io.instruction(13, 10) // 4 bits for mode + other fields
  val instrMask = io.instruction(9)
  val read1Addr = io.instruction(8, 6)   // Always read 1 address
  val read2Addr = io.instruction(5, 3)   // Always read 2 address  
  val writeAddr = io.instruction(2, 0)   // Always write address
  dontTouch(writeAddr)
  
  val instrTypeEnum = instrType.asTypeOf(InstrTypes())
  val isPacketInstr = instrTypeEnum === InstrTypes.Packet
  val isLdStInstr = instrTypeEnum === InstrTypes.LdSt
  val isALUInstr = instrTypeEnum === InstrTypes.ALU
  val isLoopInstr = instrTypeEnum === InstrTypes.Loop

  // Determine read/write enables based on instruction type
  val read1Enable = Wire(Bool())
  val read2Enable = Wire(Bool())
  val writeEnable = Wire(Bool())
  
  read1Enable := false.B
  read2Enable := false.B
  writeEnable := false.B

  val aluMode = instrMode.asTypeOf(ALUModes())
  val ldstMode = instrMode(1, 0).asTypeOf(LdStModes())
  val packetMode = instrMode(2, 0).asTypeOf(PacketModes())

  val loopSubtype = instrMode(3, 2).asTypeOf(LoopSubtypes())
  val loopMode = instrMode(1, 0).asTypeOf(LoopControlModes())

  when (isALUInstr) {
    read1Enable := true.B  // src1
    read2Enable := true.B  // src2
    writeEnable := true.B  // dst
  } .elsewhen (isLdStInstr) {
    read1Enable := true.B           // offset reg
    read2Enable := ldstMode === LdStModes.Store // store needs src value
    writeEnable := ldstMode === LdStModes.Load // load writes to dst
  } .elsewhen (isPacketInstr) {
    // most modes read target
    read1Enable := packetMode =/= PacketModes.Receive
    // send modes read length
    read2Enable := (packetMode === PacketModes.Send ||
                    packetMode === PacketModes.ForwardAndAppend ||
                    packetMode === PacketModes.ReceiveForwardAndAppend)
    // write the length or the word
    writeEnable := (packetMode === PacketModes.Receive ||
                    packetMode === PacketModes.ReceiveAndForward ||
                    packetMode === PacketModes.GetWord)
  } .elsewhen (isLoopInstr) {
    when (loopSubtype === LoopSubtypes.Control && loopMode === LoopControlModes.StartLoop) {  // Start Loop
      read1Enable := true.B  // length reg
      writeEnable := true.B  // index reg
    }
  }

  // For register 0 (packet output), always increment - order matters for packet assembly
  // For other registers, find first available write identifier

  val nextWriteIdent = Wire(UInt(params.writeIdentWidth.W))
  when(writeAddr === params.packetWordOutRegAddr.U) {
    nextWriteIdent := registers(writeAddr).lastIdent + 1.U
  }.otherwise {
    // Find first available write identifier by checking inFlight bits
    val availableIdents = ~registers(writeAddr).inFlight
    nextWriteIdent := PriorityEncoder(availableIdents)
  }

  // If the reservation stations can't accept the instruction then we stall.
  val stallALU = isALUInstr && !io.aluInstr.ready
  val stallLdSt = isLdStInstr && !io.ldstInstr.ready
  val stallPacket = isPacketInstr && !io.packetInstr.ready
  val stalled = stallALU || stallLdSt || stallPacket
  val fire = io.instrValid && active && !waitingForLoopLength && !stalled

  // Read register data conditionally
  val read1Data = Wire(new RegReadInfo(params))
  val read2Data = Wire(new RegReadInfo(params))
  val dstAddr = Wire(new RegWithIdent(params))
  
  when (fire && writeEnable) {
    dstAddr.regAddr := writeAddr
    dstAddr.writeIdent := nextWriteIdent
    registersIntermed(writeAddr).lastIdent := nextWriteIdent
    registersIntermed(writeAddr).inFlight := registers(writeAddr).inFlight | UIntToOH(nextWriteIdent)
    registersIntermed(writeAddr).isLocal := false.B
  } .otherwise {
    dstAddr := 0.U.asTypeOf(new RegWithIdent(params))
  }
  
  
  // Update register state on writes from execution units
  registers := registersIntermed
  for (i <- 0 until params.nWritePorts) {
    when (io.writeInputs(i).valid) {
      val regAddr = io.writeInputs(i).address.regAddr
      val writeIdent = io.writeInputs(i).address.writeIdent
      val isForceWrite = io.writeInputs(i).force
      
      // Update register value if this matches last ident and not local, OR if it's a force write
      when ((writeIdent === registersIntermed(regAddr).lastIdent && !registersIntermed(regAddr).isLocal) || isForceWrite) {
        registers(regAddr).value := io.writeInputs(i).value
        
        // Reset lastAccumWasMultAcc if force writing to accumulator register
        when (isForceWrite && regAddr === params.accumRegAddr.U) {
          lastAccumWasMultAcc := false.B
        }
      }
      
      // Clear in-flight bit for this write identifier (only for normal writes, not force writes)
      when (!isForceWrite) {
        registers(regAddr).inFlight := registersIntermed(regAddr).inFlight & ~UIntToOH(writeIdent)
      }
    }
  }

  // Program counter update logic
  val nextPC = Wire(UInt(params.instrAddrWidth.W))
  pc := nextPC   // pc is a Register
  nextPC := pc   // The default value for nextPC is pc
  
  // Start signal handling
  when (io.startValid) {
    pc := io.startPC
    active := true.B
    loopActive := false.B
    waitingForLoopLength := false.B
  }
  
  // Default instruction memory interface
  io.imReadValid := active   // Should optimize and make it not always read when active if stalled
  io.imReadAddress := nextPC
  
  
  // Helper function to read register and return RegReadInfo
  def readRegister(addr: UInt): RegReadInfo = {
    val result = Wire(new RegReadInfo(params))
    val regIndex = addr
    
    // Register 0 always returns 0
    when (regIndex === 0.U) {
      result.resolved := true.B
      result.value := 0.U
    } .otherwise {
      val hasInFlight = registers(regIndex).inFlight.orR
      val isLocalReg = registers(regIndex).isLocal
      
      // If no in-flight writes or is local, return resolved data
      when (!hasInFlight || isLocalReg) {
        result.resolved := true.B
        result.value := registers(regIndex).value
      } .otherwise {
        // Return unresolved reference
        result.resolved := false.B
        result.value := Cat(registers(regIndex).lastIdent, regIndex)
      }
    }
    result
  }
  
  when (read1Enable) {
    read1Data := readRegister(read1Addr)
  }.otherwise {
    read1Data.resolved := true.B
    read1Data.value := 0.U
  }
  
  when (read2Enable) {
    read2Data := readRegister(read2Addr)
  } .otherwise {
    read2Data.resolved := true.B
    read2Data.value := 0.U
  }
  

  val zeroRegReadInfo = Wire(new RegReadInfo(params))

  io.aluInstr.valid := false.B // Default overriden later
  io.aluInstr.bits.mode := aluMode
  io.aluInstr.bits.src1 := read1Data
  io.aluInstr.bits.src2 := read2Data
  io.aluInstr.bits.accum := readRegister(params.accumRegAddr.U) // Accumulator register (always read)
  io.aluInstr.bits.mask := Mux(io.instruction(9), readRegister(params.maskRegAddr.U), zeroRegReadInfo) // Mask bit 9
  io.aluInstr.bits.dstAddr := dstAddr
  io.aluInstr.bits.useLocalAccum := lastAccumWasMultAcc && (aluMode === ALUModes.MultAcc)

  zeroRegReadInfo.resolved := true.B
  zeroRegReadInfo.value := 0.U
  io.ldstInstr.valid := false.B
  io.ldstInstr.bits.mode := ldstMode
  io.ldstInstr.bits.baseAddress := Mux(instrMode(2), readRegister(params.baseAddrRegAddr.U), zeroRegReadInfo) // Base address register or 0
  io.ldstInstr.bits.offset := read1Data
  io.ldstInstr.bits.value := read2Data // For stores
  io.ldstInstr.bits.dstAddr := dstAddr
  io.ldstInstr.bits.mask := Mux(io.instruction(9), readRegister(params.maskRegAddr.U), zeroRegReadInfo) // Mask bit 9

  io.packetInstr.valid := false.B
  io.packetInstr.bits.mode := packetMode
  io.packetInstr.bits.target := read1Data
  io.packetInstr.bits.sendLength := read2Data
  io.packetInstr.bits.channel := readRegister(params.channelRegAddr.U) // Channel register
  io.packetInstr.bits.result := dstAddr
  io.packetInstr.bits.forwardAgain := io.instruction(10) // Bit 10 from ISA
  io.packetInstr.bits.mask := Mux(io.instruction(9), readRegister(params.maskRegAddr.U), zeroRegReadInfo) // Mask bit 9
  
  // We process an instruction if the reservation station has room and we're not
  // waiting on a loop length.

  // Instruction dispatch using conditional results
  when (fire) {
    nextPC := pc + 1.U

    // ALU instruction dispatch
    when (isALUInstr) {
      io.aluInstr.valid := true.B
      // Update flag: set if this is MultAcc writing to accumulator
      when (aluMode === ALUModes.MultAcc && dstAddr.regAddr === params.accumRegAddr.U) {
        lastAccumWasMultAcc := true.B
      }
      // Clear flag if any other ALU operation writes to accumulator
      .elsewhen (aluMode =/= ALUModes.MultAcc && dstAddr.regAddr === params.accumRegAddr.U) {
        lastAccumWasMultAcc := false.B
      }
    }

    // Load/Store instruction dispatch
    when (isLdStInstr) {
      io.ldstInstr.valid := true.B
      // Clear MultAcc flag if load writes to accumulator
      when (ldstMode === LdStModes.Load && dstAddr.regAddr === params.accumRegAddr.U) {
        lastAccumWasMultAcc := false.B
      }
    }
    
    // Packet instruction dispatch
    when (isPacketInstr) {
      io.packetInstr.valid := true.B
      // Clear MultAcc flag if packet instruction writes to accumulator
      when ((packetMode === PacketModes.Receive || packetMode === PacketModes.GetWord) && 
            dstAddr.regAddr === params.accumRegAddr.U) {
        lastAccumWasMultAcc := false.B
      }
    }
    
    // Loop instruction handling
    when (isLoopInstr) {
      when (loopSubtype === LoopSubtypes.Control && loopMode === LoopControlModes.StartLoop) {  // Start Loop
        loopStartPC := pc + 1.U
        loopIndex := 0.U
        loopActive := true.B
        waitingForLoopLength := true.B
        // Write loop index to register (local write)
        registers(writeAddr).value := 0.U
        registers(writeAddr).isLocal := true.B
      }
      .elsewhen (loopSubtype === LoopSubtypes.Control && loopMode === LoopControlModes.LoopSize) { // Loop Size
        loopEndPC := loopStartPC + io.instruction(9, 0) // 10-bit loop size
        waitingForLoopLength := false.B
        // Check if loop length register is resolved
        when (read1Data.resolved) {
          loopLength := read1Data.getData
          when (read1Data.getData === 0.U) {
            pc := loopEndPC + 1.U
            loopActive := false.B
          } .otherwise {
            loopLast := read1Data.getData === 1.U
          }
        } .otherwise {
          waitingForLoopLength := true.B
        }
      }
      .elsewhen (loopSubtype === LoopSubtypes.Halt && loopMode === LoopControlModes.StartLoop) { // HALT instruction
        active := false.B
      }
    }
  }
  
  // Handle loop logic
  when (loopActive && pc === loopEndPC && !loopLast) {
    nextPC := loopStartPC
    loopLast := (loopIndex + 1.U) === (loopLength - 1.U)
    loopIndex := loopIndex + 1.U
    
    // Write updated loop index (local write)
    registers(writeAddr).value := loopIndex + 1.U
    registers(writeAddr).isLocal := true.B
    
  } .elsewhen (loopActive && pc === loopEndPC && loopLast) {
    nextPC := pc + 2.U // Jump over End Loop instruction
    loopActive := false.B
  }
  
  // Initialize register file on reset
  when (reset.asBool) {
    for (i <- 0 until params.nRegs) {
      registers(i).value := 0.U
      registers(i).inFlight := 0.U
      registers(i).lastIdent := 0.U
      registers(i).isLocal := false.B
    }
  }
}

/** Generator object for creating RegisterFileAndFriends modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of RegisterFileAndFriends modules with configurable parameters.
  */
object RegisterFileAndFriendsGenerator extends fmvpu.ModuleGenerator {
  /** Create a RegisterFileAndFriends module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return RegisterFileAndFriends module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> RegisterFileAndFriends <laneParamsFileName>")
      null
    } else {
      val params = LaneParams.fromFile(args(0))
      new RegisterFileAndFriends(params)
    }
  }
}
