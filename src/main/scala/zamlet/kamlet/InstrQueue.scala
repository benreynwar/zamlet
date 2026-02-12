package zamlet.kamlet

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.jamlet.{NetworkWord, PacketHeader, MessageType}

/**
 * InstrQueue error signals.
 */
class InstrQueueErrors extends Bundle {
  val unexpectedHeader = Bool()    // Got header when expecting data
  val unexpectedData = Bool()      // Got data when expecting header
}

/**
 * InstrQueue receives instruction packets from jamlets and extracts kinstrs.
 *
 * Packet format:
 * - Word 0 (isHeader=true): PacketHeader with length field
 * - Words 1..length (isHeader=false): 64-bit kinstr data
 *
 * This module strips the header and queues the kinstr payloads.
 */
class InstrQueue(params: ZamletParams, depth: Int = 8) extends Module {
  val io = IO(new Bundle {
    // Packet input (from jamlet)
    val packetIn = Flipped(Decoupled(new NetworkWord(params)))

    // Kinstr output (to InstrExecutor)
    val kinstrOut = Decoupled(UInt(64.W))

    // Error signals
    val errors = Output(new InstrQueueErrors)
  })

  // Internal FIFO for kinstrs
  val queue = Module(new Queue(UInt(64.W), depth))
  io.kinstrOut <> queue.io.deq

  // Packet reception state
  val sIdle :: sReceiving :: Nil = Enum(2)
  val state = RegInit(sIdle)

  val remainingWords = RegInit(0.U(4.W))

  // Default outputs
  io.packetIn.ready := false.B
  queue.io.enq.valid := false.B
  queue.io.enq.bits := io.packetIn.bits.data
  io.errors.unexpectedHeader := false.B
  io.errors.unexpectedData := false.B

  switch (state) {
    is (sIdle) {
      // Wait for header
      io.packetIn.ready := true.B

      when (io.packetIn.fire) {
        when (io.packetIn.bits.isHeader) {
          // Extract header to get length
          val header = io.packetIn.bits.data.asTypeOf(new PacketHeader(params))

          // Only process Instructions packets
          when (header.messageType === MessageType.Instructions && header.length > 0.U) {
            remainingWords := header.length
            state := sReceiving
          }
        } .otherwise {
          // Got data when expecting header
          io.errors.unexpectedData := true.B
        }
      }
    }

    is (sReceiving) {
      // Receive kinstr words, enqueue to FIFO
      io.packetIn.ready := queue.io.enq.ready

      when (io.packetIn.fire) {
        when (!io.packetIn.bits.isHeader) {
          queue.io.enq.valid := true.B

          remainingWords := remainingWords - 1.U
          when (remainingWords === 1.U) {
            state := sIdle
          }
        } .otherwise {
          // Got header when expecting data
          io.errors.unexpectedHeader := true.B
        }
      }
    }
  }
}
