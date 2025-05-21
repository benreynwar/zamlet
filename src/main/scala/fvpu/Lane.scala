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
  val mode =  UInt(4.W);
  val src1 = UInt(log2Ceil(params.nDRF).W);
  val src2 = UInt(log2Ceil(params.nDRF).W);
  val dst = UInt(log2Ceil(params.nDRF).W);
  }

class LoadStoreInstr(params: FVPUParams) extends Bundle {
  val mode =  UInt(1.W);
  val reg = UInt(log2Ceil(params.nDRF).W);
  val addr = UInt(log2Ceil(params.depthDDM).W);
  }

class SendReceiveInstr(params: FVPUParams) extends Bundle {
  val mode =  UInt(1.W);
  val length = UInt(log2Ceil(params.depthDDM).W);
  val addr = UInt(log2Ceil(params.depthDDM).W);
  }

class NetworkInstr(params: FVPUParams) extends Bundle {
  val mode =  UInt(log2Ceil(params.depthNetworkConfig).W);
  val src = UInt(log2Ceil(params.nDRF).W);
  val dst = UInt(log2Ceil(params.nDRF).W);
  }
// When a mode is read it specifies how the network should be configured on each clock cycle.
//

class Instr(params: FVPUParams) extends Bundle {
  val compute = new ComputeInstr(params);
  val loadstore = new LoadStoreInstr(params);
  val network = new NetworkInstr(params);
  val sendreceive = new SendReceiveInstr(params);
  }

class Lane(params: FVPUParams) extends Module {
  val nI = IO(Input(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val nO = IO(Output(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val sI = IO(Input(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val sO = IO(Output(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val eI = IO(Input(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val eO = IO(Output(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val wI = IO(Input(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val wO = IO(Output(Vec(params.nBuses, Valid(UInt(params.width.W)))));
  val instr = IO(Input(Valid(new Instr(params))));

  val networkNode = Module(new NetworkNode(params));
  //val DRF = Module(new DistributedRegisterFile(params));
  //val DDM = Module(new DistributedDataMemory(params));
  //val ALU = Module(new LaneALU(params));


  // Connect up the Network
  val networkControl = Wire(new NetworkNodeControl(params));
  networkNode.nI := nI;
  nO := networkNode.nO;
  networkNode.sI := sI;
  sO := networkNode.sO;
  networkNode.wI := wI;
  wO := networkNode.wO;
  networkNode.eI := eI;
  eO := networkNode.eO;
  networkNode.control := networkControl;

}

