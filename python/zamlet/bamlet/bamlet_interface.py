import logging
from dataclasses import fields

import cocotb
from cocotb import triggers

from zamlet.amlet import packet_utils
from zamlet.bamlet.bamlet_params import BamletParams
from zamlet.amlet.amlet_params import AmletParams
from zamlet.utils import make_seed


logger = logging.getLogger(__name__)


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
                p_valid=1.0,
                name=f'{side}_{index}_{channel}',
            )
            self.receivers[(side, index, channel)] = packet_utils.PacketReceiver(
                name=f'{side}_{index}_{channel}',
                dut=dut,
                seed=make_seed(rnd),
                valid_signal=getattr(dut, f'io_{side}o_{index}_{channel}_valid'),
                ready_signal=getattr(dut, f'io_{side}o_{index}_{channel}_ready'),
                data_signal=getattr(dut, f'io_{side}o_{index}_{channel}_bits_data'),
                isheader_signal=getattr(dut, f'io_{side}o_{index}_{channel}_bits_isHeader'),
                p_ready=1.0,
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
        logger.info('start: starting')
        # Apply reset sequence
        self.dut.reset.value = 0
        await triggers.RisingEdge(self.dut.clock)
        self.dut.reset.value = 1
        await triggers.RisingEdge(self.dut.clock)
        self.dut.reset.value = 0
        for i in range(3):
            await triggers.RisingEdge(self.dut.clock)
        logger.info('start: done reset')
        # Start packet driver and receivers after reset
        for label in self.get_all_labels():
            cocotb.start_soon(self.drivers[label].drive_packets())
            cocotb.start_soon(self.receivers[label].receive_packets())
        cocotb.start_soon(self.check_errors())
        logger.info('start: finishing')


    async def write_register(self, reg_type, reg, value, side='w', index=0, channel=0, offset_x=0, offset_y=0):
        coord_packet = packet_utils.create_register_write_packet(
            register=reg, value=value, reg_type=reg_type, dest_x=self.bamlet_x + offset_x, dest_y=self.bamlet_y + offset_y, params=self.params.amlet
        )
        self.drivers[(side, index, channel)].add_packet(coord_packet)
        # Wait 20 cycles for packet processing
        for cycle in range(20):
            await triggers.RisingEdge(self.dut.clock)
        # Verify the write worked by reading back the value
        probed_value = self.probe_register(reg_type, reg, offset_x, offset_y)
        logger.info(f'Wrote {reg_type} {reg} -> {value}')
        assert probed_value == value, f"{reg_type.upper()}-register {reg} write failed: expected {value}, got {probed_value}"


    def probe_register(self, reg_type, reg, offset_x=0, offset_y=0):
        """Read the current value of a register"""
        if reg_type == 'a':
            assert 0 <= reg < self.params.amlet.n_a_regs, f"A-register {reg} out of range [0, {self.params.amlet.n_a_regs})"
            amlet = self.get_amlet(offset_x, offset_y)
            return int(getattr(amlet.registerFileAndRename.aRF, f'state_{reg}_value').value)
        elif reg_type == 'd':
            assert 0 <= reg < self.params.amlet.n_d_regs, f"D-register {reg} out of range [0, {self.params.amlet.n_d_regs})"
            amlet = self.get_amlet(offset_x, offset_y)
            return int(getattr(amlet.registerFileAndRename.dRF, f'state_{reg}_value').value)
        elif reg_type == 'p':
            assert 0 <= reg < self.params.amlet.n_p_regs, f"P-register {reg} out of range [0, {self.params.amlet.n_p_regs})"
            amlet = self.get_amlet(offset_x, offset_y)
            return int(getattr(amlet.registerFileAndRename.pRF, f'state_{reg}_value').value)
        elif reg_type == 'g':
            assert 0 <= reg < self.params.amlet.n_g_regs, f"G-register {reg} out of range [0, {self.params.amlet.n_g_regs})"
            return int(getattr(self.dut.control, f'state_globals_{reg}').value)
        else:
            assert False, f"Invalid register type: {reg_type}"


    def write_program(self, program, base_address=0, side='w', index=0, channel=0, offset_x=0, offset_y=0):
        instr_packet = packet_utils.create_instruction_write_packet(
            program, base_address, dest_x=self.bamlet_x + offset_x, dest_y=self.bamlet_y + offset_y, params=self.params.amlet
        )
        logger.info(f'length of instr packet is {len(instr_packet)}')
        self.drivers[(side, index, channel)].add_packet(instr_packet)

    async def get_packet_from_side(self, side, index, channel, timeout=100):
        packet = None
        label = (side, index, channel)
        for cycle in range(timeout):
            await triggers.RisingEdge(self.dut.clock)
            if self.receivers[label].has_packet():
                packet = self.receivers[label].get_packet()
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
        data_packet = packet_utils.create_data_packet(
                data=data, dest_x=self.bamlet_x + offset_x, dest_y=self.bamlet_y + offset_y, forward=forward, append_length=append_length,
                )
        self.drivers[(side, index, channel)].add_packet(data_packet)

    async def start_program(self, pc=0, side='w', index=0, channel=0, offset_x=0, offset_y=0):
        start_packet = packet_utils.create_start_packet(pc=0, dest_x=self.bamlet_x + offset_x, dest_y=self.bamlet_y + offset_y, params=self.params.amlet)
        self.drivers[(side, index, channel)].add_packet(start_packet)

    async def wait_for_program_to_run(self, timeout=1000):
        for _ in range(10):
            await triggers.RisingEdge(self.dut.clock)
        for _ in range(timeout):
            await triggers.RisingEdge(self.dut.clock)
            await triggers.ReadOnly()
            if not self.dut.control.state_active.value:
                break
        for _ in range(100):
            await triggers.RisingEdge(self.dut.clock)

    def get_amlet(self, offset_x, offset_y):
        """Get access to a specific amlet in the bamlet grid.
        If row/col not specified, uses the current bamlet position."""
        x = self.bamlet_x + offset_x
        y = self.bamlet_y + offset_y
        index = offset_y * self.params.n_amlet_columns + offset_x
        if index == 0:
            label = 'Amlet'
        else:
            label = f'Amlet_{index}'
        amlet_dut = getattr(self.dut, label)
        return amlet_dut

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

    def write_args(self, args, regs, side, channel):
        # For now we assume that the broadcast goes in at the minimum index on that side.
        # We assume that the unique packets are sent along the entire side edge.
        assert side in ('n', 's', 'e', 'w')
        if side == 'n':
            broadcast_coord = (self.bamlet_x + self.params.n_amlet_columns - 1,
                               self.bamlet_y + self.params.n_amlet_rows - 1)
        elif side == 's':
            broadcast_coord = (self.bamlet_x + self.params.n_amlet_columns - 1,
                               self.bamlet_y)
        elif side == 'e':
            broadcast_coord = (self.bamlet_x,
                               self.bamlet_y + self.params.n_amlet_rows - 1)
        else:
            broadcast_coord = (self.bamlet_x + self.params.n_amlet_columns - 1,
                               self.bamlet_y + self.params.n_amlet_rows - 1)
        amlet_coords = []
        for y in range(self.params.n_amlet_rows):
            for x in range(self.params.n_amlet_columns):
                amlet_coords.append((self.bamlet_x + x, self.bamlet_y + y))
        broadcast_packet, unique_packets = packet_utils.make_write_args_packets(
            self.params.amlet, args, regs, broadcast_coord, amlet_coords)
        broadcast_driver = self.drivers[(side, 0, channel)]
        broadcast_driver.add_packet(broadcast_packet)
        if side in ('n', 's'):
            side_length = self.params.n_amlet_columns
        else:
            side_length = self.params.n_amlet_rows
        drivers = [self.drivers[(side, index, channel)] for index in range(side_length)]
        for coord, packet in zip(amlet_coords, unique_packets):
            # For each unique packet send it to the driver for the appropriate
            # column or row.
            if side in ('n', 's'):
                index = coord[0] - self.bamlet_x
            else:
                index = coord[1] - self.bamlet_y
            assert index < side_length
            drivers[index].add_packet(packet)
        
    async def wait_to_send_packets(self, timeout=1000):
        count = 0
        while True:
            all_empty = True
            for driver in self.drivers.values():
                if not driver.empty:
                    all_empty = False
            if all_empty:
                break
            await triggers.RisingEdge(self.dut.clock)
            count += 1
            assert count < timeout

        # Wait a bit more to give them time to go
        # through the network.
        for i in range(20):
            await triggers.RisingEdge(self.dut.clock)

    async def check_errors(self):
        amlet_error_wires = [
            'errors_receivePacketInterface_imWriteCountExceedsPacket',
            'errors_receivePacketInterface_instrAndCommandPacket',
            'errors_receivePacketInterface_unexpectedHeader',
            'errors_receivePacketInterface_wrongInstructionMode',
            'errors_loadStoreRS_noFreeSlots',
            'errors_aluRS_noFreeSlots',
            'errors_aluPredicateRS_noFreeSlots',
            'errors_aluLiteRS_noFreeSlots',
            'errors_receivePacketRS_noFreeSlots',
            'errors_sendPacketRS_noFreeSlots',
            ]
        while True:
            await triggers.RisingEdge(self.dut.clock)
            await triggers.ReadOnly()
            
            # Check bamlet-level control errors
            for amlet_index in range(self.params.n_amlets):
                if getattr(self.dut, f'errors_control_unexpectedLoopIterations_{amlet_index}').value != 0:
                    row = amlet_index // self.params.n_amlet_columns
                    col = amlet_index % self.params.n_amlet_columns
                    raise Exception(f'Control error: unexpected loop iterations from amlet ({col},{row}) index {amlet_index}')
            
            # Check amlet-level errors
            for x in range(self.params.n_amlet_columns):
                for y in range(self.params.n_amlet_rows):
                    amlet = self.get_amlet(x, y)
                    for error_wire in amlet_error_wires:
                        if getattr(amlet, error_wire).value != 0:
                            raise Exception(f'Error wire {error_wire} has gone high on amlet ({x},{y})')

    def probe_vdm_data(self, x, y, addr):
        amlet = self.get_amlet(x, y)
        probed_data = amlet.dataMem.mem_ext.Memory[addr].value
        return probed_data
