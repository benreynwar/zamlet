package zamlet.shuttle

import chisel3._
import _root_.circt.stage.ChiselStage

import org.chipsalliance.cde.config._
import org.chipsalliance.diplomacy.lazymodule._
import java.io.File

/** Entry point for generating ShuttleSystem Verilog.
  *
  * Usage: <outputDir> [config]
  *   config: "minimal" (default) or "small"
  */
object Main extends App {
  if (args.length < 1) {
    println("Usage: <outputDir> [config]")
    println("  config: minimal (default), small")
    System.exit(1)
  }

  val outputDir = args(0)
  val configName = args.lift(1).getOrElse("minimal")

  // Create output directory
  val outDirFile = new File(outputDir)
  if (!outDirFile.exists()) {
    outDirFile.mkdirs()
  }

  implicit val p: Parameters = configName match {
    case "small" => new SmallShuttleConfig
    case "minimal" | _ => new MinimalShuttleConfig
  }

  ChiselStage.emitSystemVerilogFile(
    gen = new ShuttleTop,
    args = Array("--target-dir", outputDir),
    firtoolOpts = Array(
      "-disable-all-randomization",
      "-strip-debug-info",
    )
  )
}
