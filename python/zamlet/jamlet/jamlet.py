import logging
from typing import Set, List, Any, Tuple

from zamlet import addresses
from zamlet.params import LamletParams
from zamlet.kamlet.cache_table import CacheTable
from zamlet.message import Direction, SendType, MessageType, CHANNEL_MAPPING
from zamlet.message import Header, IdentHeader, AddressHeader, ValueHeader, TaggedHeader, WriteSetIdentHeader
from zamlet.utils import Queue
from zamlet.router import Router
from zamlet.kamlet import kinstructions
from zamlet import memlet
from zamlet import utils
from zamlet.kamlet import ew_convert
from zamlet.kamlet import cache_table
from zamlet.kamlet.cache_table import CacheRequestType, WaitingItem, CacheState
from zamlet.register_file_slot import KamletRegisterFile
from zamlet.transactions import MESSAGE_HANDLERS


logger = logging.getLogger(__name__)


def jamlet_coords_to_frontend_coords(params, x, y):
    return (0, -1)


class Jamlet:
    """
    A single lane of the processor.
    """

    def __init__(self, clock, params: LamletParams, x: int, y: int, cache_table: CacheTable,
                 rf_info: KamletRegisterFile, tlb: addresses.TLB):
        self.clock = clock
        self.params = params
        self.x = x
        self.y = y

        k_x = x//self.params.j_cols
        k_y = y//self.params.j_rows
        self.k_index = k_y * self.params.k_cols + k_x
        j_in_k_x = x % self.params.j_cols
        j_in_k_y = y % self.params.j_rows
        self.j_in_k_index = j_in_k_y * self.params.j_cols + j_in_k_x

        # The coords of the memlet router that this jamlet talks to.
        self.mem_x, self.mem_y = memlet.jamlet_coords_to_m_router_coords(params, x, y)

        # The coords of the frontend that this jamlet talks to.
        self.front_x, self.front_y = jamlet_coords_to_frontend_coords(params, x, y)

        # The register file in this jamlet.  It's referred to as a register file
        # slice since it's part of a logically larger register file.
        rf_slice_bytes = (params.maxvl_bytes // params.k_cols // params.k_rows //
                          params.j_cols // params.j_rows * params.n_vregs)
        self.rf_slice = bytearray([0] * rf_slice_bytes)

        # The jamlet contains some SRAM. Currently this is used as cache.
        self.sram = bytearray([0] * params.jamlet_sram_bytes)

        # The receive buffer is used for receiving messages from SEND messages.
        # It's used to reorder the messages so that we get deterministic ordering.
        self.receive_buffer = [None] * params.receive_buffer_depth

        self.routers = [Router(clock=clock, params=params, x=x, y=y, channel=ch)
                         for ch in range(params.n_channels)]

        # This is just a queue to hand instructions up to kamlet.
        self._instruction_buffer = Queue(2)

        # We have a queue for each type of message that we can send.
        # This is so that we can add multiple messages every cycle
        # without worrying out non-deterministic order of the async
        # functions.
        self.send_queues = {
            MessageType.LOAD_BYTE_RESP: Queue(2),
            MessageType.READ_BYTE_RESP: Queue(2),
            #MessageType.WRITE_LINE: Queue(2),
            MessageType.READ_LINE: Queue(2),
            MessageType.WRITE_LINE_READ_LINE: Queue(2),
            MessageType.LOAD_J2J_WORDS_REQ: Queue(2),
            MessageType.LOAD_J2J_WORDS_RESP: Queue(2),
            MessageType.LOAD_J2J_WORDS_DROP: Queue(2),
            MessageType.LOAD_J2J_WORDS_RETRY: Queue(2),
            MessageType.STORE_J2J_WORDS_REQ: Queue(2),
            MessageType.STORE_J2J_WORDS_RESP: Queue(2),
            MessageType.STORE_J2J_WORDS_DROP: Queue(2),
            MessageType.STORE_J2J_WORDS_RETRY: Queue(2),
            MessageType.LOAD_WORD_REQ: Queue(2),
            MessageType.LOAD_WORD_RESP: Queue(2),
            MessageType.LOAD_WORD_DROP: Queue(2),
            MessageType.LOAD_WORD_RETRY: Queue(2),
            MessageType.STORE_WORD_REQ: Queue(2),
            MessageType.STORE_WORD_RESP: Queue(2),
            MessageType.STORE_WORD_DROP: Queue(2),
            MessageType.STORE_WORD_RETRY: Queue(2),
            MessageType.READ_MEM_WORD_REQ: Queue(2),
            MessageType.READ_MEM_WORD_RESP: Queue(2),
            MessageType.READ_MEM_WORD_DROP: Queue(2),
            MessageType.WRITE_MEM_WORD_REQ: Queue(2),
            MessageType.WRITE_MEM_WORD_RESP: Queue(2),
            MessageType.WRITE_MEM_WORD_DROP: Queue(2),
            MessageType.WRITE_MEM_WORD_RETRY: Queue(2),
            MessageType.IDENT_QUERY_RESP: Queue(2),
            }

        # Shared with the parent kamlet
        self.cache_table = cache_table
        self.rf_info = rf_info
        self.tlb = tlb

    async def send_packet(self, packet):
        assert isinstance(packet[0], Header)
        assert len(packet) == packet[0].length, (
            f"Packet length mismatch: len(packet)={len(packet)}, header.length={packet[0].length}")
        message_type = packet[0].message_type
        header = packet[0]
        logger.debug(
            f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): send_packet queuing '
            f'{message_type.name} target=({header.target_x}, {header.target_y})')
        wait_count = 0
        while not self.send_queues[message_type].can_append():
            wait_count += 1
            if wait_count > 100:
                queue = self.send_queues[message_type]
                logger.error(
                    f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): send_packet BLOCKED '
                    f'{message_type.name} target=({header.target_x}, {header.target_y}) '
                    f'queue_len={len(queue)} queue_length={queue.length}')
                wait_count = 0
            await self.clock.next_cycle
        self.send_queues[message_type].append(packet)

    async def _send_packet(self, packet):
        assert isinstance(packet[0], Header)
        assert len(packet) == packet[0].length
        # This is only called from _send_packets
        header = packet[0]
        logger.debug(
            f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): _send_packet starting '
            f'{header.message_type.name} target=({header.target_x}, {header.target_y})')
        channel = CHANNEL_MAPPING[packet[0].message_type]
        queue = self.routers[channel]._input_buffers[Direction.H]
        stuck_count = 0
        while True:
            if queue.can_append():
                word = packet.pop(0)
                queue.append(word)
                stuck_count = 0
                if not packet:
                    await self.clock.next_cycle
                    break
            else:
                stuck_count += 1
                if stuck_count > 100:
                    logger.error(
                        f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): _send_packet STUCK '
                        f'{header.message_type.name} target=({header.target_x}, {header.target_y}) '
                        f'queue_len={len(queue)} queue_length_limit={queue.length} '
                        f'queue_appended={queue.appended}')
                    stuck_count = 0
            await self.clock.next_cycle
        logger.debug(
            f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): _send_packet finished '
            f'{header.message_type.name} target=({header.target_x}, {header.target_y})')

    async def _send_packets_channel0(self):
        """Send packets on channel 0 (always-consumable responses)."""
        while True:
            sent_something = False
            for msg_type, send_queue in self.send_queues.items():
                if CHANNEL_MAPPING.get(msg_type) == 0 and send_queue:
                    await self._send_packet(send_queue.popleft())
                    sent_something = True
            if not sent_something:
                await self.clock.next_cycle

    async def _send_packets(self):
        """Send packets on channels other than 0."""
        while True:
            sent_something = False
            for msg_type, send_queue in self.send_queues.items():
                if CHANNEL_MAPPING.get(msg_type) != 0 and send_queue:
                    await self._send_packet(send_queue.popleft())
                    sent_something = True
            if not sent_something:
                await self.clock.next_cycle

    def has_instruction(self):
        return bool(self._instruction_buffer)

    async def write_read_cache_line(self, cache_slot: int, write_address: int, read_address: int, ident: int):
        """
        Writes this jamlets share of a cache line to memory and reads a new cache line.
        """
        address_in_sram = cache_slot * self.params.cache_line_bytes // self.params.j_in_k
        n_words = self.params.cache_line_bytes // self.params.j_in_k // self.params.word_bytes
        header = AddressHeader(
            message_type=MessageType.WRITE_LINE_READ_LINE,
            send_type=SendType.SINGLE,
            target_x=self.mem_x,
            target_y=self.mem_y,
            source_x=self.x,
            source_y=self.y,
            length=n_words+3,
            ident=ident,
            address=address_in_sram,
            )
        packet = [header, write_address, read_address]
        wb = self.params.word_bytes
        for index in range(n_words):
            word = self.sram[address_in_sram + index * wb: address_in_sram + (index+1) * wb]
            packet.append(word)
        logger.debug(f'{self.clock.cycle}: jamlet ({self.x},{self.y}): Sending cache line from sram {address_in_sram} words={packet[3:]}')
        send_queue = self.send_queues[header.message_type]
        while not send_queue.can_append():
            await self.clock.next_cycle
        send_queue.append(packet)

    def update(self):
        for router in self.routers:
            router.update()
        self._instruction_buffer.update()
        for queue in self.send_queues.values():
            queue.update()

    async def _receive_instructions_packet(self, header, queue):
        remaining = header.length - 1
        while remaining:
            if queue and self._instruction_buffer.can_append():
                word = queue.popleft()
                self._instruction_buffer.append(word)
                remaining -= 1
            await self.clock.next_cycle

    async def _receive_read_line_resp_packet(self, header, queue):
        # The packet should say where to put the data.
        # It only needs the 'slot' which should fit fine in the packet.
        remaining = header.length - 1
        wb = self.params.word_bytes
        s_address = header.address

        # Some some debug checking
        cache_line_bytes_per_jamlet = self.params.cache_line_bytes // self.params.j_in_k
        slot = s_address//cache_line_bytes_per_jamlet
        slot_state = self.cache_table.slot_states[slot]
        assert slot_state.state in (CacheState.READING, CacheState.WRITING_READING)

        assert s_address % wb == 0
        assert remaining == self.params.vlines_in_cache_line
        index = 0
        while remaining:
            if queue:
                word = queue.popleft()
                sram_addr = s_address + index * wb
                old_word = self.sram[sram_addr: sram_addr + wb]
                self.sram[sram_addr: sram_addr + wb] = word
                logger.debug(
                    f'{self.clock.cycle}: CACHE_WRITE READ_LINE_RESP: jamlet ({self.x},{self.y}) '
                    f'sram[{sram_addr}] old={old_word.hex()} new={word.hex()}'
                )
                remaining -= 1
                index += 1
            await self.clock.next_cycle
        # And we want to let the kamlet know we got this response
        self.cache_table.receive_cache_response(header)

    async def _receive_write_line_resp_packet(self, header, queue):
        assert header.length == 1
        self.cache_table.receive_cache_response(header)

    async def _receive_packet_channel0(self, queue):
        """Handle channel 0 packets (always-consumable responses). These never need to send."""
        while not queue:
            await self.clock.next_cycle
        header = queue.popleft()
        assert isinstance(header, Header)
        logger.debug(
            f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): _receive_packet_channel0 got header '
            f'{header.message_type.name} from ({header.source_x}, {header.source_y})')
        await self.clock.next_cycle
        if header.message_type == MessageType.INSTRUCTIONS:
            await self._receive_instructions_packet(header, queue)
        elif header.message_type == MessageType.READ_LINE_RESP:
            await self._receive_read_line_resp_packet(header, queue)
        elif header.message_type == MessageType.WRITE_LINE_RESP:
            await self._receive_write_line_resp_packet(header, queue)
        elif header.message_type == MessageType.WRITE_LINE_READ_LINE_RESP:
            await self._receive_read_line_resp_packet(header, queue)
        else:
            handler = MESSAGE_HANDLERS.get(header.message_type)
            if handler is None:
                raise NotImplementedError(f"No handler for channel 0 message {header.message_type}")
            packet = await self._receive_packet_body(queue, header)
            result = handler(self, packet)
            assert result is None, f"Channel 0 handler for {header.message_type} must be sync (not async)"

    async def _receive_packet(self, queue):
        """Handle channel 1+ packets (requests that may need to send responses)."""
        while not queue:
            await self.clock.next_cycle
        header = queue.popleft()
        assert isinstance(header, Header)
        logger.debug(
            f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): _receive_packet got header '
            f'{header.message_type.name} from ({header.source_x}, {header.source_y})')
        await self.clock.next_cycle
        handler = MESSAGE_HANDLERS.get(header.message_type)
        if handler is None:
            raise NotImplementedError(f"No handler for {header.message_type}")
        packet = await self._receive_packet_body(queue, header)
        await handler(self, packet)

    async def _receive_packet_body(self, queue, header):
        packet = [header]
        remaining_words = header.length - 1
        wait_count = 0
        while remaining_words > 0:
            if queue:
                word = queue.popleft()
                packet.append(word)
                remaining_words -= 1
                wait_count = 0
            else:
                wait_count += 1
                if wait_count > 100:
                    logger.error(
                        f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): '
                        f'_receive_packet_body STUCK waiting for {remaining_words} more words, '
                        f'header={header}')
                    wait_count = 0
            await self.clock.next_cycle
        return packet

    async def _receive_packets_channel0(self):
        """Handle channel 0 (always-consumable responses) separately to avoid deadlock."""
        router = self.routers[0]
        queue = router._output_buffers[Direction.H]
        while True:
            await self.clock.next_cycle
            if queue:
                logger.debug(
                    f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): '
                    f'_receive_packets_channel0 calling _receive_packet_channel0, queue_len={len(queue)}')
                await self._receive_packet_channel0(queue)
                logger.debug(
                    f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): '
                    f'_receive_packets_channel0 returned from _receive_packet_channel0')

    async def _receive_packets(self):
        while True:
            await self.clock.next_cycle
            for router_idx, router in enumerate(self.routers[1:], start=1):
                queue = router._output_buffers[Direction.H]
                if queue:
                    logger.debug(
                        f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): '
                        f'_receive_packets calling _receive_packet on ch{router_idx}, queue_len={len(queue)}')
                    await self._receive_packet(queue)
                    logger.debug(
                        f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): '
                        f'_receive_packets returned from _receive_packet on ch{router_idx}')

    async def _monitor_cache_requests(self):
        # NOTE: WRITE_LINE_READ_LINE is now handled at the kamlet level to ensure
        # all jamlets send packets for the same request before moving to the next.
        # READ_LINE is also handled at the kamlet level.
        # This method is kept for potential future use.
        while True:
            await self.clock.next_cycle

    async def _monitor_witems(self) -> None:
        while True:
            await self.clock.next_cycle
            for witem in self.cache_table.waiting_items:
                if witem is not None:
                    await witem.monitor_jamlet(self)

    async def run(self):
        for router in self.routers:
            self.clock.create_task(router.run())
        self.clock.create_task(self._send_packets_channel0())
        self.clock.create_task(self._send_packets())
        self.clock.create_task(self._receive_packets_channel0())
        self.clock.create_task(self._receive_packets())
        self.clock.create_task(self._monitor_witems())
        self.clock.create_task(self._monitor_cache_requests())

    SEND = 0
    INSTRUCTIONS = 1
