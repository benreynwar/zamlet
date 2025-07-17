import logging

import cocotb
from cocotb import triggers

from fmvpu.lane import packet_utils
from fmvpu.lane.lane_params import LaneParams


logger = logging.getLogger(__name__)


def create_register_write_packet(
    register: int,
    value: int,
    dest_x: int = 0,
    dest_y: int = 0,
    params: LaneParams = LaneParams(),
) -> list[int]:
    """Create a command packet to write a value to a register"""
    header = packet_utils.PacketHeader(
        length=1,  # One command word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=packet_utils.PacketHeaderModes.COMMAND,
    )
    command_word = packet_utils.create_register_write_command(register, value, params)
    return [header.encode(), command_word]


def create_instruction_write_packet(
    instructions: list[int],
    base_address: int = 0,
    dest_x: int = 0,
    dest_y: int = 0,
    params: LaneParams = LaneParams(),
) -> list[int]:
    """Create a command packet to write multiple instructions to instruction memory"""
    header = packet_utils.PacketHeader(
        length=len(instructions),  # One command word per instruction
        dest_x=dest_x,
        dest_y=dest_y,
        mode=packet_utils.PacketHeaderModes.COMMAND,
    )
    command_words = []
    for i, instruction in enumerate(instructions):
        address = base_address + i
        command_word = packet_utils.create_instruction_memory_write_command(
            address, instruction, params
        )
        command_words.append(command_word)
    return [header.encode()] + command_words


def create_start_packet(
    pc: int, dest_x: int = 0, dest_y: int = 0, params: LaneParams = LaneParams()
) -> list[int]:
    """Create a command packet to start execution at a given PC"""
    header = packet_utils.PacketHeader(
        length=1,  # One command word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=packet_utils.PacketHeaderModes.COMMAND,
    )
    command_word = packet_utils.create_start_command(pc, params)
    return [header.encode(), command_word]


def create_data_packet(
        data: list[int], dest_x: int = 0, dest_y: int = 0, forward: bool = False,
        append_length: bool = False) -> list[int]:
    """Send a data packet in"""
    header = packet_utils.PacketHeader(
        length=len(data), # One command word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=packet_utils.PacketHeaderModes.NORMAL,
        forward=forward,
        append_length=append_length,
    )
    return [header.encode()] + data


def make_seed(rnd):
    return rnd.getrandbits(32)


def make_coord_register(x: int, y: int, params: LaneParams = LaneParams()) -> int:
    """Create coordinate register value: (y << x_pos_width) | x"""
    return (y << params.x_pos_width) | x

class LaneInterface:

    def __init__(self, dut, params, rnd, x, y):
        self.dut = dut
        self.params = params
        self.lane_x = x
        self.lane_y = y
        self.drivers = {
            label: packet_utils.PacketDriver(
                dut=dut,
                seed=make_seed(rnd),
                valid_signal=getattr(dut, f'io_{label}i_0_valid'),
                ready_signal=getattr(dut, f'io_{label}i_0_ready'),
                data_signal=getattr(dut, f'io_{label}i_0_bits_data'),
                isheader_signal=getattr(dut, f'io_{label}i_0_bits_isHeader'),
                p_valid=0.5,
            )
            for label in ['n', 's', 'e', 'w']}

        self.receivers = {
            label: packet_utils.PacketReceiver(
                name=label,
                dut=dut,
                seed=make_seed(rnd),
                valid_signal=getattr(dut, f'io_{label}o_0_valid'),
                ready_signal=getattr(dut, f'io_{label}o_0_ready'),
                data_signal=getattr(dut, f'io_{label}o_0_bits_data'),
                isheader_signal=getattr(dut, f'io_{label}o_0_bits_isHeader'),
            )
            for label in ['n', 's', 'e', 'w']}

    def initialize_signals(self):
        self.dut.io_thisX.value = self.lane_x
        self.dut.io_thisY.value = self.lane_y
        # Initialize network inputs
        self.dut.io_ni_0_valid.value = 0
        self.dut.io_si_0_valid.value = 0
        self.dut.io_ei_0_valid.value = 0
        self.dut.io_wi_0_valid.value = 0

    async def start(self):
        # Apply reset sequence
        self.dut.reset.value = 0
        await triggers.RisingEdge(self.dut.clock)
        self.dut.reset.value = 1
        await triggers.RisingEdge(self.dut.clock)
        self.dut.reset.value = 0
        # Start packet driver and receivers after reset
        for label in ['n', 's', 'e', 'w']:
            cocotb.start_soon(self.drivers[label].drive_packets())
            cocotb.start_soon(self.receivers[label].receive_packets())

    async def write_register(self, reg, value):
        # We can only write width - regaddrwidth - 2 bits
        writeable_width = self.params.width - self.params.reg_addr_width - 2
        assert value < (1 << writeable_width)
        coord_packet = create_register_write_packet(
            register=reg, value=value, dest_x=self.lane_x, dest_y=self.lane_y
        )
        self.drivers['w'].add_packet(coord_packet)
        # Wait 20 cycles for packet processing
        for cycle in range(20):
            await triggers.RisingEdge(self.dut.clock)

        probed_value = getattr(self.dut.rff, f'registers_{reg}_value').value
        assert probed_value == value

    async def read_register(self, reg):
        """Read the current value of a register"""
        for cycle in range(40):
            await triggers.RisingEdge(self.dut.clock)
        return int(getattr(self.dut.rff, f'registers_{reg}_value').value)

    async def write_program(self, program, base_address=0):
        machine_code = [instr.encode() for instr in program]
        instr_packet = create_instruction_write_packet(
            machine_code, base_address, dest_x=self.lane_x, dest_y=self.lane_y
        )
        self.drivers['w'].add_packet(instr_packet)
        # Wait for instruction write
        for cycle in range(20):
            await triggers.RisingEdge(self.dut.clock)

    async def get_packet(self, dest_x=0, dest_y=0, timeout=100, expected_length=None):
        packet = None
        direction = self.direction_from_x_and_y(dest_x, dest_y)
        for cycle in range(timeout):
            await triggers.RisingEdge(self.dut.clock)
            if self.receivers[direction].has_packet():
                packet = self.receivers[direction].get_packet()
                header = packet_utils.PacketHeader.from_word(packet[0])
                assert header.dest_x == dest_x and header.dest_y == dest_y
                if expected_length is not None:
                    assert header.length == expected_length
                break
        assert packet is not None
        return packet

    async def send_packet(self, data, forward=False, append_length=0):
        data_packet = create_data_packet(
                data=data, dest_x=self.lane_x, dest_y=self.lane_y, forward=forward, append_length=append_length,
                )
        self.drivers['w'].add_packet(data_packet)

    async def start_program(self, pc=0):
        start_packet = create_start_packet(pc=0, dest_x=self.lane_x, dest_y=self.lane_y)
        self.drivers['w'].add_packet(start_packet)

    async def wait_for_program_to_run(self):
        """Wait 40 cycles for the program to finish execution"""
        for _ in range(40):
            await triggers.RisingEdge(self.dut.clock)

    def direction_from_x_and_y(self, x: int, y: int):
        """What direction a packet will come out of the node for a given destination."""
        assert not (x == self.lane_x and y == self.lane_y)
        if x < self.lane_x:
            return 'w'
        elif x > self.lane_x:
            return 'e'
        elif y < self.lane_y:
            return 'n'
        else:
            return 's'
