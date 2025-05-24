package fvpu

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation

trait ModuleGenerator {
  def makeModule(args: Seq[String]): Module
  def generate(outputDir: String, args: Seq[String]): Unit = {
    ChiselStage.emitSystemVerilogFile(
      gen = makeModule(args),
      args = Array(
        "--target-dir", outputDir,
        ),
      firtoolOpts = Array(
        "-disable-all-randomization",
        "-strip-debug-info",
        "-disable-opt",
        "-default-layer-specialization=enable",
      )
    )
  }
}
