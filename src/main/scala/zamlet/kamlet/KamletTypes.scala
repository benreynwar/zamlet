package zamlet.kamlet

import chisel3._
import zamlet.ZamletParams

class RfUse(params: ZamletParams) extends Bundle {
  val valid = Bool()
  val addr = params.rfAddr()
}

class RfRelease(params: ZamletParams) extends Bundle {
  val uses = Vec(4, new RfUse(params))
}
