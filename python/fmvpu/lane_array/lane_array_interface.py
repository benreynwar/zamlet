import logging
from typing import Dict, List

import cocotb
from cocotb import triggers

from fmvpu.lane import packet_utils
from fmvpu.lane.lane_interface import create_register_write_packet, create_instruction_write_packet, create_start_packet, create_data_packet, make_seed
from fmvpu.lane_array.lane_array_params import LaneArrayParams


logger = logging.getLogger(__name__)


class LaneArrayInterface:
    """Interface for controlling and interacting with a LaneArray module"""

    def __init__(self, dut, params: LaneArrayParams, rnd):
        self.dut = dut
        self.params = params
        self.rnd = rnd
        
        # Create packet drivers for all edge interfaces
        self.drivers = {}
        # Create packet receivers for all edge interfaces
        self.receivers = {}

        # Initialize drivers and receivers for each column/row
        for side in ('n', 's', 'e', 'w'):
            if side in ('n', 's'):
                length = self.params.n_columns
            else:
                length = self.params.n_rows
            for col in range(length):
                for channel in range(self.params.lane.n_channels):
                    label = (side, col+1, channel)
                    self.drivers[label] = packet_utils.PacketDriver(
                            dut=dut,
                            seed=make_seed(rnd),
                            valid_signal=getattr(dut, f'io_{side}i_{col}_{channel}_valid'),
                            ready_signal=getattr(dut, f'io_{side}i_{col}_{channel}_ready'),
                            data_signal=getattr(dut, f'io_{side}i_{col}_{channel}_bits_data'),
                            isheader_signal=getattr(dut, f'io_{side}i_{col}_{channel}_bits_isHeader'),
                            p_valid=0.5,
                        )
                    self.receivers[label] = packet_utils.PacketReceiver(
                        name=str(label),
                        dut=dut,
                        seed=make_seed(rnd),
                        valid_signal=getattr(dut, f'io_{side}o_{col}_{channel}_valid'),
                        ready_signal=getattr(dut, f'io_{side}o_{col}_{channel}_ready'),
                        data_signal=getattr(dut, f'io_{side}o_{col}_{channel}_bits_data'),
                        isheader_signal=getattr(dut, f'io_{side}o_{col}_{channel}_bits_isHeader'),
                    )

    def initialize_signals(self):
        """Initialize all input signals to default values"""
        for side in ('n', 's', 'e', 'w'):
            if side in ('n', 's'):
                length = self.params.n_columns
            else:
                length = self.params.n_rows
            for col in range(length):
                for channel in range(self.params.lane.n_channels):
                    getattr(self.dut, f'io_{side}i_{col}_{channel}_valid').value = 0
                    getattr(self.dut, f'io_{side}o_{col}_{channel}_ready').value = 0

    async def start(self):
        """Apply reset sequence and start all packet drivers/receivers"""
        # Apply reset sequence
        self.dut.reset.value = 0
        await triggers.RisingEdge(self.dut.clock)
        self.dut.reset.value = 1
        await triggers.RisingEdge(self.dut.clock)
        self.dut.reset.value = 0
        
        # Start all packet drivers and receivers
        for side in ('n', 's', 'e', 'w'):
            if side in ('n', 's'):
                length = self.params.n_columns
            else:
                length = self.params.n_rows
            for col in range(length):
                for channel in range(self.params.lane.n_channels):
                    label = (side, col+1, channel)
                    cocotb.start_soon(self.drivers[label].drive_packets())
                    cocotb.start_soon(self.receivers[label].receive_packets())

    async def write_register(self, lane_x: int, lane_y: int, reg: int, value: int):
        """Write a value to a register in a specific lane"""
        # Validate lane coordinates
        assert 0 <= lane_x < self.params.nColumns
        assert 0 <= lane_y < self.params.nRows
        
        # Create register write packet
        coord_packet = create_register_write_packet(
            register=reg,
            value=value,
            dest_x=lane_x,
            dest_y=lane_y,
            params=self.params.lane
        )
        
        # We'll always send this from the ('n', 1, 0) 
        driver = self.drivers[('n', 1, 0)]
        driver.add_packet(coord_packet)
        
        # Wait for packet processing
        for cycle in range(20):
            await triggers.RisingEdge(self.dut.clock)

    async def write_program(self, program: List, base_address: int = 0):
        """Write a program to instruction memory in a specific lane"""
        machine_code = [instr.encode() for instr in program]
        instr_packet = create_instruction_write_packet(
            machine_code,
            base_address,
            dest_x=self.params.n_columns-1,
            dest_y=self.params.n_rows-1,
            params=self.params.lane,
            is_broadcast=True,
        )
        
        # Send packet from appropriate edge
        driver = self.drivers[('n', 1, 0)]
        driver.add_packet(instr_packet)
        
        # Wait for instruction write
        for cycle in range(20):
            await triggers.RisingEdge(self.dut.clock)

    async def start_program(self, pc: int = 0):
        """Start program execution in a specific lane"""
        
        start_packet = create_start_packet(
            pc=pc,
            dest_x=self.params.n_columns-1,
            dest_y=self.params.n_rows-1,
            params=self.params.lane,
            is_broadcast = True,
        )
        # Send packet from appropriate edge
        driver = self.drivers[('n', 1, 0)]
        driver.add_packet(start_packet)

    async def send_data_packet(self, lane_x: int, lane_y: int, data: List[int], forward: bool = False, append_length: int = 0):
        """Send a data packet to a specific lane"""
        # Validate lane coordinates
        assert 1 <= lane_x <= self.params.n_columns
        assert 1 <= lane_y <= self.params.n_rows
        
        data_packet = create_data_packet(
            data=data,
            dest_x=lane_x,
            dest_y=lane_y,
            forward=forward,
            append_length=append_length
        )
        
        # Send packet from appropriate edge
        driver = self.drivers[('n', 1, 0)]
        driver.add_packet(data_packet)


    async def wait_for_program_to_run(self):
        """Wait for programs to finish execution"""
        for _ in range(40):
            await triggers.RisingEdge(self.dut.clock)

    def direction_from_x_and_y(self, src_x, src_y, dest_x, dest_y):
        if dest_x < 1:
            side = 'w'
            index = src_y
        elif dest_x > self.params.n_columns:
            side = 'e'
            index = src_y
        elif dest_y < 1:
            side = 'n'
            index = dest_x
        elif dest_y > self.params.n_rows:
            side = 's'
            index = dest_x
        else:
            # dst coords are in the array
            assert False
        return (side, index)

    async def get_packet(self, src_x, src_y, dest_x=0, dest_y=0, channel=0,
                         timeout=100, expected_length=None):
        packet = None
        side, index = self.direction_from_x_and_y(src_x, src_y, dest_x, dest_y)
        label = (side, index, channel)
        for cycle in range(timeout):
            await triggers.RisingEdge(self.dut.clock)
            if self.receivers[label].has_packet():
                packet = self.receivers[label].get_packet()
                header = packet_utils.PacketHeader.from_word(packet[0])
                assert header.dest_x == dest_x and header.dest_y == dest_y
                if expected_length is not None:
                    assert header.length == expected_length
                break
        assert packet is not None
        return packet
