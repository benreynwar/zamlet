package fmvpu.lane

import chisel3._
import chisel3.util._

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
  
  // Track if last write to accumulator was from MultAcc (for local accumulator optimization)
  val lastAccumWasMultAcc = RegInit(false.B)
  
  // Program counter and loop state
  val pc = RegInit(0.U(params.instrAddrWidth.W))
  val active = RegInit(false.B)
  val loopActive = RegInit(false.B)
  val loopStartPC = Reg(UInt(params.instrAddrWidth.W))
  val loopEndPC = Reg(UInt(params.instrAddrWidth.W))
  val loopLast = RegInit(false.B)
  val loopIndex = Reg(UInt(params.width.W))
  val loopLength = Reg(UInt(params.width.W))
  val waitingForLoopLength = RegInit(false.B)
  val cancelNextInstr = RegInit(false.B)

  // Standard instruction format - all instructions use same bit positions for register addresses
  val instrType = io.instruction(15, 14)
  val instrMode = io.instruction(13, 10) // 4 bits for mode + other fields
  val instrMask = io.instruction(9)
  val read1Addr = io.instruction(8, 6)   // Always read 1 address
  val read2Addr = io.instruction(5, 3)   // Always read 2 address  
  val writeAddr = io.instruction(2, 0)   // Always write address
  
  val isPacketInstr = instrType === 0.U
  val isLdStInstr = instrType === 1.U
  val isALUInstr = instrType === 2.U
  val isLoopInstr = instrType === 3.U
  
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
  
  // Helper function to issue a new write and update register state
  def issueWrite(regAddr: UInt): RegWithIdent = {
    val result = Wire(new RegWithIdent(params))

    // For register 0 (packet output), always increment - order matters for packet assembly
    // For other registers, find first available write identifier
    val nextIdent = Wire(UInt(params.writeIdentWidth.W))
    when(regAddr === params.packetWordOutRegAddr.U) {
      nextIdent := registers(regAddr).lastIdent + 1.U
    }.otherwise {
      // Find first available write identifier by checking inFlight bits
      val availableIdents = ~registers(regAddr).inFlight
      nextIdent := PriorityEncoder(availableIdents)
    }
    
    result.regAddr := regAddr
    result.writeIdent := nextIdent
    
    // Update register state - always update lastIdent for dependency tracking
    registers(regAddr).lastIdent := nextIdent
    registers(regAddr).inFlight := registers(regAddr).inFlight | UIntToOH(nextIdent)
    registers(regAddr).isLocal := false.B
    
    result
  }
  
  // Update register state on writes from execution units
  for (i <- 0 until params.nWritePorts) {
    when (io.writeInputs(i).valid) {
      val regAddr = io.writeInputs(i).address.regAddr
      val writeIdent = io.writeInputs(i).address.writeIdent
      
      // Update register value if this matches last ident and not local
      when (writeIdent === registers(regAddr).lastIdent && !registers(regAddr).isLocal) {
        registers(regAddr).value := io.writeInputs(i).value
      }
      
      // Clear in-flight bit for this write identifier
      registers(regAddr).inFlight := registers(regAddr).inFlight & ~UIntToOH(writeIdent)
    }
  }
  
  // Start signal handling
  when (io.startValid) {
    pc := io.startPC
    active := true.B
    loopActive := false.B
    waitingForLoopLength := false.B
  }
  
  // Default instruction memory interface
  io.imReadValid := active && !waitingForLoopLength && !cancelNextInstr
  io.imReadAddress := pc
  
  // Default instruction outputs
  io.aluInstr.valid := false.B
  io.aluInstr.bits.mode := ALUModes.Add
  io.aluInstr.bits.src1.resolved := true.B
  io.aluInstr.bits.src1.value := 0.U
  io.aluInstr.bits.src2.resolved := true.B
  io.aluInstr.bits.src2.value := 0.U
  io.aluInstr.bits.accum.resolved := true.B
  io.aluInstr.bits.accum.value := 0.U
  io.aluInstr.bits.mask.resolved := true.B
  io.aluInstr.bits.mask.value := 1.U
  io.aluInstr.bits.dstAddr.regAddr := 0.U
  io.aluInstr.bits.dstAddr.writeIdent := 0.U
  io.aluInstr.bits.useLocalAccum := false.B
  
  io.ldstInstr.valid := false.B
  io.ldstInstr.bits.mode := LdStModes.Load
  io.ldstInstr.bits.baseAddress.resolved := true.B
  io.ldstInstr.bits.baseAddress.value := 0.U
  io.ldstInstr.bits.offset.resolved := true.B
  io.ldstInstr.bits.offset.value := 0.U
  io.ldstInstr.bits.dstAddr.regAddr := 0.U
  io.ldstInstr.bits.dstAddr.writeIdent := 0.U
  io.ldstInstr.bits.value.resolved := true.B
  io.ldstInstr.bits.value.value := 0.U
  
  io.packetInstr.valid := false.B
  io.packetInstr.bits.mode := PacketModes.Receive
  io.packetInstr.bits.target.resolved := true.B
  io.packetInstr.bits.target.value := 0.U
  io.packetInstr.bits.result.regAddr := 0.U
  io.packetInstr.bits.result.writeIdent := 0.U
  io.packetInstr.bits.sendLength.resolved := true.B
  io.packetInstr.bits.sendLength.value := 0.U
  io.packetInstr.bits.channel.resolved := true.B
  io.packetInstr.bits.channel.value := 0.U
  
  // Instruction processing
  val canProcess = io.instrValid && active && !cancelNextInstr && !waitingForLoopLength
  val stallALU = isALUInstr && !io.aluInstr.ready
  val stallLdSt = isLdStInstr && !io.ldstInstr.ready
  val stallPacket = isPacketInstr && !io.packetInstr.ready
  val stalled = stallALU || stallLdSt || stallPacket
  
  // Determine read/write enables based on instruction type
  val read1Enable = Wire(Bool())
  val read2Enable = Wire(Bool())
  val writeEnable = Wire(Bool())
  
  read1Enable := false.B
  read2Enable := false.B
  writeEnable := false.B
  
  when (isALUInstr) {
    read1Enable := true.B  // src1
    read2Enable := true.B  // src2
    writeEnable := true.B  // dst
  } .elsewhen (isLdStInstr) {
    val ldstMode = instrMode(1, 0)
    read1Enable := true.B           // offset reg
    read2Enable := ldstMode === 1.U // store needs src value
    writeEnable := ldstMode === 0.U // load writes to dst
  } .elsewhen (isPacketInstr) {
    val packetMode = instrMode(2, 0)
    read1Enable := packetMode =/= 0.U  // most modes read target
    read2Enable := packetMode === 4.U || packetMode === 3.U || packetMode === 2.U  // send modes read length
    writeEnable := packetMode === 0.U || packetMode === 1.U || packetMode === 5.U  // receive/get_word write result
  } .elsewhen (isLoopInstr) {
    val loopSubtype = instrMode(3, 2)
    val loopMode = instrMode(1, 0)
    when (loopSubtype === 0.U && loopMode === 0.U) {  // Start Loop
      read1Enable := true.B  // length reg
      writeEnable := true.B  // index reg
    }
  }
  
  // Read register data conditionally
  val read1Data = Wire(new RegReadInfo(params))
  val read2Data = Wire(new RegReadInfo(params))
  val dstAddr = Wire(new RegWithIdent(params))
  
  // Default values
  read1Data := 0.U.asTypeOf(new RegReadInfo(params))
  read2Data := 0.U.asTypeOf(new RegReadInfo(params))
  dstAddr := 0.U.asTypeOf(new RegWithIdent(params))
  
  when (read1Enable) {
    read1Data := readRegister(read1Addr)
  }
  
  when (read2Enable) {
    read2Data := readRegister(read2Addr)
  }
  
  when (writeEnable) {
    dstAddr := issueWrite(writeAddr)
  }
  
  // Instruction dispatch using conditional results
  when (canProcess && !stalled) {
    // ALU instruction dispatch
    when (isALUInstr) {
      val aluMode = instrMode.asTypeOf(ALUModes())
      
      io.aluInstr.valid := true.B
      io.aluInstr.bits.mode := aluMode
      io.aluInstr.bits.src1 := read1Data
      io.aluInstr.bits.src2 := read2Data
      io.aluInstr.bits.accum := readRegister(params.accumRegAddr.U) // Accumulator register (always read)
      io.aluInstr.bits.mask := readRegister(params.maskRegAddr.U) // Mask register (always read)
      io.aluInstr.bits.dstAddr := dstAddr
      io.aluInstr.bits.useLocalAccum := lastAccumWasMultAcc && (aluMode === ALUModes.MultAcc)
      
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
      val ldstMode = instrMode(1, 0).asTypeOf(LdStModes())
      val useBase = instrMode(2)
      val zeroRegReadInfo = Wire(new RegReadInfo(params))
      zeroRegReadInfo.resolved := true.B
      zeroRegReadInfo.value := 0.U
      
      io.ldstInstr.valid := true.B
      io.ldstInstr.bits.mode := ldstMode
      io.ldstInstr.bits.baseAddress := Mux(useBase, readRegister(params.baseAddrRegAddr.U), zeroRegReadInfo) // Base address register or 0
      io.ldstInstr.bits.offset := read1Data
      io.ldstInstr.bits.value := read2Data // For stores
      io.ldstInstr.bits.dstAddr := dstAddr
      
      // Clear MultAcc flag if load writes to accumulator
      when (ldstMode === LdStModes.Load && dstAddr.regAddr === params.accumRegAddr.U) {
        lastAccumWasMultAcc := false.B
      }
    }
    
    // Packet instruction dispatch
    when (isPacketInstr) {
      val packetMode = instrMode(2, 0).asTypeOf(PacketModes())
      
      io.packetInstr.valid := true.B
      io.packetInstr.bits.mode := packetMode
      io.packetInstr.bits.target := read1Data
      io.packetInstr.bits.sendLength := read2Data
      io.packetInstr.bits.channel := readRegister(params.channelRegAddr.U) // Channel register
      io.packetInstr.bits.result := dstAddr
      
      // Clear MultAcc flag if packet instruction writes to accumulator
      when ((packetMode === PacketModes.Receive || packetMode === PacketModes.GetPacketWord) && 
            dstAddr.regAddr === params.accumRegAddr.U) {
        lastAccumWasMultAcc := false.B
      }
    }
    
    // Loop instruction handling
    when (isLoopInstr) {
      val loopSubtype = instrMode(3, 2)
      val loopMode = instrMode(1, 0)
      
      when (loopSubtype === 0.U && loopMode === 0.U) {  // Start Loop
        loopStartPC := pc + 1.U
        loopIndex := 0.U
        loopActive := true.B
        waitingForLoopLength := true.B
        
        // Write loop index to register (local write)
        registers(writeAddr).value := 0.U
        registers(writeAddr).isLocal := true.B
      }
      .elsewhen (loopSubtype === 0.U && loopMode === 3.U) { // Loop Size
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
      .elsewhen (loopSubtype === 1.U && loopMode === 0.U) { // HALT instruction
        active := false.B
      }
    }
  }
  
  // Program counter update logic
  val nextPC = Wire(UInt(params.instrAddrWidth.W))
  nextPC := pc + 1.U
  
  // Handle loop logic
  when (loopActive && pc === loopEndPC && !loopLast) {
    nextPC := loopStartPC
    loopLast := (loopIndex + 1.U) === (loopLength - 1.U)
    loopIndex := loopIndex + 1.U
    
    // Write updated loop index (local write)
    registers(writeAddr).value := loopIndex + 1.U
    registers(writeAddr).isLocal := true.B
    
    cancelNextInstr := true.B
  } .elsewhen (loopActive && pc === loopEndPC && loopLast) {
    nextPC := pc + 2.U // Jump over End Loop instruction
    loopActive := false.B
  }
  
  // Update PC when not stalled and active
  when (active && !stalled && !waitingForLoopLength) {
    pc := nextPC
  }
  
  // Clear cancel flag
  when (cancelNextInstr) {
    cancelNextInstr := false.B
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
