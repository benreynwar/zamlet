package fmvpu.utils

import chisel3._
import chisel3.util._
import fmvpu.ModuleGenerator

// This FIFO takes an additional input 'drop' that indicates that the input at
// 'i' can be discarded.
//
// It produces an output 'count' which indicates how many inputs have been consumed
// since that item was consumed.

class DroppingFifo[T <: Data](t: T, depth: Int, countBits: Int) extends Module {
  val io = IO(new Bundle {
    val i = Flipped(DecoupledIO(t))
    // If drop is high we discard the value on o
    val drop = Input(Bool())
    val o = DecoupledIO(t)
    // How many inputs we've consumed since this item entered the fifo.
    val count = Output(UInt(countBits.W))
    // Expose all internal contents and counts for dependency checking
    val allContents = Output(Vec(depth, t))
    val allCounts = Output(Vec(depth, UInt(countBits.W)))
    val allValids = Output(Vec(depth, Bool()))
  })

  val contents = Reg(Vec(depth, t))
  val counts = Reg(Vec(depth, UInt(countBits.W)))
  val writePtr = RegInit(UInt(log2Ceil(depth).W), 0.U)
  val readPtr = RegInit(UInt(log2Ceil(depth).W), 0.U)
  val empty = RegInit(Bool(), true.B)
  val full = RegInit(Bool(), false.B)

  io.i.ready := !full || io.drop || (full && io.o.ready)

  when (io.i.valid && io.i.ready) {
    // Increment all counts since an input was consumed
    for (i <- 0 until depth) {
      counts(i) := counts(i) + 1.U
    }
    when (!io.drop) {
      contents(writePtr) := io.i.bits
      counts(writePtr) := 0.U
      writePtr := (writePtr + 1.U) % depth.U
      empty := false.B
      full := (writePtr + 1.U) % depth.U === readPtr
    }
  }
  io.o.valid := !empty
  io.o.bits := contents(readPtr)
  io.count := counts(readPtr)

  when (io.o.valid && io.o.ready) {
    readPtr := (readPtr + 1.U) % depth.U
    empty := (readPtr + 1.U) % depth.U === writePtr
    full := false.B
  }

  // If we're writing (not dropping), we can't be empty
  when (io.i.valid && io.i.ready && !io.drop) {
    empty := false.B
  }

  // Connect outputs for internal state
  io.allContents := contents
  io.allCounts := counts
  
  // Determine which entries are valid based on read/write pointers
  val validBits = Wire(Vec(depth, Bool()))
  val iLTWritePtr = Wire(Vec(depth, Bool()))
  for (i <- 0 until depth) {
    if (i == depth-1) {
      iLTWritePtr(i) := false.B
    } else {
      iLTWritePtr(i) := (i.U < writePtr)
    }
    when (readPtr === writePtr) {
      validBits(i) := full
    } .elsewhen (writePtr > readPtr) {
      validBits(i) := (i.U >= readPtr && iLTWritePtr(i))
    } .otherwise {
      validBits(i) := (i.U >= readPtr || iLTWritePtr(i))
    }


    when (empty) {
      validBits(i) := false.B
    } .elsewhen (full) {
      validBits(i) := true.B
    } .otherwise {
      
      if (i == 0) {
        validBits(i) := (writePtr > readPtr && 0.U >= readPtr && 0.U < writePtr) || 
                        (writePtr <= readPtr && (0.U >= readPtr || 0.U < writePtr))
      } else if (i == depth - 1) {
        // For the last index, readPtr <= (depth-1) is always true for valid pointers
        validBits(i) := (writePtr > readPtr && true.B && false.B) || 
                        (writePtr <= readPtr && (true.B || false.B))
      } else {
        validBits(i) := (writePtr > readPtr && i.U >= readPtr && i.U < writePtr) || 
                        (writePtr <= readPtr && (i.U >= readPtr || i.U < writePtr))
      }
    }
  }
  io.allValids := validBits

}

object DroppingFifoGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 3) {
      println("Usage: <command> <outputDir> DroppingFifo <width> <depth> <countBits>")
      null
    } else {
      val width = args(0).toInt
      val depth = args(1).toInt
      val countBits = args(2).toInt
      new DroppingFifo(UInt(width.W), depth, countBits)
    }
  }
}
