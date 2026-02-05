import logging
from typing import Set, List, Any, Tuple

from zamlet import addresses
from zamlet.params import LamletParams
from zamlet.kamlet.cache_table import CacheTable
from zamlet.message import Direction, SendType, MessageType, CHANNEL_MAPPING, is_request_message
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
from zamlet.monitor import Monitor


logger = logging.getLogger(__name__)


def jamlet_coords_to_frontend_coords(params, x, y):
    return (0, -1)


class Jamlet:
    """
    A single lane of the processor.
    """

    def __init__(self, clock, params: LamletParams, x: int, y: int, cache_table: CacheTable,
                 rf_info: KamletRegisterFile, tlb: addresses.TLB, monitor: Monitor,
                 lamlet_x: int, lamlet_y: int):
        self.clock = clock
        self.params = params
        self.monitor = monitor
        self.x = x
        self.y = y
        self.lamlet_x = lamlet_x
        self.lamlet_y = lamlet_y

        k_x = x // self.params.j_cols
        k_y = y // self.params.j_rows
        self.k_index = k_y * self.params.k_cols + k_x
        self.k_min_x = k_x * self.params.j_cols
        self.k_min_y = k_y * self.params.j_rows
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
            MessageType.STORE_J2J_WORDS_REQ: Queue(2),
            MessageType.STORE_J2J_WORDS_RESP: Queue(2),
            MessageType.STORE_J2J_WORDS_DROP: Queue(2),
            MessageType.STORE_J2J_WORDS_RETRY: Queue(2),
            MessageType.LOAD_WORD_REQ: Queue(2),
            MessageType.LOAD_WORD_RESP: Queue(2),
            MessageType.LOAD_WORD_DROP: Queue(2),
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
            MessageType.LOAD_INDEXED_ELEMENT_RESP: Queue(2),
            MessageType.STORE_INDEXED_ELEMENT_RESP: Queue(2),
            MessageType.READ_REG_ELEMENT_REQ: Queue(2),
            MessageType.READ_REG_ELEMENT_RESP: Queue(2),
            MessageType.READ_REG_ELEMENT_DROP: Queue(2),
            }

        # Shared with the parent kamlet
        self.cache_table = cache_table
        self.rf_info = rf_info
        self.tlb = tlb

    async def send_packet(self, packet, parent_span_id: int,
                          drop_reason: str | None = None):
        header = packet[0]
        assert isinstance(header, IdentHeader)
        assert len(packet) == header.length, (
            f"Packet length mismatch: len(packet)={len(packet)}, header.length={header.length}")
        message_type = header.message_type
        logger.debug(
            f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): send_packet queuing '
            f'{message_type.name} target=({header.target_x}, {header.target_y})')

        # Record message as child of parent span
        tag = getattr(header, 'tag', None)
        self.monitor.record_message_sent(
            parent_span_id, message_type.name,
            ident=header.ident, tag=tag,
            src_x=self.x, src_y=self.y,
            dst_x=header.target_x, dst_y=header.target_y,
            drop_reason=drop_reason,
        )

        blocked_cycles = 0
        while not self.send_queues[message_type].can_append():
            blocked_cycles += 1
            if blocked_cycles > 100 and blocked_cycles % 100 == 0:
                queue = self.send_queues[message_type]
                logger.error(
                    f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): send_packet BLOCKED '
                    f'{message_type.name} target=({header.target_x}, {header.target_y}) '
                    f'queue_len={len(queue)} queue_length={queue.length}')
            await self.clock.next_cycle
        self.monitor.record_send_queue_attempt(self.x, self.y, message_type.name, blocked_cycles)
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
        is_drop = 'DROP' in header.message_type.name
        queue = self.routers[channel]._input_buffers[Direction.H]
        stuck_count = 0
        while True:
            if queue.can_append():
                word = packet.pop(0)
                queue.append(word)
                self.monitor.report_jamlet_sending(self.x, self.y, channel)
                if is_drop:
                    self.monitor.report_jamlet_dropping(self.x, self.y, channel)
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

        # Record cache message - use slot as tag, include j_in_k_index in src coords
        cache_request_span_id = self.monitor.get_cache_request_span_id(
            self.k_min_x, self.k_min_y, cache_slot)
        self.monitor.record_message_sent(
            cache_request_span_id, header.message_type.name,
            ident=ident, tag=cache_slot,
            src_x=self.x, src_y=self.y,
            dst_x=self.mem_x, dst_y=self.mem_y)

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
            await self.clock.next_cycle
            if queue:
                assert self._instruction_buffer.can_append(), \
                    f"Instruction buffer full at jamlet ({self.x}, {self.y})"
                word = queue.popleft()
                self.monitor.record_input_queue_consumed(self.x, self.y, is_ch0=True)
                self._instruction_buffer.append(word)
                remaining -= 1
                # Record instruction message received only at kamlet origin
                if self.x == self.k_min_x and self.y == self.k_min_y:
                    self.monitor.record_message_received(
                        word.instr_ident,
                        header.source_x, header.source_y,
                        self.x, self.y,
                        message_type='INSTRUCTION')

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
            await self.clock.next_cycle
            if queue:
                word = queue.popleft()
                self.monitor.record_input_queue_consumed(self.x, self.y, is_ch0=True)
                sram_addr = s_address + index * wb
                old_word = self.sram[sram_addr: sram_addr + wb]
                self.sram[sram_addr: sram_addr + wb] = word
                logger.debug(
                    f'{self.clock.cycle}: CACHE_WRITE READ_LINE_RESP: jamlet ({self.x},{self.y}) '
                    f'sram[{sram_addr}] old={old_word.hex()} new={word.hex()}'
                )
                remaining -= 1
                index += 1
        # And we want to let the kamlet know we got this response
        self.cache_table.receive_cache_response(header)

    async def _receive_write_line_resp_packet(self, header, queue):
        assert header.length == 1
        self.cache_table.receive_cache_response(header)

    async def _receive_packet_channel0(self, queue):
        """
        Handle channel 0 packets (always-consumable responses). These never need to send.
        This function should return on the same cycle that the last word was consumed.
        """
        while not queue:
            await self.clock.next_cycle
        header = queue.popleft()
        self.monitor.report_jamlet_receiving(self.x, self.y, channel=0)
        self.monitor.record_input_queue_consumed(self.x, self.y, is_ch0=True)
        assert isinstance(header, Header)
        logger.debug(
            f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): _receive_packet_channel0 got header '
            f'{header.message_type.name} from ({header.source_x}, {header.source_y})')

        # Record message received for all channel 0 messages except INSTRUCTIONS
        if header.message_type != MessageType.INSTRUCTIONS:
            self.monitor.record_message_received_by_header(header, self.x, self.y)

        if header.message_type == MessageType.INSTRUCTIONS:
            await self._receive_instructions_packet(header, queue)
        elif header.message_type == MessageType.READ_LINE_RESP:
            await self._receive_read_line_resp_packet(header, queue)
        elif header.message_type == MessageType.WRITE_LINE_RESP:
            await self.clock.next_cycle
            await self._receive_write_line_resp_packet(header, queue)
        elif header.message_type == MessageType.WRITE_LINE_READ_LINE_RESP:
            await self._receive_read_line_resp_packet(header, queue)
        elif header.message_type == MessageType.WRITE_LINE_READ_LINE_DROP:
            # Memlet couldn't handle request - clear sent flag so kamlet will re-send
            assert isinstance(header, IdentHeader)
            request = self.cache_table.cache_requests[header.ident]
            self.cache_table.clear_cache_request_sent(header.ident, self.j_in_k_index)
        else:
            # All other channel 0 messages are responses tracked via MESSAGE_HANDLERS
            assert isinstance(header, IdentHeader)
            handler = MESSAGE_HANDLERS.get(header.message_type)
            if handler is None:
                raise NotImplementedError(f"No handler for channel 0 message {header.message_type}")
            packet = await self._receive_packet_body(queue, header, channel=0)
            result = handler(self, packet)
            assert result is None, f"Channel 0 handler for {header.message_type} must be sync (not async)"

    async def _receive_packet(self, queue, channel: int):
        """Handle channel 1+ packets (requests that may need to send responses)."""
        while not queue:
            await self.clock.next_cycle
        header = queue.popleft()
        self.monitor.report_jamlet_receiving(self.x, self.y, channel)
        self.monitor.record_input_queue_consumed(self.x, self.y, is_ch0=False)
        assert isinstance(header, IdentHeader)
        logger.debug(
            f'{self.clock.cycle}: jamlet ({self.x}, {self.y}): _receive_packet got header '
            f'{header.message_type.name} from ({header.source_x}, {header.source_y})')

        # Record message received (completes the MESSAGE span for the request)
        self.monitor.record_message_received_by_header(header, self.x, self.y)

        await self.clock.next_cycle
        handler = MESSAGE_HANDLERS.get(header.message_type)
        if handler is None:
            raise NotImplementedError(f"No handler for {header.message_type}")
        packet = await self._receive_packet_body(queue, header, channel=channel)
        await handler(self, packet)

    async def _receive_packet_body(self, queue, header, channel: int):
        packet = [header]
        remaining_words = header.length - 1
        wait_count = 0
        while remaining_words > 0:
            await self.clock.next_cycle
            if queue:
                word = queue.popleft()
                self.monitor.report_jamlet_receiving(self.x, self.y, channel)
                self.monitor.record_input_queue_consumed(self.x, self.y, is_ch0=(channel == 0))
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
                    await self._receive_packet(queue, channel=router_idx)
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
            for witem in list(self.cache_table.waiting_items):
                if witem in self.cache_table.waiting_items:
                    await witem.monitor_jamlet(self)

    async def _record_input_queues(self) -> None:
        """Track when input queues have data ready."""
        ch0_queue = self.routers[0]._output_buffers[Direction.H]
        ch1andup_queues = [r._output_buffers[Direction.H] for r in self.routers[1:]]
        while True:
            await self.clock.next_cycle
            if ch0_queue:
                self.monitor.record_input_queue_ready(self.x, self.y, is_ch0=True)
            if any(q for q in ch1andup_queues):
                self.monitor.record_input_queue_ready(self.x, self.y, is_ch0=False)

    async def run(self):
        for router in self.routers:
            self.clock.create_task(router.run())
        self.clock.create_task(self._send_packets_channel0())
        self.clock.create_task(self._send_packets())
        self.clock.create_task(self._receive_packets_channel0())
        self.clock.create_task(self._receive_packets())
        self.clock.create_task(self._monitor_witems())
        self.clock.create_task(self._monitor_cache_requests())
        self.clock.create_task(self._record_input_queues())

    SEND = 0
    INSTRUCTIONS = 1
