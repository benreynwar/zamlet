package zamlet.shuttle

import chisel3._
import chisel3.util._

import org.chipsalliance.cde.config._
import org.chipsalliance.diplomacy.lazymodule._

/** Thin wrapper around ShuttleSystem that provides concrete reset types.
  *
  * This exists solely to solve the firtool "public module port must have concrete reset type"
  * error. The inner ShuttleSystem module can be used directly if needed.
  */
class ShuttleTop(implicit p: Parameters) extends RawModule {
  val clock = IO(Input(Clock()))
  val reset = IO(Input(Bool()))

  val ldut = withClockAndReset(clock, reset) {
    LazyModule(new ShuttleSystem)
  }

  val dut = withClockAndReset(clock, reset) {
    Module(ldut.module)
  }

  // Drive clock infrastructure with concrete reset type
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
