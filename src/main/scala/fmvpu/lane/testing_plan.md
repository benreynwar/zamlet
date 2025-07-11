# NewLane Testing Plan

## Phase 1: Basic Test
- Reset module
- Wait 10 cycles
- Check nothing happens

## Phase 2: Program Execution Test
- Use command packets to write registers:
  - Write coordinate (0, 1) to register 3
  - Write value 4 to register 5
- Write program to instruction memory using command packet:
  - Instruction: `0100_0_011_101_000` (packet send: location=reg3, value=reg5, result=reg0)
- Send command packet to run the program
- Confirm that a packet header with destination (0, 1) and length field 4 is output from the lane