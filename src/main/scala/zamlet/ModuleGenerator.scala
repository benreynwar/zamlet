package zamlet

import chisel3._
import _root_.circt.stage.ChiselStage
import chisel3.stage.ChiselGeneratorAnnotation

/** Trait for generating Chisel modules with command-line arguments.
  *
  * This trait provides a common interface for all FMVPU module generators,
  * enabling command-line generation of Verilog files with configurable parameters.
  */
trait ModuleGenerator {
  /** Create a module instance with the given arguments.
    *
    * @param args Command line arguments for module configuration
    * @return Module instance configured with the provided arguments
    */
  def makeModule(args: Seq[String]): Module
  
  /** Generate Verilog file for the module.
    *
    * @param outputDir Directory where the generated Verilog file should be written
    * @param args Command line arguments passed to makeModule
    */
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
