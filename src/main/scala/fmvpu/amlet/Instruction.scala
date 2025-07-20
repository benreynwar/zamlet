package fmvpu.amlet

import chisel3._
import chisel3.util._

object Instr {
  abstract class Base(params: AmletParams) extends Bundle
  abstract class Resolved(params: AmletParams) extends Bundle
  abstract class Resolving(params: AmletParams) extends Bundle {
    def isResolved(): Bool
    def resolve(): Resolved
    def isMasked(): Bool
    def update(writes: WriteBacks): Resolving
  }
}

