package zamlet.lamlet

import chisel3._
import chisel3.util._
import org.chipsalliance.cde.config._
import freechips.rocketchip.rocket._
import freechips.rocketchip.tile._
import freechips.rocketchip.util._

/**
 * Simple vector decoder for Zamlet.
 *
 * Currently only supports unit-stride vector loads and stores.
 * This tells Shuttle which instructions should be sent to the vector unit.
 */
class ZamletVectorDecode(implicit p: Parameters) extends RocketVectorDecoder()(p) {

  // Default outputs
  io.vector := false.B
  io.legal := false.B
  io.fp := false.B
  io.read_rs1 := false.B
  io.read_rs2 := false.B
  io.read_frs1 := false.B
  io.write_rd := false.B
  io.write_frd := false.B

  // Decode fields
  val opcode = io.inst(6, 0)
  val width = io.inst(14, 12)
  val mop = io.inst(27, 26)
  val mew = io.inst(28)

  // Vector load/store opcodes (using LOAD-FP and STORE-FP encoding)
  val opcLoad = "b0000111".U
  val opcStore = "b0100111".U

  // Check for vector memory operations
  // width field: 0=8b, 5=16b, 6=32b, 7=64b (non-vector widths are 1,2,3,4)
  val isVectorWidth = !width.isOneOf(1.U, 2.U, 3.U, 4.U)
  val isVectorLoad = opcode === opcLoad && isVectorWidth
  val isVectorStore = opcode === opcStore && isVectorWidth

  // For now, only support unit-stride (mop=0) with standard element widths
  val isUnitStride = mop === 0.U
  val isValidWidth = width.isOneOf(0.U, 5.U, 6.U, 7.U)

  when(isVectorLoad || isVectorStore) {
    io.vector := true.B
    io.legal := isUnitStride && isValidWidth && mew === 0.U && !io.vconfig.vtype.vill
    io.read_rs1 := true.B  // Base address from rs1
  }
}
