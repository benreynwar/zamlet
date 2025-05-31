package fmpvu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid
import chisel3.util.DecoupledIO

import scala.io.Source

import fmpvu.ModuleGenerator


class NetworkNodeControl(params: FMPVUParams) extends Bundle {
  val nsInputSel = Vec(params.nBuses, Bool())
  val weInputSel = Vec(params.nBuses, Bool())
  val nsCrossbarSel = Vec(params.nBuses, UInt(log2Ceil(params.nBuses + 2).W))
  val weCrossbarSel = Vec(params.nBuses, UInt(log2Ceil(params.nBuses + 2).W))
  val drfSel = UInt(log2Ceil(params.nBuses * 2).W)
  val ddmSel = UInt(log2Ceil(params.nBuses * 2).W)
  val nDrive = Vec(params.nBuses, Bool())
  val sDrive = Vec(params.nBuses, Bool())
  val wDrive = Vec(params.nBuses, Bool())
  val eDrive = Vec(params.nBuses, Bool())
}

class NetworkNode(params: FMPVUParams) extends Module {
  val io = IO(new Bundle {
    val inputs = Vec(4, Vec(params.nBuses, new Bus(params.width)))
    val outputs = Vec(4, Vec(params.nBuses, Flipped(new Bus(params.width))))
    val toDRF = Output(Valid(UInt(params.width.W)))
    val fromDRF = Input(Valid(UInt(params.width.W)))
    val toDDM = Output(Valid(new HeaderTag(UInt(params.width.W))))
    val fromDDM = Input(Valid(UInt(params.width.W)))
    val control = Input(new NetworkNodeControl(params))
    val thisLoc = Input(new Location(params))
    val configValid = Input(Bool())
    val configIsPacketMode = Input(Bool())
    val configDelay = Input(UInt(log2Ceil(params.networkMemoryDepth + 1).W))
  })

  // Just here to define modules
  val withHeaderTemplate = new HeaderTag(UInt(params.width.W))

  val isPacketMode = RegInit(true.B)

  when (io.configValid) {
    isPacketMode := io.configIsPacketMode
  }

  val crossbar = Module(new NetworkCrossbar(params))

  // Create a wire to aggregate all switch toDDM outputs
  val switchesToDDM = Wire(DecoupledIO(new HeaderTag(UInt(params.width.W))))

  // To the DDM from either the switch or the crossbar
  when (isPacketMode) {
    io.toDDM.valid := switchesToDDM.valid
    io.toDDM.bits := switchesToDDM.bits
    switchesToDDM.ready := true.B
  }.otherwise {
    io.toDDM.valid := crossbar.io.toDDM.valid
    io.toDDM.bits.bits := crossbar.io.toDDM.bits
    io.toDDM.bits.header := false.B
    switchesToDDM.ready := false.B
  }

  val ddmSelActive = RegInit(false.B)
  val ddmSelPointer = RegInit(0.U(log2Ceil(params.nBuses).W))
  val ddmRemaining = RegInit(0.U(log2Ceil(params.maxPacketLength+1).W))
  
  // Default values for switchesToDDM
  switchesToDDM.valid := false.B
  switchesToDDM.bits := DontCare
  
  // DDM arbitration logic - will be connected to switches in the loop below
  val nextDdmSelActive = Wire(Bool())
  val nextDdmSelPointer = Wire(UInt(log2Ceil(params.nBuses).W))
  val nextDdmRemaining = Wire(UInt(log2Ceil(params.maxPacketLength+1).W))
  
  // Default next values
  nextDdmSelActive := ddmSelActive
  nextDdmRemaining := ddmRemaining
  nextDdmSelPointer := ddmSelPointer

  crossbar.io.fromDRF := io.fromDRF
  io.toDRF := crossbar.io.toDRF
  crossbar.io.fromDDM := io.fromDDM
  crossbar.io.control := io.control

  // Create all switch instances
  val switches = Seq.fill(params.nBuses)(withReset(reset.asBool || io.configValid) { Module(new NetworkSwitch(params)) })

  val allSwitchToDDM = Wire(Vec(params.nBuses, DecoupledIO(new HeaderTag(UInt(params.width.W)))))
  for (i <- 0 until params.nBuses) {
    allSwitchToDDM(i) <> switches(i).io.toDDM
  }
  switchesToDDM.valid := allSwitchToDDM(ddmSelPointer).valid && isPacketMode
  switchesToDDM.bits := allSwitchToDDM(ddmSelPointer).bits

  for (busIndex <- 0 until params.nBuses) {
    val switch = switches(busIndex)
    switch.io.thisLoc := io.thisLoc
    
    // Currently we don't have any way for the DDM to initiate sending a packet
    // so this is inactive.
    switch.io.fromDDM.valid := false.B
    switch.io.fromDDM.bits := DontCare
    
    // DDM arbitration: only the selected switch can write to DDM
    when (isPacketMode && ddmSelPointer === busIndex.U) {
      allSwitchToDDM(busIndex).ready := switchesToDDM.ready
      // This switch is selected for DDM access
      when (!ddmSelActive) {
        // Not currently active - check if this switch wants to start a packet
        when (switch.io.toDDM.valid && switch.io.toDDM.bits.header) {
          // Switch wants to start a new packet, grant access
          nextDdmSelActive := true.B
          // Extract packet length from header
          val header = Header.fromBits(switch.io.toDDM.bits.bits, params)
          nextDdmRemaining := header.length
        }.otherwise {
          nextDdmSelPointer := (ddmSelPointer + 1.U) % params.nBuses.U
        }
      }.otherwise {
        // Decrement remaining count on successful transfer
        when (switch.io.toDDM.valid && switch.io.toDDM.ready) {
          nextDdmRemaining := ddmRemaining - 1.U
          // Check if this is the last transfer
          when (ddmRemaining === 1.U) {
            nextDdmSelActive := false.B
          }
        }
      }
    }.otherwise {
      // This switch is not selected for DDM access
      allSwitchToDDM(busIndex).ready := false.B
    }


    for (direction <- 0 until 4) {
      // If we're in packet mode the inputs go to the switch
      // otherwise they go to the crossbar.
      when (isPacketMode) {
        switch.io.inputs(direction) <> io.inputs(direction)(busIndex)
        crossbar.io.inputs(direction)(busIndex).valid := false.B
        crossbar.io.inputs(direction)(busIndex).bits := DontCare
      }.otherwise {
        switch.io.inputs(direction).valid := false.B
        switch.io.inputs(direction).bits := DontCare
        io.inputs(direction)(busIndex).token := false.B
        crossbar.io.inputs(direction)(busIndex) := io.inputs(direction)(busIndex).toValid()
      }

      val fifoOrDelay = Module(new FifoOrDelay(withHeaderTemplate, params.networkMemoryDepth))
      fifoOrDelay.io.config.valid := io.configValid
      fifoOrDelay.io.config.bits.isFifo := io.configIsPacketMode
      fifoOrDelay.io.config.bits.delay := io.configDelay

      // If we're in packet mode then the memory inputs come from the switch
      // otherwise the inputs come from the crossbar
      when (isPacketMode) {
        fifoOrDelay.io.input <> switch.io.toFifos(direction)
      }.otherwise {
        fifoOrDelay.io.input.valid := crossbar.io.outputs(direction)(busIndex).valid
        fifoOrDelay.io.input.bits.bits := crossbar.io.outputs(direction)(busIndex).bits
        fifoOrDelay.io.input.bits.header := false.B
        // Note: crossbar outputs are Valid signals with no backpressure
        switch.io.toFifos(direction).ready := false.B
      }

      // If we're in packet mode then the memory outputs go the switch
      // otherwise they go into the pre-output mux.
      // If we're in packet mode then the pre-output mux comes from the switch

      val toOutputs = Wire(new Bus(params.width))
      when (isPacketMode) {
        switch.io.fromFifos(direction) <> fifoOrDelay.io.output
        toOutputs <> switch.io.outputs(direction)
      }.otherwise {
        val oppositeDir = Wire(UInt(2.W))
        when (direction.U === 0.U) {
          oppositeDir := 1.U
        }.elsewhen (direction.U === 1.U) {
          oppositeDir := 0.U
        }.elsewhen (direction.U === 2.U) {
          oppositeDir := 3.U
        }.otherwise {
          oppositeDir := 2.U
        }
        val fromOpposite = io.inputs(oppositeDir)(busIndex)
        val shouldDrive = Wire(Bool())
        when (direction.U === 0.U) {
          shouldDrive := io.control.nDrive(busIndex)
        }.elsewhen (direction.U === 1.U) {
          shouldDrive := io.control.sDrive(busIndex)
        }.elsewhen (direction.U === 2.U) {
          shouldDrive := io.control.wDrive(busIndex)
        }.otherwise {
          shouldDrive := io.control.eDrive(busIndex)
        }
        
        when (shouldDrive && fifoOrDelay.io.output.valid) {
          // Drive our own output from fifoOrDelay
          toOutputs.valid := true.B
          toOutputs.bits := fifoOrDelay.io.output.bits
          fifoOrDelay.io.output.ready := toOutputs.token
          fromOpposite.token := false.B
        }.otherwise {
          // Don't drive - pass through from opposite direction
          toOutputs.valid := fromOpposite.valid
          toOutputs.bits := fromOpposite.bits
          fifoOrDelay.io.output.ready := false.B
          fromOpposite.token := toOutputs.token
        }
        fifoOrDelay.io.output.ready := toOutputs.token
        switch.io.fromFifos(direction).valid := false.B
        switch.io.fromFifos(direction).bits := DontCare
        switch.io.outputs(direction).token := false.B
      }
      
      // Register the outputs.
      io.outputs(direction)(busIndex).valid := RegNext(toOutputs.valid)
      io.outputs(direction)(busIndex).bits := RegNext(toOutputs.bits)
      toOutputs.token := RegNext(io.outputs(direction)(busIndex).token)

    }
  }
  
  // Update DDM arbitration registers
  ddmSelActive := nextDdmSelActive
  ddmRemaining := nextDdmRemaining
  ddmSelPointer := nextDdmSelPointer
  
}


object NetworkNodeGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    // Parse arguments
    if (args.length < 1) {
      println("Usage: <command> <outputDir> NetworkNode <paramsFileName>")
      null
    } else {
      val params = FMPVUParams.fromFile(args(0))
      new NetworkNode(params)
    }
  }
}
