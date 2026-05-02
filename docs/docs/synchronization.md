# Synchronization Network

Each kamlet contains a "Synchronizer" module which communicates with other kamlet synchronizers and with a
synchronizer on the lamlet.

This is kept separate from the main network mesh, since we want it to be fast, and it can
be kept to be 10 bits wide so it is relatively inexpensive.

## Interface

* Each synchronizer is triggered locally with a `sync_ident`, a `value` and a `mode`.

* A synchronization completes when a synchronizer knows that every synchronizer has been
  triggered for a given `sync_ident`.  The synchronization network also computes either the
  maximum or the minimum of all the values, where the operation is determined by `mode`.

* The local events are typically triggered, and the synchronization result waited for by
  a kinstruction located in the waiting item table.

* The `sync_ident` refers to a specific synchronziation slot, so that multiple synchronization
  operations can be in-flight at the same time (note that synchronization operations don't have
  to block, but some kinstructions will block on them).  The number of supported in-flight
  synchronizations will likely be 8.

## Use

* Synchronization is used by kinstructions that involve non-local data movement between
  kamlets. This is so that they can wait until all kamlets have completed the instruction
  before moving on.

* The minimum functionality is used to determine which element index faulted during
  indexed load and store operations.

* The maximum and minimum functionality of the synchronization network is used directly
  by some reduction operations.

* IdentQuery [see IdentQuery] make use of the synchronization network to determine
  available instruction buffer space, available kinstruction idents, and available sync idents.

## Implementation

* Each Synchronizer is connected to its 8 adjacent and diagonal neighbors.

* A synchronizer sends the following messages in each direction.
     1) North: All nodes directly south of you have triggered.
     2) South: All nodes directly north of you have triggered.
     3) East: All nodes directly west of you have triggered.
     4) West: All nodes directly east of you have triggered.
     5) North-East: All nodes in your south-west quadrant have triggered.
     6) North-West: All nodes in your south-east quadrant have triggered.
     7) South-East: All nodes in your north-west quadrant have triggered.
     8) South-West: All nodes in your north-east quadrant have triggered.

* A synchronizer when complete when messages from all 8 of its neighbors have arrived.

* An 8 neighbor design was chosen since diagonal movement is much faster, and since these are
  per kamlet, the area cost is less of a concern.

# Performance

* A synchronization packet is 2 or 3 flits.  5 cycles for each hop is realistic.
  For a 32x32 jamlet grid consisting of a 4x4 grid of kamlets, this would be a total latency
  of roughly 20 cycles.  Much faster than the mesh network.
