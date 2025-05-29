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
  val nsInputSel =  Vec(params.nBuses, Bool());
  val weInputSel =  Vec(params.nBuses, Bool());
  val nsCrossbarSel = Vec(params.nBuses, UInt(log2Ceil(params.nBuses+2).W));
  val weCrossbarSel = Vec(params.nBuses, UInt(log2Ceil(params.nBuses+2).W));
  val drfSel = UInt(log2Ceil(params.nBuses*2).W);
  val ddmSel = UInt(log2Ceil(params.nBuses*2).W);
  }

class NetworkNode(params: FMPVUParams) extends Module {
  val inputs = IO(Vec(4, Vec(params.nBuses, new Bus(params.width))))
  val outputs = IO(Vec(4, Vec(params.nBuses, Flipped(new Bus(params.width)))))
  val toDRF = IO(Output(Valid(UInt(params.width.W))))
  val fromDRF = IO(Input(Valid(UInt(params.width.W))))
  val toDDM = IO(Output(Valid(new HeaderTag(UInt(params.width.W)))))
  val fromDDM = IO(Input(Valid(UInt(params.width.W))))
  val control = IO(Input(new NetworkNodeControl(params)))
  val thisLoc = IO(Input(new Location(params)))

  // Just here to define modules
  val withHeaderTemplate = new HeaderTag(UInt(params.width.W))

  val configValid = IO(Input(Bool()))
  val configIsPacketMode = IO(Input(Bool()))
  val configDelay = IO(Input(UInt(log2Ceil(params.networkMemoryDepth+1).W)))

  val isPacketMode = RegInit(true.B)

  when (configValid) {
    isPacketMode := configIsPacketMode
  }

  val crossbar = Module(new NetworkCrossbar(params))

  // Create a wire to aggregate all switch toDDM outputs
  val switchesToDDM = Wire(DecoupledIO(new HeaderTag(UInt(params.width.W))))

  // To the DDM from either the switch or the crossbar
  when (isPacketMode) {
    toDDM.valid := switchesToDDM.valid
    toDDM.bits := switchesToDDM.bits
    switchesToDDM.ready := true.B
  }.otherwise {
    toDDM.valid := crossbar.toDDM.valid
    toDDM.bits.bits := crossbar.toDDM.bits
    toDDM.bits.header := false.B
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

  crossbar.fromDRF := fromDRF
  toDRF := crossbar.toDRF
  crossbar.fromDDM := fromDDM
  crossbar.control := control

  // Create all switch instances
  val switches = Seq.fill(params.nBuses)(withReset(reset.asBool || configValid) { Module(new NetworkSwitch(params)) })

  val allSwitchToDDM = Wire(Vec(params.nBuses, DecoupledIO(new HeaderTag(UInt(params.width.W)))))
  for (i <- 0 until params.nBuses) {
    allSwitchToDDM(i) <> switches(i).toDDM
  }
  switchesToDDM.valid := allSwitchToDDM(ddmSelPointer).valid && isPacketMode
  switchesToDDM.bits := allSwitchToDDM(ddmSelPointer).bits

  for (busIndex <- 0 until params.nBuses) {
    val switch = switches(busIndex)
    switch.thisLoc := thisLoc
    
    // Currently we don't have any way for the DDM to initiate sending a packet
    // so this is inactive.
    switch.fromDDM.valid := false.B
    switch.fromDDM.bits := DontCare
    
    // DDM arbitration: only the selected switch can write to DDM
    when (isPacketMode && ddmSelPointer === busIndex.U) {
      allSwitchToDDM(busIndex).ready := switchesToDDM.ready
      // This switch is selected for DDM access
      when (!ddmSelActive) {
        // Not currently active - check if this switch wants to start a packet
        when (switch.toDDM.valid && switch.toDDM.bits.header) {
          // Switch wants to start a new packet, grant access
          nextDdmSelActive := true.B
          // Extract packet length from header
          val header = Header.fromBits(switch.toDDM.bits.bits, params)
          nextDdmRemaining := header.length
        }.otherwise {
          nextDdmSelPointer := (ddmSelPointer + 1.U) % params.nBuses.U
        }
      }.otherwise {
        // Decrement remaining count on successful transfer
        when (switch.toDDM.valid && switch.toDDM.ready) {
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
        switch.inputs(direction) <> inputs(direction)(busIndex)
        crossbar.inputs(direction)(busIndex).valid := false.B
        crossbar.inputs(direction)(busIndex).bits := DontCare
      }.otherwise {
        switch.inputs(direction).valid := false.B
        switch.inputs(direction).bits := DontCare
        inputs(direction)(busIndex).token := false.B
        crossbar.inputs(direction)(busIndex) := inputs(direction)(busIndex).toValid()
      }

      val fifoOrDelay = Module(new FifoOrDelay(withHeaderTemplate, params.networkMemoryDepth))
      fifoOrDelay.configValid := configValid
      fifoOrDelay.configIsFifo := configIsPacketMode
      fifoOrDelay.configDelay := configDelay

      // If we're in packet mode then the memory inputs come from the switch
      // otherwise the inputs come from the crossbar
      when (isPacketMode) {
        fifoOrDelay.input <> switch.toFifos(direction)
      }.otherwise {
        fifoOrDelay.input.valid := crossbar.outputs(direction)(busIndex).valid
        fifoOrDelay.input.bits.bits := crossbar.outputs(direction)(busIndex).bits
        fifoOrDelay.input.bits.header := false.B
        // Note: crossbar outputs are Valid signals with no backpressure
        switch.toFifos(direction).ready := false.B
      }

      // If we're in packet mode then the memory outputs go the switch
      // otherwise they go into the pre-output mux.
      // If we're in packet mode then the pre-output mux comes from the switch

      val toOutputs = Wire(new Bus(params.width))
      when (isPacketMode) {
        switch.fromFifos(direction) <> fifoOrDelay.output
        toOutputs <> switch.outputs(direction)
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
        val fromOpposite = inputs(oppositeDir)(busIndex)
        // Output from fifoOrDelay gets precedence
        when (fifoOrDelay.output.valid) {
          toOutputs.valid := true.B
          toOutputs.bits := fifoOrDelay.output.bits
          fifoOrDelay.output.ready := toOutputs.token
          fromOpposite.token := false.B
        }.otherwise {
          toOutputs.valid := fromOpposite.valid
          toOutputs.bits := fromOpposite.bits
          fifoOrDelay.output.ready := false.B
          fromOpposite.token := toOutputs.token
        }
        fifoOrDelay.output.ready := toOutputs.token
        switch.fromFifos(direction).valid := false.B
        switch.fromFifos(direction).bits := DontCare
        switch.outputs(direction).token := false.B
      }
      
      // Register the outputs.
      outputs(direction)(busIndex).valid := RegNext(toOutputs.valid)
      outputs(direction)(busIndex).bits := RegNext(toOutputs.bits)
      toOutputs.token := RegNext(outputs(direction)(busIndex).token)

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
      return null
    }
    val params = FMPVUParams.fromFile(args(0));
    return new NetworkNode(params);
  }

}
