# IdentTracker (First Draft)

Tracks instruction identifiers and per-kamlet tokens for flow control.

**Full implementation** - this is a critical flow control component.

## Overview

The IdentTracker manages two backpressure mechanisms:

1. **Ident space**: Prevents `instr_ident` wraparound collisions (128 values wrap)
2. **Kamlet queue tokens**: Prevents overflowing per-kamlet instruction queues

Both use the IdentQuery mechanism via the sync network.

## Interfaces

```
IdentTracker

// Kinstr stream (IssueUnit → IdentTracker → DispatchQueue)
├── IN:  in.valid            (kinstr from IssueUnit)
├── IN:  in.bits.kinstr      (ident field empty)
├── IN:  in.bits.k_index     (target kamlet, or broadcast)
├── OUT: in.ready            (idents and tokens available)
├── OUT: out.valid           (kinstr with ident filled, or IdentQuery)
├── OUT: out.bits.kinstr     (ident field filled in)
├── OUT: out.bits.k_index    (target kamlet, or broadcast for IdentQuery)
├── IN:  out.ready           (DispatchQueue can accept)

// Sync network (Synchronizer interface)
├── OUT: sync_local_event.valid      (lamlet participating in sync)
├── OUT: sync_local_event.sync_ident (which sync operation)
├── OUT: sync_local_event.value      (lamlet's distance for MIN aggregation)
├── IN:  sync_result.valid           (sync network completed)
├── IN:  sync_result.sync_ident      (which sync operation completed)
├── IN:  sync_result.value           (aggregated minimum distance)

// Status
├── OUT: backend_busy        (any outstanding work?)
```

IdentTracker is a stream processor: fills in ident field, can inject IdentQuery into output.

## State

```scala
// Ident allocation
val next_instr_ident = RegInit(0.U(7.W))        // what we've allocated (wraps at 128)
val oldest_active_ident = RegInit(0.U(7.W))      // from IdentQuery response
val oldest_active_valid = RegInit(false.B)       // have we received a response?

// Per-kamlet tokens (k_in_l counters)
val available_tokens = RegInit(VecInit(Seq.fill(k_in_l)(queue_length.U)))
val tokens_used_since_query = RegInit(VecInit(Seq.fill(k_in_l)(0.U)))
val tokens_in_active_query = RegInit(VecInit(Seq.fill(k_in_l)(0.U)))

// IdentQuery state machine
val iq_state = RegInit(DORMANT)  // DORMANT, READY_TO_SEND, WAITING_FOR_RESPONSE
val iq_baseline = Reg(UInt(7.W))
val iq_lamlet_dist = Reg(UInt(8.W))  // lamlet's own distance value
val last_sent_instr_ident = RegInit((max_response_tags - 2).U(7.W))
```

## Available Idents Calculation

From `ident_query.py:get_available_idents()`:

```python
if oldest_active_ident is None:
    result = max_tags - next_instr_ident - 1
else:
    result = (oldest_active_ident - next_instr_ident) % max_tags - 1
```

In hardware:
```scala
val available_idents = Mux(oldest_active_valid,
    (oldest_active_ident - next_instr_ident)(6, 0) - 1.U,  // modular subtract
    (max_tags.U - next_instr_ident - 1.U)
)
```

## Token Availability Check

Regular instructions need > 1 token (last reserved for IdentQuery).
IdentQuery only needs > 0 tokens.

```scala
def have_tokens(k_index: Option[UInt], is_ident_query: Boolean): Bool = {
    val min_tokens = if (is_ident_query) 0.U else 1.U
    k_index match {
        case None => available_tokens.forall(_ > min_tokens)  // broadcast
        case Some(k) => available_tokens(k) > min_tokens
    }
}
```

## Stream Processing Logic

```scala
// Input ready when: idents available, tokens available, output ready, not sending IdentQuery
val can_accept_input = (available_idents >= 1.U) &&
                       have_tokens(io.in.bits.k_index, false) &&
                       io.out.ready &&
                       !sending_ident_query

io.in.ready := can_accept_input

// Output: either pass through input with ident filled, or inject IdentQuery
val sending_ident_query = (iq_state === READY_TO_SEND) && io.out.ready

io.out.valid := io.in.fire || sending_ident_query

when (sending_ident_query) {
    // Inject IdentQuery (priority over regular kinstrs)
    io.out.bits.kinstr := ident_query_kinstr
    io.out.bits.k_index := BROADCAST
} .otherwise {
    // Pass through with ident filled in
    io.out.bits.kinstr := io.in.bits.kinstr.with_ident(next_instr_ident)
    io.out.bits.k_index := io.in.bits.k_index
}

// On regular kinstr pass-through
when (io.in.fire) {
    next_instr_ident := (next_instr_ident + 1.U)(6, 0)  // wrap at 128
    last_sent_instr_ident := next_instr_ident

    // Use token for target kamlet
    when (io.in.bits.k_index.is_broadcast) {
        for (k <- 0 until k_in_l) {
            available_tokens(k) := available_tokens(k) - 1.U
            tokens_used_since_query(k) := tokens_used_since_query(k) + 1.U
        }
    } .otherwise {
        val k = io.in.bits.k_index
        available_tokens(k) := available_tokens(k) - 1.U
        tokens_used_since_query(k) := tokens_used_since_query(k) + 1.U
    }
}
```

## IdentQuery Generation

Trigger conditions (from Python model):
```scala
val should_send_query = (iq_state === DORMANT) && (
    (available_idents < (max_tags / 2).U) ||           // idents running low
    available_tokens.exists(_ < (queue_length / 2).U)   // any kamlet queue low
)

// Transition to READY_TO_SEND
when (should_send_query) {
    iq_state := READY_TO_SEND
    iq_baseline := (next_instr_ident - 1.U)(6, 0)
    iq_lamlet_dist := ???  // see Open Questions
}

// IdentQuery kinstr (injected into output stream when READY_TO_SEND)
val ident_query_kinstr = IdentQuery(
    instr_ident = ident_query_ident,  // dedicated ident for queries
    baseline = iq_baseline,
    previous_instr_ident = last_sent_instr_ident
)

// When IdentQuery is sent via output stream
when (sending_ident_query) {
    // Move tokens to active query tracker
    for (k <- 0 until k_in_l) {
        tokens_in_active_query(k) := tokens_used_since_query(k)
        tokens_used_since_query(k) := 0.U
    }
    iq_state := WAITING_FOR_RESPONSE
}

// Sync network local event (fires same cycle as IdentQuery output)
io.sync_local_event.valid := sending_ident_query
io.sync_local_event.sync_ident := ident_query_ident
io.sync_local_event.value := iq_lamlet_dist
```

## IdentQuery Response Handling

When sync network result arrives:
```scala
when (io.sync_result.valid && io.sync_result.sync_ident === ident_query_ident) {
    val min_distance = io.sync_result.value

    // Update oldest_active_ident
    when (min_distance === max_tags.U) {
        oldest_active_ident := iq_baseline
    } .otherwise {
        oldest_active_ident := (iq_baseline + min_distance)(6, 0)
    }
    oldest_active_valid := true.B

    // Return tokens from completed query
    for (k <- 0 until k_in_l) {
        available_tokens(k) := available_tokens(k) + tokens_in_active_query(k)
    }

    iq_state := DORMANT
}
```

## Backend Busy

```scala
val backend_busy = (next_instr_ident =/= oldest_active_ident) || !oldest_active_valid
```

## Open Questions

1. **Lamlet distance for IdentQuery**: In Python, the lamlet computes its own distance from
   outstanding waiting items. In hardware, do we need this? The kamlets report their distances
   via sync network - does lamlet need to participate?

   Answer: Yes, the lamlet participates. It calls `synchronizer.local_event()` with its own
   distance value. This means IdentTracker needs access to: list of outstanding idents that
   have been dispatched but not completed.

2. **Multiple outstanding idents**: The lamlet tracks `waiting_items` with `instr_ident` and
   `dispatched` flag. We need some form of this for computing lamlet's distance.

   Options:
   a) Bitmap of outstanding idents (128 bits)
   b) Counter + FIFO of idents
   c) Simple: just use `(next_instr_ident - oldest_active_ident)` as distance

   Option (c) is conservative but may work for first draft.

