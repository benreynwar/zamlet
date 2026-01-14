# ScalarLoadQueue

Handles vector loads from scalar memory. Receives requests from IssueUnit, issues TileLink
reads, and injects response data into the mesh.

## Purpose

When a vector load targets scalar memory (determined by physical address range), the data
must be fetched via TileLink rather than through the VPU memory system. This module:

1. Receives load requests from IssueUnit (one per scalar memory section)
2. Issues TileLink read requests to scalar memory
3. Tracks outstanding requests while waiting for responses
4. When response arrives, injects data into mesh (same path as VPU memory loads)

## Interfaces

```
ScalarLoadQueue
├── IN:  req (from IssueUnit)
│        ├── valid/ready
│        ├── paddr              # Physical address
│        ├── size               # Bytes to read (up to cache line)
│        ├── vd                 # Destination register
│        ├── start_index        # Starting element index
│        ├── n_elements         # Number of elements
│        ├── ew                 # Element width
│        └── instr_ident        # For completion tracking
│
├── OUT: tl_a.*                 # TileLink read request to ScalarMemPort
├── IN:  tl_d.*                 # TileLink read response from ScalarMemPort
│
├── OUT: kinstr                 # LoadImm kinstr(s) to DispatchQueue
├── OUT: kinstr_valid
├── IN:  kinstr_ready           # Backpressure from DispatchQueue
└── OUT: busy                   # Has outstanding requests
```

## Request Table

```
Entry[N]
├── valid
├── tl_source                   # TileLink transaction ID (= entry index)
├── paddr                       # For debugging
├── vd                          # Destination register
├── start_index                 # Starting element index
├── n_elements                  # Number of elements
├── ew                          # Element width
├── instr_ident                 # For completion tracking
└── rf_byte_offset              # Computed: where in RF to write
```

## Operation

### Request Phase

1. IssueUnit determines a section targets scalar memory
2. IssueUnit sends request to ScalarLoadQueue
3. If table has free entry:
   - Allocate entry, record context
   - Issue TileLink Get request, source = entry index
   - Signal ready to IssueUnit
4. If table full:
   - Deassert ready, IssueUnit stalls

### Response Phase

1. TileLink response arrives (AccessAckData)
2. Look up entry by tl_d.source
3. Generate LoadImm kinstr(s) with data embedded
4. Dispatch to mesh
5. Deallocate entry

### LoadImm Kinstrs

Unlike VPU memory loads (where jamlets read from SRAM cache slots), scalar memory loads
embed the data directly in the kinstr:

- **LoadImmByte**: 1 byte of data embedded
- **LoadImmWord**: 8 bytes of data embedded

For a cache-line-sized read, this may require multiple kinstrs (e.g., 8 LoadImmWord
kinstrs for 64 bytes).

Jamlets decode LoadImm kinstrs and write the embedded data directly to RF - no SRAM
access needed.

## Relationship to VpuToScalarMem

Both modules use the ScalarMemPort TileLink interface:

| Module | Direction | Use Case |
|--------|-----------|----------|
| ScalarLoadQueue | Lamlet reads scalar mem | Unit-stride loads to scalar memory |
| VpuToScalarMem | Kamlet reads scalar mem | Indexed ops hitting scalar addresses |

An arbiter grants access to ScalarMemPort. ScalarLoadQueue has priority (kamlets can
retry via DROP).

## Sizing

N entries determines maximum scalar memory reads in flight. Larger N hides TileLink
latency better but uses more area.

Suggested: N = 4-8 entries.
