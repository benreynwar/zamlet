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
import fmvpu.ModuleGenerator

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
class Lane(params: FMPVUParams) extends Module {
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
    
    /** Network configuration input from north neighbor
      * @group Control
      */
    val nConfig = Input(new Config(params))
    
    /** Network configuration output to south neighbor  
      * @group Control
      */
    val sConfig = Output(new Config(params))
  })

  val networkNode = Module(new NetworkNode(params))
  val drf = Module(new RegisterFile(params.width, params.nDRF, 4, 3))
  val ddm = Module(new DataMemory(params.width, params.ddmBankDepth, params.ddmNBanks))
  val ddmAccess = Module(new ddmAccess(params))
  // val alu = Module(new LaneALU(params))

  // Register nInstr to create sInstr
  io.sInstr := RegNext(io.nInstr)

  // Register nConfig to create sConfig
  io.sConfig := RegNext(io.nConfig)

  // Adjustable delay for instruction execution
  val instrDelayModule = Module(new AdjustableDelay(params.networkMemoryDepth, io.nInstr.getWidth))
  instrDelayModule.io.delay := io.instrDelay
  instrDelayModule.io.input.valid := true.B
  instrDelayModule.io.input.bits := io.nInstr.asUInt
  val instr = instrDelayModule.io.output.bits.asTypeOf(new Instr(params))

  // Connect ddmAccess to sendreceive instructions
  ddmAccess.io.instr := instr.sendreceive

  // Load Instruction
  val aLoadInstr = Wire(Valid(new LoadInstr(params)))
  aLoadInstr.valid := instr.loadstore.valid && instr.loadstore.bits.mode === false.B
  aLoadInstr.bits.reg := instr.loadstore.bits.reg
  aLoadInstr.bits.addr := instr.loadstore.bits.addr

  val bLoadInstr = aLoadInstr

  drf.io.reads(1).enable := bLoadInstr.valid
  drf.io.reads(1).address := bLoadInstr.bits.reg
  val bLoadData = drf.io.reads(1).data

  val cLoadInstr = bLoadInstr
  val cLoadData = bLoadData

  ddm.io.writes(1).enable := cLoadInstr.valid
  ddm.io.writes(1).address := cLoadInstr.bits.addr
  ddm.io.writes(1).data := cLoadData

  // Store Instruction
  val aStoreInstr = Wire(Valid(new LoadInstr(params)))
  aStoreInstr.valid := instr.loadstore.valid && instr.loadstore.bits.mode === true.B
  aStoreInstr.bits.reg := instr.loadstore.bits.reg
  aStoreInstr.bits.addr := instr.loadstore.bits.addr

  val bStoreInstr = aStoreInstr

  ddm.io.reads(1).address.valid := bStoreInstr.valid
  ddm.io.reads(1).address.bits := bStoreInstr.bits.addr
  val cStoreData = ddm.io.reads(1).data.bits
  // Assuming DDM has a latency of 1
  val cStoreInstr = RegNext(bStoreInstr)

  drf.io.writes(1).enable := cStoreInstr.valid
  drf.io.writes(1).address := cStoreInstr.bits.reg
  drf.io.writes(1).data := cStoreData

  val networkControl = Wire(new NetworkNodeControl(params))
  // For now let's keep things simple
  // Writes to the DDM come from the west (channel 0)
  // Reads from the DDM go the east (channel 0)
  // Writes to the DRF come from the north (channel 0)
  // Reads from the DRF go the south (channel 0)
  // For n_channels = 4, delay up to 7 this is 4 * (1 + 1 + 3 + 3 + 3 + 3 + 3 + 3) = 4 * 20 = 80 bits
  for (i <- 0 until params.nChannels) {
    networkControl.nsInputSel(i) := false.B
    networkControl.weInputSel(i) := false.B
    networkControl.nsCrossbarSel(i) := (if (i == 1) (params.nChannels + 0).U else 0.U)
    networkControl.weCrossbarSel(i) := (if (i == 1) (params.nChannels + 1).U else 0.U)
  }
  networkControl.drfSel := 0.U
  networkControl.ddmSel := params.nChannels.U
  
  // Set drive signals - for current tests, only drive east
  for (i <- 0 until params.nChannels) {
    networkControl.nDrive(i) := false.B
    networkControl.sDrive(i) := false.B
    networkControl.wDrive(i) := false.B
    networkControl.eDrive(i) := true.B
  }

  // Connect up the Network to the lane boundary.
  networkNode.io.inputs(0) <> io.nI
  io.nO <> networkNode.io.outputs(0)
  networkNode.io.inputs(1) <> io.sI
  io.sO <> networkNode.io.outputs(1)
  networkNode.io.inputs(2) <> io.wI
  io.wO <> networkNode.io.outputs(2)
  networkNode.io.inputs(3) <> io.eI
  io.eO <> networkNode.io.outputs(3)
  networkNode.io.control := networkControl
  networkNode.io.thisLoc := io.thisLoc
  networkNode.io.configValid := io.nConfig.configValid
  networkNode.io.configIsPacketMode := io.nConfig.configIsPacketMode
  networkNode.io.configDelay := io.nConfig.configDelay

  // We haven't yet connected the DRF to the Network
  drf.io.writes(0).enable := false.B
  drf.io.writes(0).address := DontCare
  drf.io.writes(0).data := DontCare
  networkNode.io.fromDRF.valid := false.B
  networkNode.io.fromDRF.bits := DontCare
  drf.io.reads(0).enable := false.B
  drf.io.reads(0).address := DontCare

  // We haven't connected a ALU to the DRF
  for (i <- 2 until 4) {
    drf.io.reads(i).enable := false.B
    drf.io.reads(i).address := DontCare
  }
  drf.io.writes(2).enable := false.B
  drf.io.writes(2).address := DontCare
  drf.io.writes(2).data := DontCare

  // Connect ddmAccess between network and DDM
  ddmAccess.io.writeDDM <> ddm.io.writes(0)
  ddmAccess.io.readDDM <> ddm.io.reads(0)
  ddmAccess.io.fromNetwork := networkNode.io.toDDM
  networkNode.io.fromDDM := ddmAccess.io.toNetwork
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
    val params = FMPVUParams.fromFile(args(0))
    new Lane(params)
  }
}
