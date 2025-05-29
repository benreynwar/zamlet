package fmpvu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid

import scala.io.Source

import fmpvu.ModuleGenerator

class ComputeInstr(params: FMPVUParams) extends Bundle {
  val mode =  UInt(4.W)
  val src1 = UInt(log2Ceil(params.nDRF).W)
  val src2 = UInt(log2Ceil(params.nDRF).W)
  val dst = UInt(log2Ceil(params.nDRF).W)
  }

class LoadOrStoreInstr(params: FMPVUParams) extends Bundle {
  val mode =  UInt(1.W)
  val reg = UInt(log2Ceil(params.nDRF).W)
  val addr = UInt(params.ddmAddrWidth.W)
  }

class LoadInstr(params: FMPVUParams) extends Bundle {
  val reg = UInt(log2Ceil(params.nDRF).W)
  val addr = UInt(params.ddmAddrWidth.W)
  }

class StoreInstr(params: FMPVUParams) extends Bundle {
  val reg = UInt(log2Ceil(params.nDRF).W)
  val addr = UInt(params.ddmAddrWidth.W)
  }

class SendReceiveInstr(params: FMPVUParams) extends Bundle {
  val mode =  UInt(1.W)
  val length = UInt(params.ddmAddrWidth.W)
  val addr = UInt(params.ddmAddrWidth.W)
  val startOffset = UInt(params.ddmAddrWidth.W)
  val stride = UInt(params.ddmAddrWidth.W)
  }

class NetworkInstr(params: FMPVUParams) extends Bundle {
  val mode =  UInt(log2Ceil(params.depthNetworkConfig).W)
  val src = UInt(log2Ceil(params.nDRF).W)
  val dst = UInt(log2Ceil(params.nDRF).W)
  }

class ConfigInstr(params: FMPVUParams) extends Bundle {
  val src = UInt(log2Ceil(params.nDRF).W)
  val dst = UInt(log2Ceil(params.nDRF).W)
  }
// When a mode is read it specifies how the network should be configured on each clock cycle.
//

class Instr(params: FMPVUParams) extends Bundle {
  val compute = Valid(new ComputeInstr(params))
  val loadstore = Valid(new LoadOrStoreInstr(params))
  val network = Valid(new NetworkInstr(params))
  val sendreceive = Valid(new SendReceiveInstr(params))
  }

class Config(params: FMPVUParams) extends Bundle {
  val configValid = Bool()
  val configIsPacketMode = Bool()
  val configDelay = UInt(log2Ceil(params.networkMemoryDepth+1).W)
  }

class Lane(params: FMPVUParams) extends Module {
  val nI = IO(Vec(params.nBuses, new Bus(params.width)))
  val nO = IO(Vec(params.nBuses, Flipped(new Bus(params.width))))
  val sI = IO(Vec(params.nBuses, new Bus(params.width)))
  val sO = IO(Vec(params.nBuses, Flipped(new Bus(params.width))))
  val eI = IO(Vec(params.nBuses, new Bus(params.width)))
  val eO = IO(Vec(params.nBuses, Flipped(new Bus(params.width))))
  val wI = IO(Vec(params.nBuses, new Bus(params.width)))
  val wO = IO(Vec(params.nBuses, Flipped(new Bus(params.width))))
  val nInstr = IO(Input(new Instr(params)))
  val sInstr = IO(Output(new Instr(params)))
  val instrDelay = IO(Input(UInt(log2Ceil(params.networkMemoryDepth+1).W)))
  val thisLoc = IO(Input(new Location(params)))
  val nConfig = IO(Input(new Config(params)))
  val sConfig = IO(Output(new Config(params)))

  val networkNode = Module(new NetworkNode(params))
  val DRF = Module(new RegisterFile(params.width, params.nDRF, 4, 3))
  val DDM = Module(new DataMemory(params.width, params.ddmBankDepth, params.ddmNBanks))
  val ddmAccess = Module(new ddmAccess(params))
  //val ALU = Module(new LaneALU(params))

  // Register nInstr to create sInstr
  sInstr := RegNext(nInstr)
  
  // Register nConfig to create sConfig
  sConfig := RegNext(nConfig)

  // Adjustable delay for instruction execution
  val instrDelayModule = Module(new AdjustableDelay(params.networkMemoryDepth, nInstr.getWidth))
  instrDelayModule.delay := instrDelay
  instrDelayModule.input.valid := true.B
  instrDelayModule.input.bits := nInstr.asUInt
  val instr = instrDelayModule.output.bits.asTypeOf(new Instr(params))

  // Connect ddmAccess to sendreceive instructions
  ddmAccess.instr := instr.sendreceive

  // Load Instruction

  val aLoadInstr = Wire(Valid(new LoadInstr(params)))
  aLoadInstr.valid := instr.loadstore.valid && instr.loadstore.bits.mode === false.B
  aLoadInstr.bits.reg := instr.loadstore.bits.reg
  aLoadInstr.bits.addr := instr.loadstore.bits.addr

  val bLoadInstr = aLoadInstr

  DRF.reads(1).enable := bLoadInstr.valid
  DRF.reads(1).address := bLoadInstr.bits.reg
  val bLoadData = DRF.reads(1).data

  val cLoadInstr = bLoadInstr
  val cLoadData = bLoadData

  DDM.writes(1).enable := cLoadInstr.valid
  DDM.writes(1).address := cLoadInstr.bits.addr
  DDM.writes(1).data := cLoadData

  // Store Instruction

  val aStoreInstr = Wire(Valid(new LoadInstr(params)))
  aStoreInstr.valid := instr.loadstore.valid && instr.loadstore.bits.mode === true.B
  aStoreInstr.bits.reg := instr.loadstore.bits.reg
  aStoreInstr.bits.addr := instr.loadstore.bits.addr

  val bStoreInstr = aStoreInstr

  DDM.reads(1).address.valid := bStoreInstr.valid
  DDM.reads(1).address.bits := bStoreInstr.bits.addr
  val cStoreData = DDM.reads(1).data.bits
  // Assuming DDM has a latency of 1.
  val cStoreInstr = RegNext(bStoreInstr)

  DRF.writes(1).enable := cStoreInstr.valid
  DRF.writes(1).address := cStoreInstr.bits.reg
  DRF.writes(1).data := cStoreData

  val networkControl = Wire(new NetworkNodeControl(params))
  // For now let's keep things simple.
  // Writes to the DDM come from the west (bus 0)
  // Reads from the DDM go the east (bus 0).
  // Writes to the DRF come from the north (bus 0).
  // Reads from the DRF go the south (bus 0).
  // For n_buses = 4, delay up to 7 this is 4 * (1 + 1 + 3 + 3 + 3 + 3 +3 + 3) = 4 * 20 = 80 bits
  for (i <- 0 until params.nBuses) {
    networkControl.nsInputSel(i) := false.B
    networkControl.weInputSel(i) := false.B
    networkControl.nsCrossbarSel(i) := (if (i == 1) (params.nBuses+0).U else 0.U)
    networkControl.weCrossbarSel(i) := (if (i == 1) (params.nBuses+1).U else 0.U)
  }
  networkControl.drfSel := 0.U
  networkControl.ddmSel := params.nBuses.U

  // Connect up the Network to the lane boundary.
  networkNode.inputs(0) <> nI
  nO <> networkNode.outputs(0)
  networkNode.inputs(1) <> sI
  sO <> networkNode.outputs(1)
  networkNode.inputs(2) <> wI
  wO <> networkNode.outputs(2)
  networkNode.inputs(3) <> eI
  eO <> networkNode.outputs(3)
  networkNode.control := networkControl
  networkNode.thisLoc := thisLoc
  networkNode.configValid := nConfig.configValid
  networkNode.configIsPacketMode := nConfig.configIsPacketMode
  networkNode.configDelay := nConfig.configDelay

  // We haven't yet connected the DRF to the Network
  DRF.writes(0).enable := false.B
  DRF.writes(0).address := DontCare
  DRF.writes(0).data := DontCare
  networkNode.fromDRF.valid := false.B
  networkNode.fromDRF.bits := DontCare
  DRF.reads(0).enable := false.B
  DRF.reads(0).address := DontCare

  // We haven't connected a ALU to he DRF
  for (i <- 2 until 4) {
    DRF.reads(i).enable := false.B
    DRF.reads(i).address := DontCare
  }
  DRF.writes(2).enable := false.B
  DRF.writes(2).address := DontCare
  DRF.writes(2).data := DontCare

  // Connect ddmAccess between network and DDM
  ddmAccess.writeDDM <> DDM.writes(0)
  ddmAccess.readDDM <> DDM.reads(0)
  ddmAccess.fromNetwork := networkNode.toDDM
  networkNode.fromDDM := ddmAccess.toNetwork

}


object LaneGenerator extends ModuleGenerator {

  override def makeModule(args: Seq[String]): Module = {
    // Parse arguments
    if (args.length < 1) {
      println("Usage: <command> <outputDir> Lane <paramsFileName>")
      return null
    }
    val params = FMPVUParams.fromFile(args(0));
    return new Lane(params);
  }

}
