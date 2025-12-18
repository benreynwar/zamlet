# ScalarToKinstr

Bridges TileLink requests from the scalar core (for VPU memory addresses) into the
IssueUnit pipeline. Holds request state and receives responses from the mesh.

## Purpose

When the scalar core issues a load/store to an address in VPU memory space, it arrives
via TileLink. This module buffers the request, feeds it to the IssueUnit (which creates
the actual kinstr), and handles the response path back to the scalar core.

## Inputs

From TileLink (scalar core):
- `tl_a.valid` - Request valid
- `tl_a.opcode` - Get (load) / PutFull (store) / etc.
- `tl_a.address` - Physical address in VPU memory
- `tl_a.size` - Access size
- `tl_a.data` - Write data (for stores)
- `tl_a.source` - Transaction ID for response matching

From lamlet message handler (response from mesh):
- `resp.valid`
- `resp.ident` - Matching instruction ident
- `resp.data` - Load data (for loads)

## Outputs

To IssueUnit:
- `scalar_req.valid`
- `scalar_req.addr` - VPU address
- `scalar_req.size` - Access size
- `scalar_req.is_store`
- `scalar_req.data` - Write data (for stores)

From IssueUnit (back):
- `scalar_req.ready` - IssueUnit accepted request
- `scalar_req.ident` - Allocated ident for tracking response

To TileLink (scalar core):
- `tl_d.valid` - Response valid
- `tl_d.opcode` - AccessAck / AccessAckData
- `tl_d.data` - Read data (for loads)
- `tl_d.source` - Matching transaction ID

## Operation

1. Receive TileLink request, buffer it
2. Send request info to IssueUnit
3. IssueUnit allocates ident, generates kinstr, dispatches
4. Store mapping: ident → TileLink source (for response matching)
5. Response arrives from mesh with ident
6. Look up TileLink source, send TileLink response

## State

- Request buffer (address, size, is_store, data, tl_source)
- Ident-to-source mapping table (for matching responses)

## Flow Control

- If request buffer full, deassert tl_a.ready
- Multiple outstanding requests supported (up to table size)
