package fmvpu.gamlet

import chisel3._
import chisel3.util._
import fmvpu.famlet._
import io.circe._
import io.circe.generic.auto._
import io.circe.generic.semiauto._

case class RenameParams(
  // Input and output registration controls
  registerInput: Boolean = true,
  registerOutput: Boolean = true,
  registerNotices: Boolean = true
)

object RenameParams {
  // Explicit decoder for RenameParams
  implicit val renameParamsDecoder: Decoder[RenameParams] = deriveDecoder[RenameParams]
}

// - A-Reg logical to physical mapping
// - D-Reg logical to physical mapping
// - For each physical reg
//     - is live
//     - number of outstanding reads
// - Number of available physical regs
// - 4 available phyiscal A-Reg
// - 4 available phyiscal D-Reg

class RenameState(params: FamletParams) extends Bundle {
  val aRegMap = Vec(params.nARegs, params.aPhysReg())
  val dRegMap = Vec(params.nDRegs, params.dPhysReg())

  val nAvailAPhysRegs = UInt(log2Ceil(params.nAPhysRegs+1).W)
  val nAvailDPhysRegs = UInt(log2Ceil(params.nAPhysRegs+1).W)
  // A-PhysRegs that are known to be available.
  val availAPhysRegs = Vec(params.nAWritePorts, params.aPhysReg())
  // D-PhysRegs that are known to be available.
  val availDPhysRegs = Vec(params.nDWritePorts, params.dPhysReg())

  val aIsLive = Vec(params.nAPhysRegs, Bool())
  val dIsLive = Vec(params.nDPhysRegs, Bool())
  val aPendingReads = Vec(params.nAPhysRegs, UInt(params.pendingReadsWidth.W))
  val dPendingReads = Vec(params.nDPhysRegs, UInt(params.pendingReadsWidth.W))
}

class AReadUpdate(params: FamletParams) extends Bundle {
  val state = new RenameState(params)
  val addr = params.aPhysReg()
}

class DReadUpdate(params: FamletParams) extends Bundle {
  val state = new RenameState(params)
  val addr = params.dPhysReg()
}

class AWriteUpdate(params: FamletParams) extends Bundle {
  val state = new RenameState(params)
  val addr = params.aPhysReg()
  val failed = Bool()
}

class DWriteUpdate(params: FamletParams) extends Bundle {
  val state = new RenameState(params)
  val addr = params.dPhysReg()
  val failed = Bool()
}

class BWriteUpdate(params: FamletParams) extends Bundle {
  val state = new RenameState(params)
  val addr = params.bPhysReg()
  val failed = Bool()
}

object RenameHelpers {

  def updateWithARead(params: FamletParams)(state: RenameState, enable: Bool, addr: UInt): AReadUpdate = {
    val newState = Wire(new RenameState(params))
    newState := state
    val physAddr = state.aRegMap(addr)
    when (enable) {
      // FIXME: Handle overflow
      newState.aPendingReads(physAddr) := state.aPendingReads(physAddr) + 1.U
    }
    val result = Wire(new AReadUpdate(params))
    result.state := newState
    result.addr := physAddr
    result
  }
  
  def updateWithDRead(params: FamletParams)(state: RenameState, enable: Bool, addr: UInt): DReadUpdate = {
    val newState = Wire(new RenameState(params))
    newState := state
    val physAddr = state.dRegMap(addr)
    when (enable) {
      // FIXME: Handle overflow
      newState.dPendingReads(physAddr) := state.dPendingReads(physAddr) + 1.U
    }
    val result = Wire(new DReadUpdate(params))
    result.state := newState
    result.addr := physAddr
    result
  }
  
  def updateWithAWrite(params: FamletParams)(state: RenameState, enable: Bool, addr: UInt): AWriteUpdate = {
    val newState = Wire(new RenameState(params))
    newState := state
    // We need to assign a new physical address.
    val oldPhysAddr = state.aRegMap(addr)
    val physAddr = Wire(params.aPhysReg())
    val failed = Wire(Bool())
    when (state.nAvailAPhysRegs >= params.nAWritePorts.U) {
      physAddr := state.availAPhysRegs(params.nAWritePorts-1)
      failed := false.B
    } .elsewhen (state.nAvailAPhysRegs === 0.U) {
      physAddr := DontCare
      failed := true.B
    } .otherwise {
      physAddr := state.availAPhysRegs(state.nAvailAPhysRegs-1.U)
      failed := false.B
    }
    when (enable && !failed) {
      newState.aIsLive(oldPhysAddr) := false.B
      newState.aRegMap(addr) := physAddr
      newState.aIsLive(physAddr) := true.B
      newState.aPendingReads(physAddr) := 0.U
      newState.nAvailAPhysRegs := state.nAvailAPhysRegs - 1.U
    }
    val result = Wire(new AWriteUpdate(params))
    result.state := newState
    result.addr := physAddr
    result.failed := failed
    result
  }
  
  def updateWithDWrite(params: FamletParams)(state: RenameState, enable: Bool, addr: UInt): DWriteUpdate = {
    val newState = Wire(new RenameState(params))
    newState := state
    // We need to assign a new physical address.
    val oldPhysAddr = state.dRegMap(addr)
    val physAddr = Wire(params.dPhysReg())
    val failed = Wire(Bool())
    when (state.nAvailDPhysRegs >= params.nDWritePorts.U) {
      physAddr := state.availDPhysRegs(params.nDWritePorts-1)
      failed := false.B
    } .elsewhen (state.nAvailDPhysRegs === 0.U) {
      physAddr := DontCare
      failed := true.B
    } .otherwise {
      physAddr := state.availDPhysRegs(state.nAvailDPhysRegs-1.U)
      failed := false.B
    }
    when (enable && !failed) {
      newState.dIsLive(oldPhysAddr) := false.B
      newState.dRegMap(addr) := physAddr
      newState.dIsLive(physAddr) := true.B
      newState.dPendingReads(physAddr) := 0.U
      newState.nAvailDPhysRegs := state.nAvailDPhysRegs - 1.U
    }
    val result = Wire(new DWriteUpdate(params))
    result.state := newState
    result.addr := physAddr
    result.failed := failed
    result
  }
  
  class BReadUpdate(params: FamletParams) extends Bundle {
    val state = new RenameState(params)
    val addr = params.bPhysReg()
  }
  
  def updateWithBRead(params: FamletParams)(state: RenameState, enable: Bool, addr: UInt): BReadUpdate = {
    val result = Wire(new BReadUpdate(params))
    when (addr(params.bRegWidth-1)) {
      val dResult = RenameHelpers.updateWithDRead(params)(state, enable, addr(params.dRegWidth-1, 0))
      result.state := dResult.state
      result.addr := dResult.addr | (1.U << (params.bPhysRegWidth-1).U)
    } .otherwise {
      val aResult = RenameHelpers.updateWithARead(params)(state, enable, addr(params.aRegWidth-1, 0))
      result.state := aResult.state
      result.addr := aResult.addr
    }
    result
  }
  
  def updateWithBWrite(params: FamletParams)(state: RenameState, enable: Bool, addr: UInt): BWriteUpdate = {
    val result = Wire(new BWriteUpdate(params))
    when (addr(params.bRegWidth-1)) {
      val dResult = RenameHelpers.updateWithDWrite(params)(state, enable, addr(params.dRegWidth-1, 0))
      result.state := dResult.state
      result.failed := dResult.failed
      result.addr := dResult.addr | (1.U << (params.bPhysRegWidth-1).U)
    } .otherwise {
      val aResult = RenameHelpers.updateWithAWrite(params)(state, enable, addr(params.aRegWidth-1, 0))
      result.state := aResult.state
      result.failed := aResult.failed
      result.addr := aResult.addr
    }
    result
  }

}

class Rename(params: GamletParams) extends Module {
  val io = IO(new Bundle {
    val input = Input(Valid(new VLIWInstr.Expanded(params.famlet)))
    val output = Output(Valid(new VLIWInstr.Renamed(params.famlet)))

    val notices = Input(Vec(params.nFamlets, new NoticeBus(params.famlet)))
  })
  
  // Optional input registration
  val inputStage = if (params.rename.registerInput) {
    RegNext(io.input)
  } else {
    io.input
  }
  
  // Optional notices registration
  val noticesStage = if (params.rename.registerNotices) {
    RegNext(io.notices)
  } else {
    io.notices
  }
  
  val stateInit = Wire(new RenameState(params.famlet))
  // Initialize register mappings - logical register N maps to physical register N initially
  for (i <- 0 until params.famlet.nARegs) {
    stateInit.aRegMap(i) := i.U
  }
  for (i <- 0 until params.famlet.nDRegs) {
    stateInit.dRegMap(i) := i.U
  }
  stateInit.nAvailAPhysRegs := (params.famlet.nAPhysRegs - params.famlet.nARegs).U
  stateInit.nAvailDPhysRegs := (params.famlet.nDPhysRegs - params.famlet.nDRegs).U
  // Initialize available physical registers (starting from the first unused ones)
  for (i <- 0 until params.famlet.nAWritePorts) {
    stateInit.availAPhysRegs(i) := (params.famlet.nARegs + i).U
  }
  for (i <- 0 until params.famlet.nDWritePorts) {
    stateInit.availDPhysRegs(i) := (params.famlet.nDRegs + i).U
  }
  // Mark initial physical registers as live, rest as not live
  for (i <- 0 until params.famlet.nAPhysRegs) {
    stateInit.aIsLive(i) := (i < params.famlet.nARegs).B
  }
  for (i <- 0 until params.famlet.nDPhysRegs) {
    stateInit.dIsLive(i) := (i < params.famlet.nDRegs).B
  }
  // Initialize pending reads to 0
  for (i <- 0 until params.famlet.nAPhysRegs) {
    stateInit.aPendingReads(i) := 0.U
  }
  for (i <- 0 until params.famlet.nDPhysRegs) {
    stateInit.dPendingReads(i) := 0.U
  }

  val stateNext = Wire(new RenameState(params.famlet))
  val state = RegNext(stateNext, stateInit)

  // Create intermediate output stage  
  val outputStage = Wire(Valid(new VLIWInstr.Renamed(params.famlet)))

  // Control
  // Reads: Iterations
  // Writes: Loop Index
  val statePreControl = Wire(new RenameState(params.famlet))
  val controlReadUpdate = RenameHelpers.updateWithARead(params.famlet)(
    statePreControl, inputStage.bits.control.iterationsReadEnable(), inputStage.bits.control.iterations.addr)
  val controlWriteUpdate = RenameHelpers.updateWithAWrite(params.famlet)(
    controlReadUpdate.state, inputStage.bits.control.writeEnable(), inputStage.bits.control.dst)
  val statePostControl = controlWriteUpdate.state

  val stallControl = controlWriteUpdate.failed
  outputStage.bits.control := inputStage.bits.control.rename(controlReadUpdate.addr, controlWriteUpdate.addr)

  // Predicate
  // Reads: src2
  // Writes: dst (but predicates don't have physical registers, so this is a pass-through)
  val statePrePredicate = Wire(new RenameState(params.famlet))
  val predicateReadUpdate = RenameHelpers.updateWithARead(params.famlet)(
    statePrePredicate, true.B, inputStage.bits.predicate.src2)
  val statePostPredicate = predicateReadUpdate.state

  val stallPredicate = false.B // Predicates don't allocate physical registers
  outputStage.bits.predicate := inputStage.bits.predicate.rename(predicateReadUpdate.addr)

  // ALU
  // Reads: src1, src2, old (if predicated)
  // Writes: dst
  val statePreALU = Wire(new RenameState(params.famlet))
  val aluReadSrc1Update = RenameHelpers.updateWithDRead(params.famlet)(
    statePreALU, inputStage.bits.alu.src1ReadEnable(), inputStage.bits.alu.src1)
  val aluReadSrc2Update = RenameHelpers.updateWithDRead(params.famlet)(
    aluReadSrc1Update.state, inputStage.bits.alu.src2ReadEnable(), inputStage.bits.alu.src2)
  val aluReadOldUpdate = RenameHelpers.updateWithBRead(params.famlet)(
    aluReadSrc2Update.state, inputStage.bits.alu.oldReadEnable(), inputStage.bits.alu.dst)
  val aluWriteUpdate = RenameHelpers.updateWithBWrite(params.famlet)(
    aluReadOldUpdate.state, inputStage.bits.alu.writeEnable(), inputStage.bits.alu.dst)
  val statePostALU = aluWriteUpdate.state

  val stallALU = aluWriteUpdate.failed
  outputStage.bits.alu := inputStage.bits.alu.rename(aluReadSrc1Update.addr, aluReadSrc2Update.addr, aluReadOldUpdate.addr, aluWriteUpdate.addr)

  // ALULite
  // Reads: src1, src2 (A-registers), old (if predicated)
  // Writes: dst
  val statePreALULite = Wire(new RenameState(params.famlet))
  val aluLiteReadSrc1Update = RenameHelpers.updateWithARead(params.famlet)(
    statePreALULite, inputStage.bits.aluLite.src1ReadEnable(), inputStage.bits.aluLite.src1)
  val aluLiteReadSrc2Update = RenameHelpers.updateWithARead(params.famlet)(
    aluLiteReadSrc1Update.state, inputStage.bits.aluLite.src2ReadEnable(), inputStage.bits.aluLite.src2)
  val aluLiteReadOldUpdate = RenameHelpers.updateWithBRead(params.famlet)(
    aluLiteReadSrc2Update.state, inputStage.bits.aluLite.oldReadEnable(), inputStage.bits.aluLite.dst)
  val aluLiteWriteUpdate = RenameHelpers.updateWithBWrite(params.famlet)(
    aluLiteReadOldUpdate.state, inputStage.bits.aluLite.writeEnable(), inputStage.bits.aluLite.dst)
  val statePostALULite = aluLiteWriteUpdate.state

  val stallALULite = aluLiteWriteUpdate.failed
  outputStage.bits.aluLite := inputStage.bits.aluLite.rename(aluLiteReadSrc1Update.addr, aluLiteReadSrc2Update.addr, aluLiteReadOldUpdate.addr, aluLiteWriteUpdate.addr)

  // LoadStore
  // Reads: addr (A-register), src (for Store), old (for Load if predicated)
  // Writes: dst (for Load)
  val statePreLoadStore = Wire(new RenameState(params.famlet))
  val loadStoreReadAddrUpdate = RenameHelpers.updateWithARead(params.famlet)(
    statePreLoadStore, inputStage.bits.loadStore.addrReadEnable(), inputStage.bits.loadStore.addr)
  val loadStoreReadSrcUpdate = RenameHelpers.updateWithBRead(params.famlet)(
    loadStoreReadAddrUpdate.state, inputStage.bits.loadStore.srcReadEnable(), inputStage.bits.loadStore.reg)
  val loadStoreReadOldUpdate = RenameHelpers.updateWithBRead(params.famlet)(
    loadStoreReadSrcUpdate.state, inputStage.bits.loadStore.oldReadEnable(), inputStage.bits.loadStore.reg)
  val loadStoreWriteUpdate = RenameHelpers.updateWithBWrite(params.famlet)(
    loadStoreReadOldUpdate.state, inputStage.bits.loadStore.writeEnable(), inputStage.bits.loadStore.reg)
  val statePostLoadStore = loadStoreWriteUpdate.state

  val stallLoadStore = loadStoreWriteUpdate.failed
  outputStage.bits.loadStore := inputStage.bits.loadStore.rename(loadStoreReadAddrUpdate.addr, loadStoreReadSrcUpdate.addr, loadStoreReadOldUpdate.addr, loadStoreWriteUpdate.addr)

  // Packet
  // Reads: length (for Send operations), target (for operations that use target), result (for forward operations), old (for receive operations if predicated)
  // Writes: dst (for receive operations)
  val statePrePacket = Wire(new RenameState(params.famlet))
  val packetReadLengthUpdate = RenameHelpers.updateWithARead(params.famlet)(
    statePrePacket, inputStage.bits.packet.lengthReadEnable(), inputStage.bits.packet.length)
  val packetReadTargetUpdate = RenameHelpers.updateWithARead(params.famlet)(
    packetReadLengthUpdate.state, inputStage.bits.packet.targetReadEnable(), inputStage.bits.packet.target)
  val packetReadResultUpdate = RenameHelpers.updateWithBRead(params.famlet)(
    packetReadTargetUpdate.state, inputStage.bits.packet.resultReadEnable(), inputStage.bits.packet.result)
  val packetReadOldUpdate = RenameHelpers.updateWithBRead(params.famlet)(
    packetReadResultUpdate.state, inputStage.bits.packet.oldReadEnable(), inputStage.bits.packet.result)
  val packetWriteUpdate = RenameHelpers.updateWithBWrite(params.famlet)(
    packetReadOldUpdate.state, inputStage.bits.packet.writeEnable(), inputStage.bits.packet.result)
  val statePostPacket = packetWriteUpdate.state

  val stallPacket = packetWriteUpdate.failed
  outputStage.bits.packet := inputStage.bits.packet.rename(packetReadLengthUpdate.addr, packetReadTargetUpdate.addr, packetReadResultUpdate.addr, packetReadOldUpdate.addr, packetWriteUpdate.addr)

  // Update available physical registers
  val statePreAvail = Wire(new RenameState(params.famlet))
  val statePostAvail = Wire(new RenameState(params.famlet))
  statePostAvail := statePreAvail
  
  // Find available A physical registers
  val aRegsAvailable = Wire(Vec(params.famlet.nAPhysRegs, Bool()))
  for (i <- 0 until params.famlet.nAPhysRegs) {
    aRegsAvailable(i) := !statePreAvail.aIsLive(i) && statePreAvail.aPendingReads(i) === 0.U
  }
  
  statePostAvail.nAvailAPhysRegs := PopCount(aRegsAvailable)
  
  // Select first nAWritePorts available A registers
  for (portIdx <- 0 until params.famlet.nAWritePorts) {
    for (i <- 0 until params.famlet.nAPhysRegs) {
      when (aRegsAvailable(i) && PopCount(aRegsAvailable.take(i)) === portIdx.U) {
        statePostAvail.availAPhysRegs(portIdx) := i.U
      }
    }
  }
  
  // Find available D physical registers
  val dRegsAvailable = Wire(Vec(params.famlet.nDPhysRegs, Bool()))
  for (i <- 0 until params.famlet.nDPhysRegs) {
    dRegsAvailable(i) := !statePreAvail.dIsLive(i) && statePreAvail.dPendingReads(i) === 0.U
  }
  
  statePostAvail.nAvailDPhysRegs := PopCount(dRegsAvailable)
  
  // Select first nDWritePorts available D registers
  for (portIdx <- 0 until params.famlet.nDWritePorts) {
    for (i <- 0 until params.famlet.nDPhysRegs) {
      when (dRegsAvailable(i) && PopCount(dRegsAvailable.take(i)) === portIdx.U) {
        statePostAvail.availDPhysRegs(portIdx) := i.U
      }
    }
  }
  
  // Process notices to decrement pending reads
  val statePreNotices = Wire(new RenameState(params.famlet))
  
  val statePostNotices = Wire(new RenameState(params.famlet))
  statePostNotices := statePreNotices
  
  // Create vectors to collect all decrements
  val totalAReadPorts = params.nFamlets * params.famlet.nAOnlyReadPorts
  val totalDReadPorts = params.nFamlets * params.famlet.nDOnlyReadPorts  
  val totalBReadPorts = params.nFamlets * params.famlet.nBReadPorts
  
  val aReadDecrements = Wire(Vec(totalAReadPorts, Vec(params.famlet.nAPhysRegs, Bool())))
  val dReadDecrements = Wire(Vec(totalDReadPorts, Vec(params.famlet.nDPhysRegs, Bool())))
  val bReadADecrements = Wire(Vec(totalBReadPorts, Vec(params.famlet.nAPhysRegs, Bool())))
  val bReadDDecrements = Wire(Vec(totalBReadPorts, Vec(params.famlet.nDPhysRegs, Bool())))
  
  
  // Process A register read completions
  var aPortIdx = 0
  for (famletIdx <- 0 until params.nFamlets) {
    for (portIdx <- 0 until params.famlet.nAOnlyReadPorts) {
      when (noticesStage(famletIdx).aReads(portIdx).valid) {
        val physAddr = noticesStage(famletIdx).aReads(portIdx).bits
        aReadDecrements(aPortIdx) := UIntToOH(physAddr, params.famlet.nAPhysRegs).asBools
      } .otherwise {
        aReadDecrements(aPortIdx) := VecInit(Seq.fill(params.famlet.nAPhysRegs)(false.B))
      }
      aPortIdx += 1
    }
  }
  
  // Process D register read completions
  var dPortIdx = 0
  for (famletIdx <- 0 until params.nFamlets) {
    for (portIdx <- 0 until params.famlet.nDOnlyReadPorts) {
      when (noticesStage(famletIdx).dReads(portIdx).valid) {
        val physAddr = noticesStage(famletIdx).dReads(portIdx).bits
        dReadDecrements(dPortIdx) := UIntToOH(physAddr, params.famlet.nDPhysRegs).asBools
      } .otherwise {
        dReadDecrements(dPortIdx) := VecInit(Seq.fill(params.famlet.nDPhysRegs)(false.B))
      }
      dPortIdx += 1
    }
  }
  
  // Process B register read completions
  var bPortIdx = 0
  for (famletIdx <- 0 until params.nFamlets) {
    for (portIdx <- 0 until params.famlet.nBReadPorts) {
      when (noticesStage(famletIdx).bReads(portIdx).valid) {
        val physAddr = noticesStage(famletIdx).bReads(portIdx).bits
        when (physAddr(params.famlet.bPhysRegWidth-1)) {
          // D register
          val dPhysAddr = physAddr(params.famlet.dPhysRegWidth-1, 0)
          bReadDDecrements(bPortIdx) := UIntToOH(dPhysAddr, params.famlet.nDPhysRegs).asBools
          bReadADecrements(bPortIdx) := VecInit(Seq.fill(params.famlet.nAPhysRegs)(false.B))
        } .otherwise {
          // A register
          val aPhysAddr = physAddr(params.famlet.aPhysRegWidth-1, 0)
          bReadADecrements(bPortIdx) := UIntToOH(aPhysAddr, params.famlet.nAPhysRegs).asBools
          bReadDDecrements(bPortIdx) := VecInit(Seq.fill(params.famlet.nDPhysRegs)(false.B))
        }
      } .otherwise {
        bReadADecrements(bPortIdx) := VecInit(Seq.fill(params.famlet.nAPhysRegs)(false.B))
        bReadDDecrements(bPortIdx) := VecInit(Seq.fill(params.famlet.nDPhysRegs)(false.B))
      }
      bPortIdx += 1
    }
  }
  
  // Sum up all decrements and apply them
  for (reg <- 0 until params.famlet.nAPhysRegs) {
    val aReadDecs = VecInit(aReadDecrements.map(_(reg)))
    val bReadDecs = VecInit(bReadADecrements.map(_(reg)))
    val totalDec = PopCount(aReadDecs) + PopCount(bReadDecs)
    // FIXME: Handle underflow
    statePostNotices.aPendingReads(reg) := statePreNotices.aPendingReads(reg) - totalDec
  }
  
  for (reg <- 0 until params.famlet.nDPhysRegs) {
    val dReadDecs = VecInit(dReadDecrements.map(_(reg)))
    val bReadDecs = VecInit(bReadDDecrements.map(_(reg)))
    val totalDec = PopCount(dReadDecs) + PopCount(bReadDecs)
    // FIXME: Handle underflow
    statePostNotices.dPendingReads(reg) := statePreNotices.dPendingReads(reg) - totalDec
  }

  // State chaining - pass state through all instruction processing stages
  statePreControl := state
  statePrePredicate := statePostControl
  statePreALU := statePostPredicate
  statePreALULite := statePostALU
  statePreLoadStore := statePostALULite
  statePrePacket := statePostLoadStore

  statePreAvail := statePostPacket
  statePreNotices := statePostAvail
  
  
  // Overall stall condition
  val stallRequired = stallControl || stallPredicate || stallALU || stallALULite || stallLoadStore || stallPacket
  
  // Update state if no stall
  when (inputStage.valid && !stallRequired) {
    stateNext := statePostNotices
  } .otherwise {
    stateNext := state
  }
  
  // Set output valid signal
  outputStage.valid := inputStage.valid && !stallRequired
  
  // Optional output registration
  if (params.rename.registerOutput) {
    io.output := RegNext(outputStage)
  } else {
    io.output := outputStage
  }

}



/** Generator object for creating Rename modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of Rename modules with configurable parameters.
  */
object RenameGenerator extends fmvpu.ModuleGenerator {
  /** Create a Rename module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return Rename module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 1) {
      println("Usage: <command> <outputDir> Rename <gamletParamsFileName>")
      null
    } else {
      val params = GamletParams.fromFile(args(0))
      new Rename(params)
    }
  }
}
