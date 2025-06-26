"""
The tests should run a matrix multiplication on a LaneGrid.
One of the matrices should be stored in the DDM. One column in each
lane.
The other matrix will be streamed one word at a time, into one of the
lanes.

1) Send the first matrix to the lanes using packets.
2) Send the first row to a lane using a packet.
3) Configure the network so those words move through the grid.
4) Do mult accum commands and network commands until we have a new
   row distributed across the lanes.  
"""
