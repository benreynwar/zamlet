# Quick Start Guide

## Prerequisites

- Docker and Docker Compose
- Git

## Setup

### 1. Clone and Start Container

```bash
git clone https://github.com/benreynwar/zamlet.git
cd zamlet

# Start the development container
# Note: You may need to edit docker-compose.yml for your system
docker-compose up -d

# Enter the container
docker-compose exec zamlet bash
```

### 2. Verify Installation

Inside the container, check that tools are available:

```bash
# Check Bazel
bazel version

# Check Verilator 
verilator --version

# Check Python environment (venv is auto-activated)
python --version
```

## Run Your First Example

### Generate Verilog RTL

```bash
# Generate the default Bamlet processor RTL
bazel build //dse/bamlet:Bamlet_default_verilog

# View the generated Verilog (optional)
ls bazel-bin/dse/bamlet/Bamlet_default.sv
```

### Run Basic Tests

```bash
# Run all Bamlet tests - this shows the processor executing instructions
bazel test //python/zamlet/bamlet_test:all --test_output=streamed
```

You should see debug output showing:
- Test setup and initialization
- Instructions being executed
- Register file updates
- Network packet transfers
- Test results

### Run a Specific Meaningful Test

```bash
# Run the ALU basic test to see arithmetic operations
bazel test //python/zamlet/amlet_test:test_alu_basic_default --test_output=streamed
```

This test is located at [`python/zamlet/amlet_test/test_alu_basic.py`](../python/zamlet/amlet_test/test_alu_basic.py).

This test demonstrates:
- Loading instructions into the processor
- Executing ALU operations (add, subtract, etc.)
- Reading results from register files
- Verifying correct computation

## Performance Analysis

### Get Post-Synthesis Results

```bash
# Synthesize and get the post-synthesis area and timing reports
bazel build //dse/bamlet:Bamlet_default__sky130hd_results

# View the results
cat bazel-bin/dse/bamlet/Bamlet_default__sky130hd_stats
```

### Get Post-Route Results

```bash
# Full place-and-route timing results (takes longer)
bazel build //dse/bamlet:Bamlet_default__sky130hd_timing_route

# View the routed timing summary
cat bazel-bin/dse/bamlet/Bamlet_default__sky130hd_timing_route_summary
```

## What to Try Next

### Modify Configuration

Edit the processor configuration:
```bash
vim configs/bamlet_default.json
```

Try changing:
- Grid size (more Amlets)
- Register file sizes
- Reservation station depths

Then regenerate and test:
```bash
bazel build //dse/bamlet:Bamlet_default_verilog
bazel test //python/zamlet/bamlet_test:all --test_output=streamed
```

### Explore the Code

Key files to examine:
- `src/main/scala/zamlet/bamlet/` - Bamlet processor RTL
- `src/main/scala/zamlet/amlet/` - Amlet processing element RTL  
- `python/zamlet/bamlet_test/` - Test cases
- `python/zamlet/bamlet_kernels/` - Example applications

### Run More Complex Tests

```bash
# Test network communication
bazel test //python/zamlet/bamlet_test:test_packet_default --test_output=streamed

# Test predicated execution  
bazel test //python/zamlet/bamlet_test:test_predicate_default --test_output=streamed
```

## Next Steps

- Read the [Architecture Guide](architecture.md) to understand the design
- Check out [Applications](applications.md) for target workloads
- Explore the [Instruction Set](instruction-set.md) reference
