package zamlet.lamlet

import chisel3._
import chisel3.util._
import zamlet.LamletParams
import zamlet.jamlet.{NetworkWord, PacketHeader, SendType, MessageType}

/**
 * DispatchQueue buffers kinstrs, batches them by target kamlet, and generates network packets.
 *
 * Sits between IdentTracker and the mesh network. It:
 * 1. Receives kinstrs from IdentTracker (idents already filled in)
 * 2. Batches kinstrs for the same k_index
 * 3. Generates network packets (header + instruction words)
 * 4. Sends packets to mesh network
 *
 * IdentQuery is just another kinstr in the stream - no special handling needed.
 */
class DispatchQueue(params: LamletParams) extends Module {
  val MaxBatchSize = 4
  val TimeoutCycles = 3

  val io = IO(new Bundle {
    // Kinstr input (from IdentTracker)
    val in = Flipped(Decoupled(new KinstrWithTarget(params)))

    // Packet output (to mesh network)
    val out = Decoupled(new NetworkWord(params))
  })

  // Instruction queue (FIFO)
  val queue = Module(new Queue(new KinstrWithTarget(params), params.lamletDispatchQueueDepth))
  queue.io.enq <> io.in

  // Batching state
  val batch = Reg(Vec(MaxBatchSize, UInt(64.W)))
  val batchCount = RegInit(0.U(log2Ceil(MaxBatchSize + 1).W))
  val batchKIndex = Reg(UInt(params.kIndexWidth.W))
  val batchIsBroadcast = Reg(Bool())

  // Packet sending state
  val sending = RegInit(false.B)
  val sendIdx = RegInit(0.U(log2Ceil(MaxBatchSize + 2).W))  // 0 = header, 1+ = kinstr words

  // Timeout counter
  val idleCount = RegInit(0.U(log2Ceil(TimeoutCycles + 1).W))

  // When to send the current batch
  val batchFull = (batchCount === MaxBatchSize.U)
  val kIndexMismatch = queue.io.deq.valid &&
                       (batchCount > 0.U) &&
                       (queue.io.deq.bits.kIndex =/= batchKIndex ||
                        queue.io.deq.bits.isBroadcast =/= batchIsBroadcast)
  val timeout = (idleCount >= TimeoutCycles.U) && (batchCount > 0.U)

  val shouldSend = (batchFull || kIndexMismatch || timeout) && !sending

  // Generate packet header
  def makeHeader(kIndex: UInt, isBroadcast: Bool, count: UInt): UInt = {
    val header = Wire(new PacketHeader(params))
    // Lamlet is at position (0, -1), sending south into mesh
    // For broadcast, target is bottom-right corner (kCols-1, kRows-1)
    // For single, target is the specific kamlet
    when (isBroadcast) {
      header.targetX := (params.kCols - 1).U
      header.targetY := (params.kRows - 1).U
    } .otherwise {
      // Convert k_index to (x, y) coordinates
      header.targetX := kIndex % params.kCols.U
      header.targetY := kIndex / params.kCols.U
    }
    header.sourceX := 0.U
    header.sourceY := 0.U  // Will be interpreted as -1 by receivers
    header.length := count  // number of data words following header
    header.messageType := MessageType.Instructions
    header.sendType := Mux(isBroadcast, SendType.Broadcast, SendType.Single)
    header.asUInt
  }

  // Output: send header or kinstr word
  io.out.valid := sending
  io.out.bits.isHeader := (sendIdx === 0.U)
  io.out.bits.data := Mux(sendIdx === 0.U,
    makeHeader(batchKIndex, batchIsBroadcast, batchCount),
    batch(sendIdx - 1.U)
  )

  // Dequeue from internal queue
  queue.io.deq.ready := false.B

  when (sending) {
    when (io.out.ready) {
      sendIdx := sendIdx + 1.U
      when (sendIdx === batchCount) {
        // Done sending packet
        sending := false.B
        sendIdx := 0.U
        batchCount := 0.U
      }
    }
  } .otherwise {
    when (shouldSend) {
      // Start sending
      sending := true.B
      idleCount := 0.U
    } .elsewhen (queue.io.deq.valid) {
      // Add to batch
      queue.io.deq.ready := true.B

      val entry = queue.io.deq.bits
      when (batchCount === 0.U) {
        batchKIndex := entry.kIndex
        batchIsBroadcast := entry.isBroadcast
      }
      batch(batchCount) := entry.kinstr
      batchCount := batchCount + 1.U
      idleCount := 0.U
    } .elsewhen (batchCount > 0.U) {
      idleCount := idleCount + 1.U
    }
  }
}
