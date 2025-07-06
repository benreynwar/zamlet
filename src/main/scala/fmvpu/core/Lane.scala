package fmvpu.core

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import fmvpu.memory._
import fmvpu.network._
import fmvpu.utils._
import fmvpu.alu._
import fmvpu.ModuleGenerator

/**
 * Error signals for the Lane module
 * @param params FMVPU system parameters
 * @groupdesc Signals The actual hardware fields of the Bundle
 */
class LaneErrors(params: FMVPUParams) extends Bundle {
  /** Error signals from DDM access controller
    * @group Signals
    */
  val ddmAccess = new DDMAccessErrors
  
  /** Error signals from network node
    * @group Signals
    */
  val networkNode = new NetworkNodeErrors
  
  /** Error signals from data memory
    * @group Signals
    */
  val dataMemory = new DataMemoryErrors(params.ddmNBanks)
  
  /** Error signals from register file
    * @group Signals
    */
  val registerFile = new RegisterFileErrors(3) // 3 write ports (from RegisterFile instantiation)
}

import scala.io.Source

/** A single processing lane in the FMVPU mesh architecture.
  *
  * Each Lane contains a network node for communication, distributed register file (DRF),
  * distributed data memory (DDM), and memory access controllers. The lane can execute
  * load/store instructions and participates in the mesh network for inter-lane communication.
  *
  * @param params System configuration parameters
  * @groupdesc Network Network interface ports for mesh connectivity  
  * @groupdesc Control Control and configuration signals
  */
class Lane(params: FMVPUParams) extends Module {
  val io = IO(new Bundle {
    /** North input channels from neighboring lane
      * @group Network
      */
    val nI = Vec(params.nChannels, new PacketInterface(params.width))
    
    /** North output channels to neighboring lane  
      * @group Network
      */
    val nO = Vec(params.nChannels, Flipped(new PacketInterface(params.width)))
    
    /** South input channels from neighboring lane
      * @group Network
      */
    val sI = Vec(params.nChannels, new PacketInterface(params.width))
    
    /** South output channels to neighboring lane
      * @group Network  
      */
    val sO = Vec(params.nChannels, Flipped(new PacketInterface(params.width)))
    
    /** East input channels from neighboring lane
      * @group Network
      */
    val eI = Vec(params.nChannels, new PacketInterface(params.width))
    
    /** East output channels to neighboring lane
      * @group Network
      */
    val eO = Vec(params.nChannels, Flipped(new PacketInterface(params.width)))
    
    /** West input channels from neighboring lane
      * @group Network
      */
    val wI = Vec(params.nChannels, new PacketInterface(params.width))
    
    /** West output channels to neighboring lane
      * @group Network
      */
    val wO = Vec(params.nChannels, Flipped(new PacketInterface(params.width)))
    
    /** Instruction input from north neighbor
      * @group Control
      */
    val nInstr = Input(new Instr(params))
    
    /** Instruction output to south neighbor
      * @group Control
      */
    val sInstr = Output(new Instr(params))
    
    /** Configurable delay for instruction execution timing
      * @group Control
      */
    val instrDelay = Input(UInt(log2Ceil(params.networkMemoryDepth + 1).W))
    
    /** This lane's position in the grid coordinate system
      * @group Control
      */
    val thisLoc = Input(new Location(params))
    
    /** Send/receive instruction response output
      * @group Control
      */
    val instrResponse = Output(Valid(new SendReceiveInstrResponse(params)))
    
    /** Error status signals from all sub-modules
      * @group Control
      */
    val errors = Output(new LaneErrors(params))
    
  })

  val networkNode = Module(new NetworkNode(params))
  val drf = Module(new RegisterFile(params.width, params.nDRF, 4, 3))
  val ddm = Module(new DataMemory(params.width, params.ddmBankDepth, params.ddmNBanks))
  val ddmAccess = Module(new ddmAccess(params))
  val alu = Module(new LaneALU(params))

  // Register nInstr to create sInstr
  io.sInstr := RegNext(io.nInstr)


  // Adjustable delay for instruction execution
  val instrDelayModule = Module(new AdjustableDelay(params.networkMemoryDepth, io.nInstr.getWidth))
  instrDelayModule.io.delay := io.instrDelay
  instrDelayModule.io.input.valid := true.B
  instrDelayModule.io.input.bits := io.nInstr.asUInt
  val instr = instrDelayModule.io.output.bits.asTypeOf(new Instr(params))

  // Connect ddmAccess to sendreceive instructions
  ddmAccess.io.instr := instr.sendreceive

  // Store Instruction (register -> memory)
  val aStoreInstr = Wire(Valid(new LoadInstr(params)))
  aStoreInstr.valid := instr.loadstore.valid && instr.loadstore.bits.mode === false.B
  aStoreInstr.bits.reg := instr.loadstore.bits.reg
  aStoreInstr.bits.addr := instr.loadstore.bits.addr

  val bStoreInstr = aStoreInstr

  drf.io.reads(1).enable := bStoreInstr.valid
  drf.io.reads(1).address := bStoreInstr.bits.reg
  val bStoreData = drf.io.reads(1).data

  val cStoreInstr = bStoreInstr
  val cStoreData = bStoreData

  ddm.io.writes(1).enable := cStoreInstr.valid
  ddm.io.writes(1).address := cStoreInstr.bits.addr
  ddm.io.writes(1).data := cStoreData

  // Load Instruction (memory -> register)
  val aLoadInstr = Wire(Valid(new LoadInstr(params)))
  aLoadInstr.valid := instr.loadstore.valid && instr.loadstore.bits.mode === true.B
  aLoadInstr.bits.reg := instr.loadstore.bits.reg
  aLoadInstr.bits.addr := instr.loadstore.bits.addr

  val bLoadInstr = aLoadInstr

  ddm.io.reads(1).address.valid := bLoadInstr.valid
  ddm.io.reads(1).address.bits := bLoadInstr.bits.addr
  val cLoadData = ddm.io.reads(1).data.bits
  // Assuming DDM has a latency of 1
  val cLoadInstr = RegNext(bLoadInstr)

  drf.io.writes(1).enable := cLoadInstr.valid
  drf.io.writes(1).address := cLoadInstr.bits.reg
  drf.io.writes(1).data := cLoadData


  // Connect up the Network to the lane boundary.
  networkNode.io.inputs(0) <> io.nI
  io.nO <> networkNode.io.outputs(0)
  networkNode.io.inputs(1) <> io.sI
  io.sO <> networkNode.io.outputs(1)
  networkNode.io.inputs(2) <> io.wI
  io.wO <> networkNode.io.outputs(2)
  networkNode.io.inputs(3) <> io.eI
  io.eO <> networkNode.io.outputs(3)
  networkNode.io.thisLoc := io.thisLoc

  // We haven't yet connected the DRF to the Network
  drf.io.writes(0).enable := false.B
  drf.io.writes(0).address := DontCare
  drf.io.writes(0).data := DontCare
  networkNode.io.fromDRF.valid := false.B
  networkNode.io.fromDRF.bits := DontCare
  drf.io.reads(0).enable := false.B
  drf.io.reads(0).address := DontCare

  // Connect ALU to DRF
  alu.io.instr := instr.compute
  drf.io.reads(2).enable := instr.compute.valid
  drf.io.reads(2).address := instr.compute.bits.src1
  drf.io.reads(3).enable := instr.compute.valid
  drf.io.reads(3).address := instr.compute.bits.src2
  alu.io.src1Data := drf.io.reads(2).data
  alu.io.src2Data := drf.io.reads(3).data
  drf.io.writes(2).enable := alu.io.result.valid
  drf.io.writes(2).address := alu.io.result.bits.dstAddr
  drf.io.writes(2).data := alu.io.result.bits.data

  // Connect ddmAccess between network and DDM
  ddm.io.writes(0) <> ddmAccess.io.writeDDM
  networkNode.io.writeControl <> ddmAccess.io.writeControl
  ddmAccess.io.readDDM <> ddm.io.reads(0)
  ddmAccess.io.fromNetwork := networkNode.io.toDDM
  ddmAccess.io.thisLoc := io.thisLoc
  networkNode.io.fromDDM <> ddmAccess.io.toNetwork
  networkNode.io.fromDDMChannel := ddmAccess.io.toNetworkChannel
  
  // Connect network instruction from the main instruction bundle
  networkNode.io.networkInstr := instr.network
  
  // Connect send/receive instruction for network slot selection
  networkNode.io.sendReceiveInstr := instr.sendreceive
  
  // Connect instruction response output from ddmAccess
  io.instrResponse := ddmAccess.io.instrResponse
  
  // Connect error signals from all sub-modules
  io.errors.ddmAccess <> ddmAccess.io.errors
  io.errors.networkNode <> networkNode.io.errors
  io.errors.dataMemory <> ddm.io.errors
  io.errors.registerFile <> drf.io.errors
}


/** Generator object for creating Lane modules from command line arguments.
  *
  * This object implements the ModuleGenerator interface to enable command-line
  * generation of Lane modules with parameters loaded from JSON files.
  */
object LaneGenerator extends ModuleGenerator {

  /** Create a Lane module with parameters loaded from a JSON file.
    *
    * @param args Command line arguments, where args(0) should be the path to a JSON parameter file
    * @return Lane module instance configured with the loaded parameters
    */
  override def makeModule(args: Seq[String]): Module = {
    // Parse arguments
    if (args.length < 1) {
      println("Usage: <command> <outputDir> Lane <paramsFileName>")
      return null
    }
    val params = FMVPUParams.fromFile(args(0))
    new Lane(params)
  }
}
