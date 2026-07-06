package zamlet.utils

import chisel3._
import chisel3.util._
import zamlet.ModuleGenerator

class SeenTagBufferEntry[D <: Data, T <: Data](dataType: D, tagType: T) extends Bundle {
  val data = dataType.cloneType
  val tag = tagType.cloneType
  val seen = Bool()
}

object SeenTagBuffer {
  def updateSeen[D <: Data, T <: Data](
    dataType: D,
    tagType: T,
  )(entry: SeenTagBufferEntry[D, T], broadcastTag: T): SeenTagBufferEntry[D, T] = {
    val updated = Wire(new SeenTagBufferEntry(dataType, tagType))
    updated := entry
    when (entry.tag === broadcastTag) {
      updated.seen := true.B
    }
    updated
  }
}

class SeenTagBuffer[D <: Data, T <: Data](
  dataType: D,
  tagType: T,
  enableForward: Boolean = true,
  enableBackward: Boolean = true,
) extends Module {
  val io = IO(new Bundle {
    val i = Flipped(Decoupled(new SeenTagBufferEntry(dataType, tagType)))
    val o = Decoupled(new SeenTagBufferEntry(dataType, tagType))
    val broadcastIn = Flipped(Valid(tagType.cloneType))
    val broadcastOut = Valid(tagType.cloneType)
    val fromState = Output(Bool())
    val hidden = Output(Valid(new SeenTagBufferEntry(dataType, tagType)))
  })

  val buffer = Module(new BroadcastUpdateBuffer(
    new SeenTagBufferEntry(dataType, tagType),
    tagType,
    SeenTagBuffer.updateSeen(dataType, tagType),
    enableForward,
    enableBackward))
  buffer.io.i <> io.i
  buffer.io.broadcastIn := io.broadcastIn
  io.o <> buffer.io.o
  io.broadcastOut := buffer.io.broadcastOut
  io.fromState := buffer.io.fromState
  io.hidden := buffer.io.hidden
}

object SeenTagBufferGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.length < 2) {
      println("Usage: <command> <outputDir> SeenTagBuffer <dataWidth> <tagWidth>")
      null
    } else {
      new SeenTagBuffer(UInt(args(0).toInt.W), UInt(args(1).toInt.W))
    }
  }
}

object SeenTagBufferMain extends App {
  if (args.length < 3) {
    println("Usage: <outputDir> <dataWidth> <tagWidth>")
    System.exit(1)
  }
  SeenTagBufferGenerator.generate(args(0), args.drop(1))
}
