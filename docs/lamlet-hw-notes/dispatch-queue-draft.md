# DispatchQueue (First Draft)

Buffers kinstrs, batches them by k_index, and generates network packets.

## Overview

The DispatchQueue sits between IdentTracker and Ch0Sender. It:
1. Receives kinstrs from IdentTracker (idents already filled in)
2. Batches kinstrs for the same k_index
3. Generates network packets (header + instruction words)
4. Sends packets to Ch0Sender

IdentQuery is just another kinstr in the stream - no special handling needed.

## Interfaces

```
DispatchQueue

// Kinstr input (from IdentTracker)
├── IN:  in.valid
├── IN:  in.bits.kinstr     (ident already filled in)
├── IN:  in.bits.k_index    (target kamlet, or broadcast)
├── OUT: in.ready

// Packet output (to Ch0Sender)
├── OUT: out.valid
├── OUT: out.bits           (network word: header or kinstr)
├── IN:  out.ready
```

Outputs one network word per cycle. Header first, then kinstr words.

## Parameters

```scala
val MaxBatchSize = 4      // max instructions per packet
val QueueDepth = 8        // instruction buffer depth
val TimeoutCycles = 3     // send partial batch after this many idle cycles
```

## State

```scala
// Instruction queue (FIFO)
val queue = Module(new Queue(new KinstrEntry, QueueDepth))

class KinstrEntry extends Bundle {
    val kinstr = UInt(64.W)   // packed kinstr
    val k_index = UInt(...)   // target kamlet or broadcast flag
}

// Batching state
val batch = Reg(Vec(MaxBatchSize, UInt(64.W)))  // just the kinstrs
val batch_count = RegInit(0.U)
val batch_k_index = Reg(UInt(...))

// Packet sending state
val sending = RegInit(false.B)
val send_idx = RegInit(0.U)  // 0 = header, 1+ = kinstr words

// Timeout counter
val idle_count = RegInit(0.U(2.W))
```

## Batching Logic

```scala
// When to send the current batch
val batch_full = (batch_count === MaxBatchSize.U)
val k_index_mismatch = queue.io.deq.valid &&
                       (batch_count > 0.U) &&
                       (queue.io.deq.bits.k_index =/= batch_k_index)
val timeout = (idle_count >= TimeoutCycles.U) && (batch_count > 0.U)

val should_send = (batch_full || k_index_mismatch || timeout) && !sending
```

## Packet Format

Network packet for instructions:
- Word 0: Header (target coords, source coords, length, message type)
- Words 1+: Kinstr data (64 bits each)

```scala
def make_header(k_index: UInt, count: UInt): UInt = {
    val target_x = ...  // from k_index
    val target_y = ...  // from k_index
    val source_x = 0.U  // lamlet position
    val source_y = (-1).S.asUInt  // lamlet at y=-1
    val length = count + 1.U  // header + kinstrs
    val message_type = MessageType.INSTRUCTIONS
    val send_type = Mux(k_index.is_broadcast, SendType.BROADCAST, SendType.SINGLE)
    // Pack into header word
    ...
}
```

## Main Logic

```scala
// Output: send header or kinstr word
io.out.valid := sending
io.out.bits := Mux(send_idx === 0.U,
    make_header(batch_k_index, batch_count),
    batch(send_idx - 1.U)
)

when (sending && io.out.ready) {
    send_idx := send_idx + 1.U
    when (send_idx === batch_count) {
        // Done sending packet
        sending := false.B
        send_idx := 0.U
        batch_count := 0.U
    }
}

// Input: accept when not sending and queue has room
io.in.ready := !sending && queue.io.enq.ready

// Batching: pull from queue when not sending
when (!sending) {
    when (should_send) {
        // Start sending
        sending := true.B
        idle_count := 0.U
    } .elsewhen (queue.io.deq.valid) {
        // Add to batch
        val entry = queue.io.deq.bits
        queue.io.deq.ready := true.B

        when (batch_count === 0.U) {
            batch_k_index := entry.k_index
        }
        batch(batch_count) := entry.kinstr
        batch_count := batch_count + 1.U
        idle_count := 0.U
    } .elsewhen (batch_count > 0.U) {
        idle_count := idle_count + 1.U
    }
}
```

## Design Decisions

1. **Fixed timeout**: 3 cycles. Balances latency vs batching efficiency.

2. **Queue depth 8**: Enough to absorb bursts while IssueUnit waits for TLB etc.

3. **k_index mismatch triggers send**: When a different k_index appears, flush current batch.
   This naturally handles IdentQuery (broadcast) arriving after targeted kinstrs.
