import logging

import cocotb
from cocotb import triggers

from fmvpu.amlet import packet_utils
from fmvpu.bamlet.bamlet_params import BamletParams
from fmvpu.amlet.amlet_params import AmletParams


logger = logging.getLogger(__name__)


def create_register_write_packet(
    register: int,
    value: int,
    dest_x: int = 0,
    dest_y: int = 0,
    params: AmletParams = AmletParams(),
    is_broadcast: bool = False,
) -> list[int]:
    """Create a command packet to write a value to a register"""
    header = packet_utils.PacketHeader(
        length=1,  # One command word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=packet_utils.PacketHeaderModes.COMMAND,
        is_broadcast=is_broadcast,
    )
    command_word = packet_utils.create_register_write_command(register, value, params)
    return [header.encode(), command_word]


def create_instruction_write_packet(
    instructions: list[int],
    base_address: int = 0,
    dest_x: int = 0,
    dest_y: int = 0,
    params: AmletParams = AmletParams(),
    is_broadcast: bool = False,
) -> list[int]:
    """Create a command packet to write multiple instructions to instruction memory"""
    header = packet_utils.PacketHeader(
        length=len(instructions),  # One command word per instruction
        dest_x=dest_x,
        dest_y=dest_y,
        mode=packet_utils.PacketHeaderModes.COMMAND,
        is_broadcast=is_broadcast,
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
        pc: int, dest_x: int = 0, dest_y: int = 0, params: AmletParams = AmletParams(),
        is_broadcast: bool = False,
) -> list[int]:
    """Create a command packet to start execution at a given PC"""
    header = packet_utils.PacketHeader(
        length=1,  # One command word
        dest_x=dest_x,
        dest_y=dest_y,
        mode=packet_utils.PacketHeaderModes.COMMAND,
        is_broadcast=is_broadcast,
    )
    command_word = packet_utils.create_start_command(pc, params)
    return [header.encode(), command_word]


def create_data_packet(
        data: list[int], dest_x: int = 0, dest_y: int = 0, forward: bool = False,
        append_length: int = 0) -> list[int]:
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


def make_coord_register(x: int, y: int, params: AmletParams = AmletParams()) -> int:
    """Create coordinate register value: (y << x_pos_width) | x"""
    return (y << params.x_pos_width) | x

class BamletInterface:

    def __init__(self, dut, params, rnd, x, y):
        self.dut = dut
        self.params = params
        self.bamlet_x = x
        self.bamlet_y = y
        self.drivers = {}
        self.receivers = {}
        
        for side, index, channel in self.get_all_labels():
            self.drivers[(side, index, channel)] = packet_utils.PacketDriver(
                dut=dut,
                seed=make_seed(rnd),
                valid_signal=getattr(dut, f'io_{side}i_{index}_{channel}_valid'),
                ready_signal=getattr(dut, f'io_{side}i_{index}_{channel}_ready'),
                data_signal=getattr(dut, f'io_{side}i_{index}_{channel}_bits_data'),
                isheader_signal=getattr(dut, f'io_{side}i_{index}_{channel}_bits_isHeader'),
                p_valid=0.5,
            )
            self.receivers[(side, index, channel)] = packet_utils.PacketReceiver(
                name=f'{side}_{index}_{channel}',
                dut=dut,
                seed=make_seed(rnd),
                valid_signal=getattr(dut, f'io_{side}o_{index}_{channel}_valid'),
                ready_signal=getattr(dut, f'io_{side}o_{index}_{channel}_ready'),
                data_signal=getattr(dut, f'io_{side}o_{index}_{channel}_bits_data'),
                isheader_signal=getattr(dut, f'io_{side}o_{index}_{channel}_bits_isHeader'),
            )

    def get_all_labels(self):
        """Return all (side, index, channel) labels"""
        labels = []
        for side in ['n', 's', 'e', 'w']:
            index_range = self.params.n_amlet_columns if side in ['n', 's'] else self.params.n_amlet_rows
            for index in range(index_range):
                for channel in range(self.params.amlet.n_channels):
                    labels.append((side, index, channel))
        return labels

    def initialize_signals(self):
        self.dut.io_thisX.value = self.bamlet_x
        self.dut.io_thisY.value = self.bamlet_y
        # Initialize all network inputs
        for side, index, channel in self.get_all_labels():
            getattr(self.dut, f'io_{side}i_{index}_{channel}_valid').value = 0

    async def start(self):
        # Apply reset sequence
        self.dut.reset.value = 0
        await triggers.RisingEdge(self.dut.clock)
        self.dut.reset.value = 1
        await triggers.RisingEdge(self.dut.clock)
        self.dut.reset.value = 0
        # Start packet driver and receivers after reset
        for label in self.get_all_labels():
            cocotb.start_soon(self.drivers[label].drive_packets())
            cocotb.start_soon(self.receivers[label].receive_packets())

    async def write_register(self, reg, value, side='w', index=0, channel=0, offset_x=0, offset_y=0):
        # We can only write width - regaddrwidth - 2 bits
        writeable_width = self.params.amlet.width - self.params.amlet.d_reg_width - 2
        assert value < (1 << writeable_width)
        coord_packet = create_register_write_packet(
            register=reg, value=value, dest_x=self.bamlet_x + offset_x, dest_y=self.bamlet_y + offset_y, params=self.params.amlet
        )
        self.drivers[(side, index, channel)].add_packet(coord_packet)
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

    async def write_program(self, program, base_address=0, side='w', index=0, channel=0, offset_x=0, offset_y=0):
        machine_code = [instr.encode() for instr in program]
        instr_packet = create_instruction_write_packet(
            machine_code, base_address, dest_x=self.bamlet_x + offset_x, dest_y=self.bamlet_y + offset_y, params=self.params.amlet
        )
        self.drivers[(side, index, channel)].add_packet(instr_packet)
        # Wait for instruction write
        for cycle in range(20):
            await triggers.RisingEdge(self.dut.clock)

    async def get_packet_from_side(self, side, timeout=100):
        packet = None
        for cycle in range(timeout):
            await triggers.RisingEdge(self.dut.clock)
            if self.receivers[side].has_packet():
                packet = self.receivers[side].get_packet()
                break
        assert packet is not None
        return packet

    async def get_packet(self, dest_x=0, dest_y=0, offset_x=0, offset_y=0, channel=0, timeout=100, expected_length=None):
        side, index = self.direction_from_x_and_y(dest_x, dest_y, offset_x, offset_y)
        packet = await self.get_packet_from_side(side, index, channel, timeout)
        header = packet_utils.PacketHeader.from_word(packet[0])
        assert header.dest_x == dest_x and header.dest_y == dest_y
        if expected_length is not None:
            assert header.length == expected_length
        return packet

    async def send_packet(self, data, forward=False, side='w', index=0, channel=0, append_length=0, offset_x=0, offset_y=0):
        data_packet = create_data_packet(
                data=data, dest_x=self.bamlet_x + offset_x, dest_y=self.bamlet_y + offset_y, forward=forward, append_length=append_length,
                )
        self.drivers[(side, index, channel)].add_packet(data_packet)

    async def start_program(self, pc=0, side='w', index=0, channel=0, offset_x=0, offset_y=0):
        start_packet = create_start_packet(pc=0, dest_x=self.bamlet_x + offset_x, dest_y=self.bamlet_y + offset_y, params=self.params.amlet)
        self.drivers[(side, index, channel)].add_packet(start_packet)

    async def wait_for_program_to_run(self):
        """Wait 40 cycles for the program to finish execution"""
        for _ in range(40):
            await triggers.RisingEdge(self.dut.clock)

    def direction_from_x_and_y(self, dst_x: int, dst_y: int, offset_x: int = 0, offset_y: int = 0):
        """What direction and label a packet will emerge from given destination and source lane offset."""
        src_x = self.bamlet_x + offset_x
        src_y = self.bamlet_y + offset_y
        
        # Assert destination is not within the bamlet grid
        bamlet_x_min = self.bamlet_x
        bamlet_x_max = self.bamlet_x + self.params.n_amlet_columns - 1
        bamlet_y_min = self.bamlet_y
        bamlet_y_max = self.bamlet_y + self.params.n_amlet_rows - 1
        
        assert not (bamlet_x_min <= dst_x <= bamlet_x_max and bamlet_y_min <= dst_y <= bamlet_y_max), \
            f"Destination ({dst_x}, {dst_y}) lies within bamlet grid"
        
        if dst_x < bamlet_x_min:
            # West of bamlet - emerges on west edge at src row index
            return 'w', offset_y
        elif dst_x > bamlet_x_max:
            # East of bamlet - emerges on east edge at src row index
            return 'e', offset_y
        elif dst_y < bamlet_y_min:
            # North of bamlet - emerges on north edge at dst column index
            return 'n', dst_x - bamlet_x_min
        else:
            # South of bamlet - emerges on south edge at dst column index
            return 's', dst_x - bamlet_x_min
