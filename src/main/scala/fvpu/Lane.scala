package fvpu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid

import scala.io.Source

import fvpu.ModuleGenerator

class ComputeInstr(params: FVPUParams) extends Bundle {
  val mode =  UInt(4.W)
  val src1 = UInt(log2Ceil(params.nDRF).W)
  val src2 = UInt(log2Ceil(params.nDRF).W)
  val dst = UInt(log2Ceil(params.nDRF).W)
  }

class LoadOrStoreInstr(params: FVPUParams) extends Bundle {
  val mode =  UInt(1.W)
  val reg = UInt(log2Ceil(params.nDRF).W)
  val addr = UInt(params.ddmAddrWidth.W)
  }

class LoadInstr(params: FVPUParams) extends Bundle {
  val reg = UInt(log2Ceil(params.nDRF).W)
  val addr = UInt(params.ddmAddrWidth.W)
  }

class StoreInstr(params: FVPUParams) extends Bundle {
  val reg = UInt(log2Ceil(params.nDRF).W)
  val addr = UInt(params.ddmAddrWidth.W)
  }

class SendReceiveInstr(params: FVPUParams) extends Bundle {
  val mode =  UInt(1.W)
  val length = UInt(params.ddmAddrWidth.W)
  val addr = UInt(params.ddmAddrWidth.W)
  }

class NetworkInstr(params: FVPUParams) extends Bundle {
  val mode =  UInt(log2Ceil(params.depthNetworkConfig).W)
  val src = UInt(log2Ceil(params.nDRF).W)
  val dst = UInt(log2Ceil(params.nDRF).W)
  }

class ConfigInstr(params: FVPUParams) extends Bundle {
  val src = UInt(log2Ceil(params.nDRF).W)
  val dst = UInt(log2Ceil(params.nDRF).W)
  }
// When a mode is read it specifies how the network should be configured on each clock cycle.
//

class Instr(params: FVPUParams) extends Bundle {
  val compute = Valid(new ComputeInstr(params))
  val loadstore = Valid(new LoadOrStoreInstr(params))
  val network = Valid(new NetworkInstr(params))
  val sendreceive = Valid(new SendReceiveInstr(params))
  }

class Lane(params: FVPUParams) extends Module {
  val nI = IO(Input(Vec(params.nBuses, Valid(UInt(params.width.W)))))
  val nO = IO(Output(Vec(params.nBuses, Valid(UInt(params.width.W)))))
  val sI = IO(Input(Vec(params.nBuses, Valid(UInt(params.width.W)))))
  val sO = IO(Output(Vec(params.nBuses, Valid(UInt(params.width.W)))))
  val eI = IO(Input(Vec(params.nBuses, Valid(UInt(params.width.W)))))
  val eO = IO(Output(Vec(params.nBuses, Valid(UInt(params.width.W)))))
  val wI = IO(Input(Vec(params.nBuses, Valid(UInt(params.width.W)))))
  val wO = IO(Output(Vec(params.nBuses, Valid(UInt(params.width.W)))))
  val instr = IO(Input(new Instr(params)))

  val networkNode = Module(new NetworkNode(params))
  val DRF = Module(new RegisterFile(params.width, params.nDRF, 4, 3))
  val DDM = Module(new DataMemory(params.width, params.ddmBankDepth, params.ddmNBanks))
  val ddmAccess = Module(new ddmAccess(params))
  //val ALU = Module(new LaneALU(params))

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
  for (i <- 0 until params.nBuses) {
    networkControl.nsInputSel(i) := false.B
    networkControl.weInputSel(i) := false.B
    networkControl.nsCrossbarSel(i) := (if (i == 0) (params.nBuses+0).U else 0.U)
    networkControl.weCrossbarSel(i) := (if (i == 0) (params.nBuses+1).U else 0.U)
    networkControl.nOutputDelays(i) := 0.U
    networkControl.sOutputDelays(i) := 0.U
    networkControl.wOutputDelays(i) := 0.U
    networkControl.eOutputDelays(i) := 0.U
    networkControl.nOutputDrive(i) := false.B
    networkControl.sOutputDrive(i) := (i == 0).B
    networkControl.wOutputDrive(i) := false.B
    networkControl.eOutputDrive(i) := (i == 0).B
  }
  networkControl.drfSel := 0.U
  networkControl.ddmSel := params.nBuses.U

  // Connect up the Network to the lane boundary.
  networkNode.nI := nI
  nO := networkNode.nO
  networkNode.sI := sI
  sO := networkNode.sO
  networkNode.wI := wI
  wO := networkNode.wO
  networkNode.eI := eI
  eO := networkNode.eO
  networkNode.control := networkControl

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
    val params = FVPUParams.fromFile(args(0));
    return new Lane(params);
  }

}
