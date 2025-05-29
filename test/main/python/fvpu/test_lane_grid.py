import os
import json
import math
from random import Random
import collections

import cocotb
from cocotb import triggers, clock

from fvpu import generate_rtl, test_utils
from fvpu.params import FVPUParams

this_dir = os.path.abspath(os.path.dirname(__file__))


async def process_to_lane_grid(dut, togrid_queue, params):
    while True:
        if togrid_queue:
            words = togrid_queue.popleft()  # List of nColumns * nRows words
            # Send data for nColumns cycles, starting from final column backwards
            for cycle in range(params.n_columns):
                col = params.n_columns - 1 - cycle  # Start from final column, work backwards
                for row in range(params.n_rows):
                    lane_idx = row * params.n_columns + col
                    getattr(dut, f'wI_{row}_0_valid').value = 1
                    getattr(dut, f'wI_{row}_0_bits_bits').value = words[lane_idx]
                    getattr(dut, f'wI_{row}_0_bits_header').value = 0
                await triggers.RisingEdge(dut.clock)
        else:
            for row in range(params.n_rows):
                getattr(dut, f'wI_{row}_0_valid').value = 0
            await triggers.RisingEdge(dut.clock)


async def process_from_lane_grid(dut, fromlane_queue, params):
    await triggers.RisingEdge(dut.clock)
    await triggers.ReadOnly()
    while True:
        if getattr(dut, 'eO_0_1_valid').value:
            words = [None] * (params.n_rows * params.n_columns)
            for cycle in range(params.n_columns):
                col = params.n_columns - 1 - cycle
                for row in range(params.n_rows):
                    lane_idx = row * params.n_columns + col
                    assert getattr(dut, f'eO_{row}_1_valid').value == 1
                    words[lane_idx] = int(getattr(dut, f'eO_{row}_1_bits_bits').value)
                await triggers.RisingEdge(dut.clock)
                # Send token back to acknowledge receipt (after rising edge, not in read-only mode)
                for row in range(params.n_rows):
                    getattr(dut, f'eO_{row}_1_token').value = 1
                await triggers.ReadOnly()
            assert None not in words
            fromlane_queue.append(words)
        else:
            await triggers.RisingEdge(dut.clock)
            # No tokens when no valid data (after rising edge, not in read-only mode)
            for row in range(params.n_rows):
                getattr(dut, f'eO_{row}_1_token').value = 0
            await triggers.ReadOnly()


def submit_send(dut, length, address, params):
    # Submit to all columns with appropriate offset/stride
    for col in range(params.n_columns):
        start_offset = 0
        stride = params.n_columns
        getattr(dut, f'instr_{col}_sendreceive_valid').value = 1
        getattr(dut, f'instr_{col}_sendreceive_bits_mode').value = 0
        getattr(dut, f'instr_{col}_sendreceive_bits_length').value = length
        getattr(dut, f'instr_{col}_sendreceive_bits_addr').value = address
        getattr(dut, f'instr_{col}_sendreceive_bits_startOffset').value = start_offset
        getattr(dut, f'instr_{col}_sendreceive_bits_stride').value = stride


def submit_receive(dut, length, address, params):
    # Submit to all columns with appropriate offset/stride
    for col in range(params.n_columns):
        start_offset = params.n_columns - 1 - col  # Column 0 gets last word, column 1 gets second-to-last, etc.
        stride = params.n_columns
        getattr(dut, f'instr_{col}_sendreceive_valid').value = 1
        getattr(dut, f'instr_{col}_sendreceive_bits_mode').value = 1
        getattr(dut, f'instr_{col}_sendreceive_bits_length').value = length
        getattr(dut, f'instr_{col}_sendreceive_bits_addr').value = address
        getattr(dut, f'instr_{col}_sendreceive_bits_startOffset').value = start_offset
        getattr(dut, f'instr_{col}_sendreceive_bits_stride').value = stride


def clear_sendreceive(dut, params):
    # Clear all columns
    for col in range(params.n_columns):
        getattr(dut, f'instr_{col}_sendreceive_valid').value = 0


def submit_load(dut, reg, addr, params):
    """Load from register to memory address"""
    for col in range(params.n_columns):
        getattr(dut, f'instr_{col}_loadstore_valid').value = 1
        getattr(dut, f'instr_{col}_loadstore_bits_mode').value = 0  # Load mode: register -> memory
        getattr(dut, f'instr_{col}_loadstore_bits_reg').value = reg
        getattr(dut, f'instr_{col}_loadstore_bits_addr').value = addr


def submit_store(dut, reg, addr, params):
    """Store from memory address to register"""
    for col in range(params.n_columns):
        getattr(dut, f'instr_{col}_loadstore_valid').value = 1
        getattr(dut, f'instr_{col}_loadstore_bits_mode').value = 1  # Store mode: memory -> register
        getattr(dut, f'instr_{col}_loadstore_bits_reg').value = reg
        getattr(dut, f'instr_{col}_loadstore_bits_addr').value = addr


def clear_loadstore(dut, params):
    for col in range(params.n_columns):
        getattr(dut, f'instr_{col}_loadstore_valid').value = 0


async def send_and_receive(dut, rnd, params):
    """
    Send in vectors using the Receive instruction.
    Send out vectors using the Send instruction.
    Check that they match.
    """
    n_lanes = params.n_columns * params.n_rows
    test_data = [0x1000 + i for i in range(n_lanes * 2)]  # Two vectors worth of data
    
    togrid_queue = collections.deque()
    fromgrid_queue = collections.deque()
    
    # Start communication tasks
    togrid_task = cocotb.start_soon(process_to_lane_grid(dut, togrid_queue, params))
    fromgrid_task = cocotb.start_soon(process_from_lane_grid(dut, fromgrid_queue, params))
    
    # Set up receive instruction for 2 vectors
    submit_receive(dut, 2, 0, params)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut, params)
    await triggers.RisingEdge(dut.clock)
    
    # Send two vectors
    first_vector = test_data[:n_lanes]
    second_vector = test_data[n_lanes:]
    togrid_queue.append(first_vector)
    togrid_queue.append(second_vector)
    
    while togrid_queue:
        await triggers.RisingEdge(dut.clock)
    
    # Set up send instruction for 2 vectors
    submit_send(dut, 2, 0, params)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut, params)
    
    # Wait for all data to come back (2 words per row)
    while len(fromgrid_queue) < 2:
        await triggers.RisingEdge(dut.clock)
    
    # Collect received data and verify
    received_data = []
    while fromgrid_queue:
        received_data += fromgrid_queue.popleft()
    
    assert test_data == received_data
    
    # Clean up tasks
    togrid_task.kill()
    fromgrid_task.kill()


async def send_and_receive_swap_order(dut, rnd, params):
    """
    Send in vectors using the Receive instruction.
    Load the vectors into registers.
    Store them back to the data memory but in the opposite order.
    Send out vectors using the Send instruction.
    """
    n_lanes = params.n_columns * params.n_rows
    test_data = [0x2000 + i for i in range(n_lanes * 2)]  # Two vectors worth of data
    expected_data = test_data[n_lanes:] + test_data[:n_lanes]  # Swapped order
    
    togrid_queue = collections.deque()
    fromgrid_queue = collections.deque()
    
    # Start communication tasks
    togrid_task = cocotb.start_soon(process_to_lane_grid(dut, togrid_queue, params))
    fromgrid_task = cocotb.start_soon(process_from_lane_grid(dut, fromgrid_queue, params))
    
    # Step 1: Receive two vectors into memory (addresses 0 and 1)
    submit_receive(dut, 2, 0, params)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut, params)
    await triggers.RisingEdge(dut.clock)
    
    first_vector = test_data[:n_lanes]
    second_vector = test_data[n_lanes:]
    togrid_queue.append(first_vector)
    togrid_queue.append(second_vector)
    
    while togrid_queue:
        await triggers.RisingEdge(dut.clock)
    await triggers.RisingEdge(dut.clock)
    
    # Step 2: Store vector from memory address 0 into register 0
    submit_store(dut, 0, 0, params)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut, params)
    await triggers.RisingEdge(dut.clock)
    
    # Step 3: Store vector from memory address 1 into register 1
    submit_store(dut, 1, 1, params)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut, params)
    await triggers.RisingEdge(dut.clock)
    
    # Step 4: Load register 0 to memory address 1 (swap)
    submit_load(dut, 0, 1, params)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut, params)
    await triggers.RisingEdge(dut.clock)
    
    # Step 5: Load register 1 to memory address 0 (swap)
    submit_load(dut, 1, 0, params)
    await triggers.RisingEdge(dut.clock)
    clear_loadstore(dut, params)
    await triggers.RisingEdge(dut.clock)
    
    # Step 6: Send the swapped data out
    submit_send(dut, 2, 0, params)
    await triggers.RisingEdge(dut.clock)
    clear_sendreceive(dut, params)
    
    # Wait for all data to come back (2 words per row)
    while len(fromgrid_queue) < 2:
        await triggers.RisingEdge(dut.clock)
    
    # Collect received data and verify
    received_data = []
    while fromgrid_queue:
        received_data += fromgrid_queue.popleft()
    
    assert expected_data == received_data
    
    # Clean up tasks
    togrid_task.kill()
    fromgrid_task.kill()


def make_packet_header(params, x, y, address, length):
    x_bits = test_utils.clog2(params.n_columns)
    y_bits = test_utils.clog2(params.n_rows)
    addr_bits = test_utils.clog2(params.ddm_addr_width)
    length_bits = test_utils.clog2(params.max_packet_length)

    # Pack header with MSB to LSB order: dest.x | dest.y | address | length
    header = 0
    header |= (length & ((1 << length_bits) - 1))
    header |= ((address & ((1 << addr_bits) - 1)) << length_bits)
    header |= ((y & ((1 << y_bits) - 1)) << (length_bits + addr_bits))
    header |= ((x & ((1 << x_bits) - 1)) << (length_bits + addr_bits + y_bits))

    return header


class PacketSender:

    def __init__(self, dut, edge, position, bus_index, packet_queue):
        self.dut = dut
        self.valid_s = getattr(dut, f'{edge}I_{position}_{bus_index}_valid')
        self.token_s = getattr(dut, f'{edge}I_{position}_{bus_index}_token')
        self.header_s = getattr(dut, f'{edge}I_{position}_{bus_index}_bits_header')
        self.data_s = getattr(dut, f'{edge}I_{position}_{bus_index}_bits_bits')
        self.queue = packet_queue
        self.n_tokens = 0
        cocotb.start_soon(self.receive_tokens())
        cocotb.start_soon(self.send_packets())

    async def receive_tokens(self):
        while True:
            await triggers.RisingEdge(self.dut.clock)
            await triggers.ReadOnly()
            if self.token_s.value == 1:
                self.n_tokens += 1

    async def send_packets(self):
        header = None
        body = []
        while True:
            await triggers.RisingEdge(self.dut.clock)
            self.valid_s.value = 0
            if (not body) and self.queue:
                packet = self.queue.popleft()
                header = packet[0]
                body = packet[1:]
            if self.n_tokens > 0:
                if header is not None:
                    self.dut._log.info(f'Sending header on {self.valid_s}')
                    self.valid_s.value = 1
                    self.header_s.value = 1
                    self.data_s.value = header
                    header = None
                    self.n_tokens -= 1
                elif body:
                    self.valid_s.value = 1
                    self.header_s.value = 0
                    self.data_s.value = body.pop(0)
                    self.n_tokens -= 1


async def send_packet_and_receive(dut, rnd, params):
    '''
    Send data to the lanes with packets.
    Use a 'send' instruction to get it back.
    '''
    # Make the data to send
    n_words_per_lane = 13
    base_address = 8
    n_lanes = params.n_rows * params.n_columns

    data = [i for i in range(n_lanes*n_words_per_lane)]

    packets = []
    for x in range(params.n_columns):
        for y in range(params.n_rows):
            lane_index = y*params.n_columns + x
            header = make_packet_header(params, x, y, base_address, n_words_per_lane)
            body = []
            for offset in range(n_words_per_lane):
                data_index = offset*n_lanes + lane_index
                body.append(data[data_index])
            packet = [header] + body
            packets.append(packet)

    packet_queue = collections.deque()

    for col in range(params.n_columns):
        getattr(dut, f'config_{col}_configValid').value = 1
        getattr(dut, f'config_{col}_configIsPacketMode').value = 1
        getattr(dut, f'config_{col}_configDelay').value = 0
    await triggers.RisingEdge(dut.clock)
    for col in range(params.n_columns):
        getattr(dut, f'config_{col}_configValid').value = 0
    for i in range(4):
        await triggers.RisingEdge(dut.clock)

    packet_sender = PacketSender(dut=dut, edge='n', position=1, bus_index=2, packet_queue=packet_queue)
    header = make_packet_header(params, 0, 0, 6, 3)
    dut._log.info(f'header is {bin(header)}')
    packet = [header, 0, 1, 2]
    packet_queue.append(packet)
    for i in range(100):
        await triggers.RisingEdge(dut.clock)


async def timeout(dut, max_cycles):
    count = 0
    while True:
        await triggers.RisingEdge(dut.clock)
        assert count < max_cycles, f"Test timed out after {max_cycles} cycles"
        count += 1


@cocotb.test()
async def lane_grid_test(dut):
    test_params = test_utils.read_params()
    rnd = Random(test_params['seed'])
    params_dict = test_params['params']
    params = FVPUParams.from_dict(params_dict)
    
    # Initialize all instruction interfaces to inactive
    for col in range(params.n_columns):
        getattr(dut, f'instr_{col}_compute_valid').value = 0
        getattr(dut, f'instr_{col}_loadstore_valid').value = 0
        getattr(dut, f'instr_{col}_network_valid').value = 0
        getattr(dut, f'instr_{col}_sendreceive_valid').value = 0
    
    # Initialize all network interfaces to inactive
    for row in range(params.n_rows):
        for bus in range(params.n_buses):
            getattr(dut, f'wI_{row}_{bus}_valid').value = 0
            getattr(dut, f'eI_{row}_{bus}_valid').value = 0
            # Token inputs for outputs (these go into the LaneGrid)
            getattr(dut, f'eO_{row}_{bus}_token').value = 0
            getattr(dut, f'wO_{row}_{bus}_token').value = 0
    
    for col in range(params.n_columns):
        for bus in range(params.n_buses):
            getattr(dut, f'nI_{col}_{bus}_valid').value = 0
            getattr(dut, f'sI_{col}_{bus}_valid').value = 0
            # Token inputs for outputs (these go into the LaneGrid)
            getattr(dut, f'nO_{col}_{bus}_token').value = 0
            getattr(dut, f'sO_{col}_{bus}_token').value = 0

    # Initialize all config interfaces to inactive
    for col in range(params.n_columns):
        getattr(dut, f'config_{col}_configValid').value = 0
        getattr(dut, f'config_{col}_configIsPacketMode').value = 0
        getattr(dut, f'config_{col}_configDelay').value = 0

    cocotb.start_soon(clock.Clock(dut.clock, 1, 'ns').start())
    cocotb.start_soon(timeout(dut, 200))
    
    # Reset sequence
    dut.reset.value = 0
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 1
    await triggers.RisingEdge(dut.clock)
    dut.reset.value = 0

    for col in range(params.n_columns):
        getattr(dut, f'config_{col}_configValid').value = 1
        getattr(dut, f'config_{col}_configIsPacketMode').value = 0
        getattr(dut, f'config_{col}_configDelay').value = 0
    await triggers.RisingEdge(dut.clock)
    for col in range(params.n_columns):
        getattr(dut, f'config_{col}_configValid').value = 0
    
    # Run tests
    await send_and_receive(dut, rnd, params)
    await send_and_receive_swap_order(dut, rnd, params)
    await send_packet_and_receive(dut, rnd, params)


def test_proc():
    working_dir = os.path.abspath('deleteme')
    params_filename = os.path.join(this_dir, 'params.json')
    filenames = generate_rtl.generate('LaneGrid', working_dir, [params_filename])
    toplevel = 'LaneGrid'
    module = 'test_lane_grid'
    with open(params_filename, 'r', encoding='utf-8') as params_f:
        design_params = json.loads(params_f.read())
    test_params = {
        'seed': 0,
        'params': design_params,
        }
    test_utils.run_test(working_dir, filenames, test_params, toplevel, module)


if __name__ == '__main__':
    test_proc()
