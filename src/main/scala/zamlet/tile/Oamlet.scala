package zamlet.tile

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage

import org.chipsalliance.cde.config._
import org.chipsalliance.diplomacy.lazymodule._
import freechips.rocketchip.subsystem._
import freechips.rocketchip.devices.tilelink._

import shuttle.common._
import zamlet.LamletParams
import zamlet.lamlet.{LamletTop, ZamletParamsKey, ZamletVectorDecode}

import java.io.File

/** Config fragment to use LamletTop as the vector unit */
class WithZamletVector(params: LamletParams) extends Config((site, here, up) => {
  case ZamletParamsKey => params
  case TilesLocated(InSubsystem) => up(TilesLocated(InSubsystem)) map {
    case tp: ShuttleTileAttachParams =>
      tp.copy(tileParams = tp.tileParams.copy(
        core = tp.tileParams.core.copy(
          vector = Some(ShuttleCoreVectorParams(
            build = ((p: Parameters) => new LamletTop()(p)),
            vLen = 128,
            vfLen = 64,
            vfh = false,
            decoder = ((p: Parameters) => Module(new ZamletVectorDecode()(p))),
            issueVConfig = false,
            vExts = Seq(),
          )),
        )
      ))
    case other => other
  }
})

/** Oamlet config - Shuttle with Zamlet vector unit */
class OamletConfig(params: LamletParams) extends Config(
  new WithZamletVector(params) ++
  new shuttle.common.WithNShuttleCores(n = 1, retireWidth = 2) ++
  new WithCoherentBusTopology ++
  new ShuttleBaseConfig
)

/** Small Oamlet config - reduced cache sizes for faster simulation */
class SmallOamletConfig(params: LamletParams) extends Config(
  new shuttle.common.WithL1ICacheSets(32) ++
  new shuttle.common.WithL1ICacheWays(2) ++
  new shuttle.common.WithL1DCacheSets(32) ++
  new shuttle.common.WithL1DCacheWays(2) ++
  new OamletConfig(params)
)

/**
 * OamletTop - wrapper around ShuttleSystem with Zamlet vector unit.
 *
 * Provides concrete reset types for Verilog generation.
 */
class OamletTop(implicit p: Parameters) extends RawModule {
  val clock = IO(Input(Clock()))
  val reset = IO(Input(Bool()))

  val ldut = withClockAndReset(clock, reset) {
    LazyModule(new ShuttleSystem)
  }

  val dut = withClockAndReset(clock, reset) {
    Module(ldut.module)
  }

  // Drive clock infrastructure
  ldut.io_clocks.foreach { clocks =>
    clocks.elements.values.foreach { bundle =>
      bundle.clock := clock
      bundle.reset := reset
    }
  }

  // Expose memory AXI4 port
  val mem_axi4 = IO(chisel3.reflect.DataMirror.internal.chiselTypeClone(ldut.mem_axi4.head))
  mem_axi4 <> ldut.mem_axi4.head

  // Expose MMIO AXI4 port
  val mmio_axi4 = IO(chisel3.reflect.DataMirror.internal.chiselTypeClone(ldut.mmio_axi4.head))
  mmio_axi4 <> ldut.mmio_axi4.head

  // Expose reset vector input
  val reset_vector = IO(Input(UInt(64.W)))
  ldut.module.reset_vector.foreach(_ := reset_vector)

  // Tie off interrupts
  dut.interrupts := 0.U.asTypeOf(dut.interrupts)

  // Tie off debug module
  ldut.debug.foreach { debug =>
    debug.clock := clock
    debug.reset := reset
    debug.clockeddmi.foreach { dmi =>
      dmi.dmi.req.valid := false.B
      dmi.dmi.req.bits := DontCare
      dmi.dmi.resp.ready := false.B
      dmi.dmiClock := clock
      dmi.dmiReset := reset
    }
    debug.dmactiveAck := false.B
  }

  // Tie off reset control
  ldut.resetctrl.foreach { rc =>
    rc.hartIsInReset.foreach(_ := reset)
  }
}

/** Entry point for generating Oamlet Verilog */
object OamletMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <zamletConfigFile> [size]")
    println("  size: normal (default) or small")
    System.exit(1)
  }

  val outputDir = args(0)
  val configFile = args(1)
  val size = args.lift(2).getOrElse("normal")

  // Load Zamlet params from config file
  val zParams = LamletParams.fromFile(configFile)

  // Create output directory
  val outDirFile = new File(outputDir)
  if (!outDirFile.exists()) {
    outDirFile.mkdirs()
  }

  implicit val p: Parameters = size match {
    case "small" => new SmallOamletConfig(zParams)
    case "normal" | _ => new OamletConfig(zParams)
  }

  ChiselStage.emitSystemVerilogFile(
    gen = new OamletTop,
    args = Array("--target-dir", outputDir),
    firtoolOpts = Array(
      "-disable-all-randomization",
      "-strip-debug-info",
    )
  )
}
