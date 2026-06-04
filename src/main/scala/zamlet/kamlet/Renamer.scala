package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.KInstr

class RenamerIO(params: ZamletParams) extends Bundle {
  val kinstrIn = Flipped(Decoupled(UInt(KInstr.width.W)))
  val renamedOut = Decoupled(UInt(KInstr.width.W))

  val rsRelease = Flipped(Decoupled(params.rfAddr()))
  val kteRelease = Flipped(Decoupled(params.rfAddr()))
}

class Renamer(params: ZamletParams) extends Module {
  val io = IO(new RenamerIO(params))

  // First-pass behavior: pass raw kinstrs through until the rename map and
  // physical-register free-list are implemented.
  io.renamedOut.valid := io.kinstrIn.valid
  io.renamedOut.bits := io.kinstrIn.bits
  io.kinstrIn.ready := io.renamedOut.ready

  io.rsRelease.ready := true.B
  io.kteRelease.ready := true.B
}
