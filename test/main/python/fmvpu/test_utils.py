import os
import json
import collections
import logging
from typing import Any, Dict, List, Deque, Optional

import cocotb
from cocotb import triggers
from cocotb.handle import HierarchyObject
from cocotb_tools.runner import get_runner
import cocotb.logging


logger = logging.getLogger(__name__)


def configure_logging_pre_sim(level: str = 'INFO') -> None:
    """Configure logging for tests before simulation starts."""
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {level}')
    logging.basicConfig(
        level=numeric_level,
        format='%(levelname)-8s %(name)-34s %(message)s',
        force=True
    )


def configure_logging_sim(level: str = 'INFO') -> None:
    """Configure logging for tests during simulation using cocotb's format."""
    cocotb.logging.default_config()
    
    # Set the desired log level
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {level}')
    logging.getLogger().setLevel(numeric_level)


def write_params(working_dir: str, params: Dict[str, Any]) -> None:
    """Write test parameters to JSON file and set environment variable."""
    params_filename = os.path.join(working_dir, 'test_params.json')
    os.environ['FMPVU_TEST_PARAMS_FILENAME'] = params_filename
    with open(params_filename, 'w', encoding='utf-8') as params_file:
        params_file.write(json.dumps(params))


def read_params() -> Dict[str, Any]:
    """Read test parameters from JSON file specified in environment variable."""
    params_filename = os.environ['FMPVU_TEST_PARAMS_FILENAME']
    with open(params_filename, 'r', encoding='utf-8') as params_file:
        params = json.loads(params_file.read())
    return params


def run_test(working_dir: str, filenames: List[str], params: Dict[str, Any], toplevel: str, module: str) -> None:
    """Run cocotb test with Verilator simulator."""
    sim = 'verilator'
    runner = get_runner(sim)
    write_params(working_dir, params)
    runner.build(
        sources=filenames,
        hdl_toplevel=toplevel,
        always=True,
        waves=True,
        build_args=['--trace', '--trace-structs'],
        )
    runner.test(hdl_toplevel=toplevel, test_module=module, waves=True)


def clog2(value: int) -> int:
    """Calculate ceiling log2 - how many bits are required to represent 'value-1'."""
    value = value - 1
    bits = 0
    while value > 0:
        value = value >> 1
        bits += 1
    return bits


def make_seed(rnd: Any) -> int:
    """Generate a 32-bit random seed."""
    return rnd.getrandbits(32)




class PacketSender:
    """Handles packet sending with proper token-based backpressure."""
    
    def __init__(self, dut: HierarchyObject, edge: str, position: Optional[int], bus_index: int, packet_queue: Deque):
        """
        Initialize packet sender.
        
        Args:
            dut: Device under test
            edge: Direction ('n', 's', 'e', 'w')
            position: Position index for the edge (None for Lane, int for LaneGrid)
            bus_index: Channel/bus index
            packet_queue: Queue of packets to send, where each packet is [header, data1, data2, ...]
        """
        self.dut = dut
        self.queue = packet_queue
        self.n_tokens = 0
        
        # Get signal references based on the interface naming pattern
        if position is None:
            # Lane naming convention: io_{edge}I_{bus_index}_*
            self.valid_s = getattr(dut, f'io_{edge}I_{bus_index}_valid')
            self.token_s = getattr(dut, f'io_{edge}I_{bus_index}_token')
            self.header_s = getattr(dut, f'io_{edge}I_{bus_index}_bits_header')
            self.data_s = getattr(dut, f'io_{edge}I_{bus_index}_bits_bits')
        else:
            # LaneGrid naming convention: io_{edge}I_{position}_{bus_index}_*
            self.valid_s = getattr(dut, f'io_{edge}I_{position}_{bus_index}_valid')
            self.token_s = getattr(dut, f'io_{edge}I_{position}_{bus_index}_token')
            self.header_s = getattr(dut, f'io_{edge}I_{position}_{bus_index}_bits_header')
            self.data_s = getattr(dut, f'io_{edge}I_{position}_{bus_index}_bits_bits')
        
        # Start the coroutines
        self.token_task = cocotb.start_soon(self.receive_tokens())
        self.send_task = cocotb.start_soon(self.send_packets())

    async def receive_tokens(self):
        """Track incoming tokens for backpressure control."""
        while True:
            await triggers.RisingEdge(self.dut.clock)
            await triggers.ReadOnly()
            if self.token_s.value == 1:
                self.n_tokens += 1

    async def send_packets(self):
        """Send packets from queue when tokens are available."""
        header = None
        body = []
        while True:
            await triggers.RisingEdge(self.dut.clock)
            self.valid_s.value = 0
            
            # Get next packet if we don't have one in progress
            if (not body) and self.queue:
                packet = self.queue.popleft()
                header = packet[0]
                body = packet[1:]
            
            # Send data if we have tokens available
            if self.n_tokens > 0:
                if header is not None:
                    self.valid_s.value = 1
                    self.header_s.value = 1
                    logger.info(f'Sending header {header} on {self.data_s}')
                    self.data_s.value = header
                    header = None
                    self.n_tokens -= 1
                elif body:
                    self.valid_s.value = 1
                    self.header_s.value = 0
                    word = body.pop(0)
                    logger.info(f'Sending body {word}')
                    self.data_s.value = word
                    self.n_tokens -= 1

    def kill(self):
        """Terminate the packet sender tasks."""
        self.token_task.kill()
        self.send_task.kill()


class PacketReceiver:
    """Handles packet receiving with proper token-based backpressure."""
    
    def __init__(self, dut: HierarchyObject, edge: str, position: Optional[int], bus_index: int, packet_queue: Deque, params: Any, max_tokens: int = 8):
        """
        Initialize packet receiver.
        
        Args:
            dut: Device under test
            edge: Direction ('n', 's', 'e', 'w')
            position: Position index for the edge (None for Lane, int for LaneGrid)
            bus_index: Channel/bus index
            packet_queue: Queue to store received packets, where each packet is [header, data1, data2, ...]
            params: FMVPU parameters for header decoding
            max_tokens: Maximum number of tokens to issue for backpressure control
        """
        self.dut = dut
        self.queue = packet_queue
        self.params = params
        self.max_tokens = max_tokens
        self.available_tokens = max_tokens
        self.current_packet = []
        self.packet_length = 0
        self.words_received = 0
        self.expecting_header = True
        
        # Get signal references based on the interface naming pattern
        if position is None:
            # Lane naming convention: io_{edge}O_{bus_index}_*
            self.valid_s = getattr(dut, f'io_{edge}O_{bus_index}_valid')
            self.token_s = getattr(dut, f'io_{edge}O_{bus_index}_token')
            self.header_s = getattr(dut, f'io_{edge}O_{bus_index}_bits_header')
            self.data_s = getattr(dut, f'io_{edge}O_{bus_index}_bits_bits')
        else:
            # LaneGrid naming convention: io_{edge}O_{position}_{bus_index}_*
            self.valid_s = getattr(dut, f'io_{edge}O_{position}_{bus_index}_valid')
            self.token_s = getattr(dut, f'io_{edge}O_{position}_{bus_index}_token')
            self.header_s = getattr(dut, f'io_{edge}O_{position}_{bus_index}_bits_header')
            self.data_s = getattr(dut, f'io_{edge}O_{position}_{bus_index}_bits_bits')
        
        # Start the receiver coroutine
        self.receive_task = cocotb.start_soon(self.receive_packets())

    async def receive_packets(self):
        """Receive packets with proper token management and error checking."""
        while True:
            await triggers.RisingEdge(self.dut.clock)
            
            # Send token if we have available tokens
            if self.available_tokens > 0:
                self.token_s.value = 1
                self.available_tokens -= 1  # Decrement when we send token
            else:
                self.token_s.value = 0
            
            # Check if we have valid data
            if self.valid_s.value == 1:
                data_value = int(self.data_s.value)
                is_header = bool(self.header_s.value)
                
                # Increment available tokens when we receive data
                self.available_tokens += 1
                
                if is_header:
                    if not self.expecting_header:
                        raise RuntimeError("Received unexpected packet header - expected data")
                    
                    # Start of new packet - decode header to get length
                    from control_structures import PacketHeader
                    packet_header = PacketHeader.from_word(self.params, data_value)
                    logger.info(f'Header is {packet_header}')
                    self.current_packet = [data_value]
                    self.packet_length = packet_header.length
                    self.words_received = 0
                    self.expecting_header = False
                    
                    # If packet has zero length, complete immediately
                    if self.packet_length == 0:
                        self.queue.append(self.current_packet)
                        self.current_packet = []
                        self.expecting_header = True
                        
                else:
                    # Data word
                    if self.expecting_header:
                        raise RuntimeError("Received unexpected data - expected packet header")
                    
                    if not self.current_packet:
                        raise RuntimeError("Received data without active packet")
                    
                    self.current_packet.append(data_value)
                    self.words_received += 1
                    
                    # Check if packet is complete
                    if self.words_received >= self.packet_length:
                        self.queue.append(self.current_packet)
                        self.current_packet = []
                        self.words_received = 0
                        self.expecting_header = True

    def kill(self):
        """Terminate the packet receiver task."""
        self.receive_task.kill()
