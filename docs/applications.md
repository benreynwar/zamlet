# Target Applications & Workloads

Zamlet targets **data-parallel workloads** that benefit from SIMT execution across a mesh of processing elements. The architecture is designed for applications with regular computation patterns and explicit communication requirements.

## Primary Application Domains

### Dense Linear Algebra
**Matrix-matrix multiplication, matrix-vector operations, linear solvers**

The VLIW SIMT architecture naturally maps to blocked matrix operations:
- Each Amlet processes matrix tiles
- Mesh network streams operand blocks between processing elements  
- SIMT execution handles regular computation patterns
- Multiple register files optimize for data/address separation

### Signal Processing  
**FFT, convolution, filtering operations**

Digital signal processing algorithms fit well due to:
- Regular computation patterns across data elements
- Butterfly operations map to VLIW instruction slots
- Twiddle factors stored in shared instruction memory
- Network enables efficient data shuffling between stages

### Scientific Computing
**Stencil computations, finite difference methods, particle simulations**

Scientific workloads benefit from:
- Spatial locality matches mesh topology
- Explicit memory management avoids cache unpredictability
- Predicated execution handles boundary conditions
- Out-of-order execution hides communication latency

## Detailed Example: Matrix Multiplication

Consider 32×32 matrix multiplication distributed across a 4×4 Amlet mesh:

### Data Layout
```
Matrix A: Distributed row-wise across Amlets
Matrix B: Streamed column-wise through mesh
Matrix C: Accumulated locally, collected via network
```

### Computation Flow
```scala
// Pseudocode for each Amlet
for col in B_columns:
  // 1. Receive column data, forward to next Amlet
  packet: ReceiveAndForward(length=32, dest=next_amlet)
  
  // 2. Process column against local rows  
  control: LoopImmediate(body_len=4, iterations=32)
    loadstore: Load(d_a_element, a_row_base, loop_index)
    packet: GetWord(d_b_element)  
    alu: MUL(d_product, d_a_element, d_b_element)
    alu: ADD(d_accumulator, d_accumulator, d_product)
    
  // 3. Send partial results
  packet: Send(length=1, dest=collector_amlet)
    // Write d_accumulator to network
```

### Performance Characteristics
- **Computation/Communication Overlap**: Network transfers hidden by local computation
- **Scalable**: Linear performance scaling with mesh size (until network saturated)
- **Memory Efficient**: No temporary storage beyond register files

## Detailed Example: FFT Implementation

Radix-2 FFT across multiple Amlets with inter-stage communication:

### Local FFT Stage
```scala
// Each Amlet performs local butterflies
control: LoopImmediate(body_len=6, iterations=log2(local_size))
  // Load butterfly operands
  loadstore: Load(d_a, a_base, a_index1)
  loadstore: Load(d_b, a_base, a_index2) 
  loadstore: Load(d_twiddle, a_twiddle_base, twiddle_index)
  
  // Butterfly computation  
  alu: MUL(d_temp, d_b, d_twiddle)
  alu: ADD(d_sum, d_a, d_temp)
  alu: SUB(d_diff, d_a, d_temp)
  
  // Store results
  loadstore: Store(a_base, a_index1, d_sum)
  loadstore: Store(a_base, a_index2, d_diff)
```

### Inter-Amlet Data Exchange
```scala
// Exchange data between processing elements
packet: Send(length=local_size/2, dest=partner_amlet)
packet: Receive(length=local_size/2)

// Merge received data with local data
control: LoopImmediate(body_len=2, iterations=local_size/2)
  packet: GetWord(d_remote_data)
  loadstore: Store(a_local_base, offset, d_remote_data)
```

## Architecture Advantages for Target Workloads

### VLIW Benefits
- **Explicit Parallelism**: Compiler exposes instruction-level parallelism
- **Predictable Performance**: No dynamic scheduling overhead
- **Efficient Control**: Single control unit manages entire mesh

### SIMT Benefits  
- **Control Efficiency**: Single instruction stream across data elements
- **Divergence Handling**: Predicates manage conditional execution
- **Synchronization**: Natural barrier points at instruction boundaries

### Mesh Network Benefits
- **Spatial Locality**: Communication patterns match algorithm structure
- **Scalability**: Network bandwidth scales with processing elements
- **Low Latency**: Minimal buffering reduces communication overhead

## Performance Expectations

### Strong Suits
- **Regular, predictable workloads**: VLIW + SIMT excel at structured computation
- **Communication-intensive algorithms**: Mesh network provides dedicated bandwidth  
- **Memory-bound workloads**: Out-of-order execution hides memory latency
- **Real-time applications**: Predictable timing due to explicit management

### Limitations
- **Irregular workloads**: Poor SIMT utilization with divergent control flow
- **Cache-friendly algorithms**: No cache hierarchy to exploit temporal locality
- **Sequential algorithms**: Limited parallelism extraction
- **Dynamic workloads**: Fixed VLIW structure less adaptable than superscalar

## Current Implementation Status

### Completed Applications
- **Basic ALU operations**: Arithmetic verified across mesh
- **Simple memory patterns**: Load/store functionality working
- **Network communication**: Packet routing and forwarding operational

### In Development
- **Matrix multiplication kernel**: Currently being written and debugged
- **FFT implementation**: Algorithm design in progress
- **Performance benchmarking**: Measurement infrastructure being developed

### Planned Applications  
- **Convolution**: 2D convolution for image processing
- **Stencil operations**: 2D/3D finite difference computations
- **Graph algorithms**: Breadth-first search, shortest path

## Competitive Position

**Compared to GPUs:**
- ✅ More predictable performance
- ✅ Lower power for regular workloads  
- ❌ Lower peak throughput
- ❌ Less mature software ecosystem

**Compared to CPUs:**
- ✅ Higher parallel efficiency
- ✅ Dedicated communication network
- ❌ Less flexibility for irregular workloads
- ❌ Requires specialized programming

**Compared to FPGAs:**
- ✅ Higher-level programming model
- ✅ Faster compilation/debug cycles
- ❌ Less customizable datapath
- ❌ Higher area overhead per operation

The Zamlet architecture fills a niche for **predictable, parallel computation** in domains where GPU variability is problematic but FPGA complexity is excessive.