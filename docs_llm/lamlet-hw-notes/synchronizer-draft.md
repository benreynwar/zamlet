# Synchronizer (First Draft)

Handles lamlet-wide synchronization with optional MIN value aggregation. Used by kamlets and lamlet.

**Full implementation** - reusable module.

## Overview

The sync network is separate from the main packet network. Each Synchronizer connects to up to 8
neighbors (N, S, E, W, NE, NW, SE, SW) via 9-bit buses. It aggregates "sync complete" signals and
optionally computes the minimum value across all participants.

Used for:
- IdentQuery: Find oldest active ident across all kamlets (MIN aggregation)
- Future: Barrier synchronization, reduction operations

## Network Topology

```
Lamlet (0,-1)
    │ S
    ▼
Kamlet(0,0) ─── Kamlet(1,0) ─── ...
    │               │
Kamlet(0,1) ─── Kamlet(1,1) ─── ...
    │               │
   ...             ...
```

Each kamlet connects to all 8 neighbors that exist. The lamlet at (0,-1) only connects S to
kamlet (0,0).

## Bus Format

9 bits per cycle per direction:
- `[8]` = last_byte (1 = final byte of packet)
- `[7:0]` = data byte

## Packet Format

- Byte 0: sync_ident (8 bits)
- Byte 1: value (8 bits) - for MIN aggregation

First draft: Fixed 2-byte packets (always include value). Simplifies hardware.

## Interfaces

```
Synchronizer

// Configuration (directly wired, not registered)
├── PARAM: x              (kamlet x coordinate, 0 for lamlet)
├── PARAM: y              (kamlet y coordinate, -1 for lamlet)
├── PARAM: k_cols         (total kamlet columns)
├── PARAM: k_rows         (total kamlet rows)

// Local event input (from IdentTracker or cache_table)
├── IN:  local_event.valid      (this node has seen the event)
├── IN:  local_event.sync_ident (which sync operation)
├── IN:  local_event.value      (value for MIN aggregation, 8 bits)

// Sync result output (to IdentTracker)
├── OUT: result.valid           (sync completed for this ident)
├── OUT: result.sync_ident      (which sync operation completed)
├── OUT: result.value           (MIN value across all nodes)

// Network ports (direct wires to neighbors, no buffering)
├── OUT: port_n.valid, port_n.bits[8:0]
├── IN:  port_n_in.valid, port_n_in.bits[8:0]
├── ... (same for S, E, W, NE, NW, SE, SW)
```

Direct wire connections - no buffers, no ready signal. Neighbor samples on clock edge.

## State

Support multiple concurrent syncs using a table indexed by sync_ident. Since sync_ident is 8 bits
but we only need a few concurrent syncs, use a small CAM-like structure.

```scala
val MaxConcurrentSyncs = 4  // configurable

class SyncEntry extends Bundle {
    val valid = Bool()
    val sync_ident = UInt(8.W)
    val local_seen = Bool()
    val local_value = UInt(8.W)

    // Region sync status (true = synced)
    val quadrant_synced = Vec(4, Bool())  // NE, NW, SE, SW
    val column_synced = Vec(2, Bool())    // N, S
    val row_synced = Vec(2, Bool())       // E, W

    // MIN values from each region
    val quadrant_values = Vec(4, UInt(8.W))
    val column_values = Vec(2, UInt(8.W))
    val row_values = Vec(2, UInt(8.W))

    // Track which directions we've sent to
    val sent = Vec(8, Bool())  // N, S, E, W, NE, NW, SE, SW
}

val entries = RegInit(VecInit(Seq.fill(MaxConcurrentSyncs)(0.U.asTypeOf(new SyncEntry))))

// Packet reception state (per direction)
// Just need to hold byte 0 while waiting for byte 1
val rx_has_byte0 = RegInit(VecInit(Seq.fill(8)(false.B)))
val rx_byte0 = Reg(Vec(8, UInt(8.W)))

// Packet transmission state (per direction)
// Track which byte we're sending (0 = ident, 1 = value)
val tx_active = RegInit(VecInit(Seq.fill(8)(false.B)))
val tx_sync_idx = Reg(Vec(8, UInt(log2Ceil(MaxConcurrentSyncs).W)))  // which entry
val tx_byte_idx = Reg(Vec(8, UInt(1.W)))  // 0 = sync_ident, 1 = value
```

Lookup logic:
```scala
def find_entry(ident: UInt): (Bool, UInt) = {
    val found = entries.map(e => e.valid && e.sync_ident === ident)
    val idx = OHToUInt(found)
    (found.reduce(_ || _), idx)
}

def alloc_entry(ident: UInt): (Bool, UInt) = {
    val free = entries.map(!_.valid)
    val idx = PriorityEncoder(free)
    (free.reduce(_ || _), idx)
}
```

## Topology Initialization

On reset or start_sync, mark non-existent regions as already synced:

```scala
// Compute which neighbors exist (combinational, based on x, y, k_cols, k_rows)
val has_n = (y > 0) || (x === 0 && y === 0)  // kamlet (0,0) has lamlet at N
val has_s = (y < k_rows - 1)
val has_e = (x < k_cols - 1)
val has_w = (x > 0)
val has_ne = has_n && has_e  // except lamlet
val has_nw = has_n && has_w
val has_se = has_s && has_e
val has_sw = has_s && has_w

// For lamlet at (0, -1): only has_s is true
val is_lamlet = (y === -1.S)
when (is_lamlet) {
    has_n := false.B; has_e := false.B; has_w := false.B
    has_ne := false.B; has_nw := false.B; has_se := false.B; has_sw := false.B
}

// Initialize synced status for non-existent regions
when (start_sync) {
    quadrant_synced(NE) := !has_ne
    quadrant_synced(NW) := !has_nw
    quadrant_synced(SE) := !has_se
    quadrant_synced(SW) := !has_sw
    column_synced(N) := !has_n
    column_synced(S) := !has_s
    row_synced(E) := !has_e
    row_synced(W) := !has_w
}
```

## Send Conditions

From Python `SEND_REQUIREMENTS`:

```scala
// Cardinal directions: need opposite column/row synced
val can_send_n = local_seen && column_synced(S)
val can_send_s = local_seen && column_synced(N)
val can_send_e = local_seen && row_synced(W)
val can_send_w = local_seen && row_synced(E)

// Diagonal directions: need opposite quadrant + adjacent column + adjacent row
val can_send_ne = local_seen && quadrant_synced(SW) && column_synced(S) && row_synced(W)
val can_send_nw = local_seen && quadrant_synced(SE) && column_synced(S) && row_synced(E)
val can_send_se = local_seen && quadrant_synced(NW) && column_synced(N) && row_synced(W)
val can_send_sw = local_seen && quadrant_synced(NE) && column_synced(N) && row_synced(E)
```

Special case for kamlet (0,0) sending N to lamlet - must include SE quadrant + E row so lamlet
sees whole grid:
```scala
val can_send_n_origin = local_seen && column_synced(S) && quadrant_synced(SE) && row_synced(E)
```

## Value Computation for Send

When sending in a direction, include MIN of local + all required regions:

```scala
def min_for_direction(dir: Int): UInt = {
    val values = Wire(Vec(n, UInt(8.W)))
    var idx = 0
    values(idx) := local_value; idx += 1
    // Add required region values based on direction
    // ... (table lookup based on SEND_REQUIREMENTS)
    values.reduce(_ min _)
}
```

## Receive Logic

When a 2-byte packet is received from direction D:
```scala
when (rx_complete(D)) {
    val ident = rx_byte0(D)
    val value = rx_byte1(D)

    // Find or allocate entry for this ident
    val (found, found_idx) = find_entry(ident)
    val (can_alloc, alloc_idx) = alloc_entry(ident)
    val idx = Mux(found, found_idx, alloc_idx)

    when (!found && can_alloc) {
        // Initialize new entry
        entries(idx).valid := true.B
        entries(idx).sync_ident := ident
        entries(idx).local_seen := false.B
        // Initialize region synced based on topology (see Topology Initialization)
        init_topology(entries(idx))
    }

    when (found || can_alloc) {
        val e = entries(idx)
        // Update region status based on which direction packet came from
        switch (D) {
            is (N) { e.column_synced(N) := true.B; e.column_values(N) := value }
            is (S) { e.column_synced(S) := true.B; e.column_values(S) := value }
            is (E) { e.row_synced(E) := true.B; e.row_values(E) := value }
            is (W) { e.row_synced(W) := true.B; e.row_values(W) := value }
            is (NE) { e.quadrant_synced(NE) := true.B; e.quadrant_values(NE) := value }
            is (NW) { e.quadrant_synced(NW) := true.B; e.quadrant_values(NW) := value }
            is (SE) { e.quadrant_synced(SE) := true.B; e.quadrant_values(SE) := value }
            is (SW) { e.quadrant_synced(SW) := true.B; e.quadrant_values(SW) := value }
        }
    }
}
```

## Completion Condition

Per-entry completion check:
```scala
def is_complete(e: SyncEntry): Bool = {
    val all_regions_synced = e.quadrant_synced.asUInt.andR &&
                             e.column_synced.asUInt.andR &&
                             e.row_synced.asUInt.andR

    val all_sends_complete = (e.sent.asUInt | ~has_neighbor.asUInt) === 0xFF.U

    e.valid && e.local_seen && all_regions_synced && all_sends_complete
}

def get_min_value(e: SyncEntry): UInt = {
    val values = VecInit(Seq(
        e.local_value,
        e.quadrant_values(0), e.quadrant_values(1), e.quadrant_values(2), e.quadrant_values(3),
        e.column_values(0), e.column_values(1),
        e.row_values(0), e.row_values(1)
    ))
    values.reduce(_ min _)
}
```

## Result Output

Output completed syncs (priority encode if multiple complete same cycle):
```scala
val complete_mask = VecInit(entries.map(is_complete))
val any_complete = complete_mask.asUInt.orR
val complete_idx = PriorityEncoder(complete_mask)

io.result.valid := any_complete
io.result.sync_ident := entries(complete_idx).sync_ident
io.result.value := get_min_value(entries(complete_idx))

// Clear entry when result is consumed
when (io.result.valid && io.result.ready) {
    entries(complete_idx).valid := false.B
}
```

## Timing

- Receive: 2 cycles per packet (1 byte per cycle)
- Send: 2 cycles per packet (1 byte per cycle)
- Propagation: O(k_cols + k_rows) cycles for sync to propagate across grid

## Design Decisions

1. **Fixed packet size**: Always 2 bytes (ident + value)
2. **No flow control on ports**: Neighbors always ready (send/receive rates balanced)
3. **Limited concurrent syncs**: MaxConcurrentSyncs = 4
