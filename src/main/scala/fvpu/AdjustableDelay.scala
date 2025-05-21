package fvpu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation
import java.io.{File, PrintWriter}

import chisel3.util.log2Ceil
import chisel3.util.Valid

import fvpu.ModuleGenerator

class AdjustableDelay(maxDelay: Int, width: Int) extends Module {
  val delay = IO(Input(UInt(log2Ceil(maxDelay+1).W)));
  val input = IO(Input(Valid(UInt(width.W))));
  val output = IO(Output(Valid(UInt(width.W))));
  val errors = IO(Output(UInt(1.W)));

  val regs = Reg(Vec(maxDelay, Valid(UInt(width.W))));

  for (i <- 0 until maxDelay-1) {
    regs(i) := Mux((delay === (i+1).U) && input.valid, input, regs(i+1));
  }
  regs(maxDelay-1) := Mux(delay === maxDelay.U, input, 0.U.asTypeOf(Valid(UInt(width.W))));

  output := Mux(delay === 0.U && input.valid, input, regs(0));

  errors := Mux(delay < maxDelay.U, input.valid && regs(delay(log2Ceil(maxDelay)-1, 0)).valid, 0.U);
}


object AdjustableDelayGenerator extends ModuleGenerator {

  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 2) {
      println("Usage: <command> <outputDir> AdjustableDelay <maxDelay> <width>");
      return null;
    }
    val maxDelay = args(0).toInt;
    val width = args(1).toInt;
    return new AdjustableDelay(maxDelay, width);
  }

}
