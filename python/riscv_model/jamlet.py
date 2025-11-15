import logging
from typing import Set

import addresses
from params import LamletParams
from addresses import CacheTable
from message import Direction, SendType, MessageType, CHANNEL_MAPPING
from message import Header, IdentHeader, AddressHeader, ValueHeader
from utils import Queue
from router import Router
import kinstructions
import memlet
from cache_table import CacheRequestType


logger = logging.getLogger(__name__)

"""
When jamlet processes a load instruction.

* We work out what packets we need to send.

* As packets arrive we need to apply them to the cache.
  The packet could tell us what mask to apply or we could work it
  out.
  If it's simple packet should tell us.
  If it's complex we should work it out.
  - receive packet
  - get instruction from kamlet
  - work out what shifts and masks to apply
"""


def jamlet_coords_to_frontend_coords(params, x, y):
    return (0, -1)


class Jamlet:
    """
    A single lane of the processor.
    """

    def __init__(self, clock, params: LamletParams, x: int, y: int, cache_table: CacheTable):
        self.clock = clock
        self.params = params
        self.x = x
        self.y = y

        k_x = x//self.params.j_cols
        k_y = x//self.params.j_rows
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

        self.routers = [Router(clock=clock, params=params, x=x, y=y)
                         for _ in range(params.n_channels)]

        # This is just a queue to hand instructions up to kamlet.
        self._instruction_buffer = Queue(2)

        # We have a queue for each type of message that we can send.
        # This is so that we can add multiple messages every cycle
        # without worrying out non-deterministic order of the async
        # functions.
        self.send_queues = {
            MessageType.LOAD_BYTE_RESP: Queue(2),
            MessageType.READ_BYTE_RESP: Queue(2),
            MessageType.WRITE_LINE: Queue(2),
            MessageType.READ_LINE: Queue(2),
            }

        self.cache_table = cache_table

    async def send_packet(self, packet):
        assert isinstance(packet[0], Header)
        message_type = packet[0].message_type
        while not self.send_queues[message_type].can_append():
            await self.clock.next_cycle
        self.send_queues[message_type].append(packet)

    async def _send_packet(self, packet):
        assert isinstance(packet[0], Header)
        assert len(packet) == packet[0].length
        # This is only called from _send_packets
        channel = CHANNEL_MAPPING[packet[0].message_type]
        queue = self.routers[channel]._input_buffers[Direction.H]
        while True:
            if queue.can_append():
                word = packet.pop(0)
                queue.append(word)
                if not packet:
                    await self.clock.next_cycle
                    break
            await self.clock.next_cycle

    async def _send_packets(self):
        """
        Iterate through the send queues and send packets.
        """
        something_in_a_queue = False
        while True:
            for send_queue in self.send_queues.values():
                if send_queue:
                    await self._send_packet(send_queue.popleft())
                something_in_a_queue = any(send_queue for send_queue in self.send_queues.values())
                if not something_in_a_queue:
                    await self.clock.next_cycle

    def has_instruction(self):
        bool(self._instruction_buffer)

    async def handle_read_byte_instr(self, instr: kinstructions.ReadByte, sram_address: int):
        """
        Process a read bytes from SRAM instruction.
        This blocks until the reponse message can be sent.
        """
        logger.debug(f'jamlet ({self.x}, {self.y}) reading byte from sram {hex(sram_address)}')
        value = bytes([self.sram[sram_address]])
        header = ValueHeader(
            message_type=MessageType.READ_BYTE_RESP,
            send_type=SendType.SINGLE,
            value=value,
            target_x=self.front_x,
            target_y=self.front_y,
            source_x=self.x,
            source_y=self.y,
            length=1,
            ident=instr.ident,
            )
        packet = [header]
        send_queue = self.send_queues[header.message_type]
        while not send_queue.can_append():
            await self.clock.next_cycle
        logger.debug(f'jamlet ({self.x}, {self.y}) appending a packet')
        send_queue.append(packet)
        logger.debug(f'jamlet ({self.x}, {self.y}) sent response')

    async def write_cache_line(self, cache_slot: int, address_in_memory: int, response_ident: int):
        """
        Writes this jamlets share of a cache line to memory.
        """
        address_in_sram = cache_slot * self.params.cache_line_bytes // self.params.j_in_k
        n_words = self.params.cache_line_bytes // self.params.j_in_k // self.params.word_bytes
        header = IdentHeader(
            message_type=MessageType.WRITE_LINE_READ_LINE,
            send_type=SendType.SINGLE,
            target_x=self.mem_x,
            target_y=self.mem_y,
            source_x=self.x,
            source_y=self.y,
            length=n_words+2,
            ident=response_ident,
            )
        packet = [header, address_in_memory]
        wb = self.params.word_bytes
        for index in range(n_words):
            word = self.sram[address_in_sram + index * wb: address_in_sram + (index+1) * wb]
            packet.append(word)
        as_int = []
        for word in packet[2:]:
            #as_int += [int(x) for x in word]
            as_int += [int.from_bytes(word[i*4:(i+1)*4], byteorder='little') for i in range(len(word)//4)]
        send_queue = self.send_queues[header.message_type]
        while not send_queue.can_append():
            await self.clock.next_cycle
        send_queue.append(packet)

    #async def read_cache_line_resolve(self, packet):
    #    """
    #    The kamlet sends a read line packet to the memory.
    #    Each jamlet receives a response packet and uses this function to 
    #    handle it.
    #    """
    #    logger.debug('jamlet: read_cache_line_resolve')
    #    # Wait for the response packet from the memory
    #    header = packet[0]
    #    data = packet[1:]
    #    s_address = header.address
    #    assert len(data) == self.params.vlines_in_cache_line
    #    wb = self.params.word_bytes
    #    assert s_address % wb == 0
    #    for index, word in enumerate(data):
    #        self.sram[s_address + index * wb: s_address + (index+1) * wb] = word
    #    as_int = []
    #    for word in data:
    #        as_int += [int(x) for x in word]

    async def send_load_byte_resp(self, instr: kinstructions.LoadByte):
        slot = self.cache_table.get_state(instr.src)
        assert slot is not None
        src_offset_in_word = instr.src.addr % self.params.word_bytes
        byt = self.sram[slot * self.params.word_bytes + src_offset_in_word]
        dst_vw_index = instr.dst.vw_index
        dst_x, dst_y = addresses.vw_index_to_j_coords(
                self.params, instr.dst.ordering.word_order, dst_vw_index)
        header = ValueHeader(
            target_x=dst_x,
            target_y=dst_y,
            source_x=self.x,
            source_y=self.y,
            length=1,
            message_type=MessageType.LOAD_BYTE_RESP,
            send_type=SendType.SINGLE,
            ident=instr.ident,
            value=byt,
            )
        packet = [header]
        await self.send_packet(packet)

    async def handle_load_byte_instr(self, instr: kinstructions.LoadByte):
        is_dst = instr.dst.k_index == self.k_index and instr.dst.j_in_k_index == self.j_in_k_index
        is_src = instr.src.k_index == self.k_index and instr.src.j_in_k_index == self.j_in_k_index
        slot = self.cache_table.get_state(instr.src)
        if is_src and is_dst and slot is not None:
            # The src and dst are the same jamlet and the data is in cache.
            # This is just a local move from sram to reg.
            src_offset_in_word = instr.src.addr % self.params.word_bytes
            self.rf_slice[instr.dst.reg * self.params.word_bytes + instr.dst.offset_in_word] = self.sram[slot][src_offset_in_word]
        else:
            if is_src:
                if slot is not None:
                    await self.send_load_byte_resp(instr)
                else:
                    # We need to load it into cache and then send a response.
                    pass
            if is_dst:
                # We're waiting to receive a LOAD_BYTE_RESP packet.
                # Generate the transformations to apply when we receive them.
                pass
        raise NotImplementedError()

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
        logger.warning('Got a read line resp packet')
        # The packet should say where to put the data.
        # It only needs the 'slot' which should fit fine in the packet.
        remaining = header.length - 1
        wb = self.params.word_bytes
        s_address = header.address
        assert s_address % wb == 0
        assert remaining == self.params.vlines_in_cache_line
        index = 0
        while remaining:
            if queue:
                word = queue.popleft()
                self.sram[s_address + index * wb: s_address + (index+1) * wb] = word
                remaining -= 1
                index += 1
            await self.clock.next_cycle
        # And we want to let the kamlet know we got this response
        self.cache_table.receive_cache_response(header)

    async def _receive_write_line_resp_packet(self, header, queue):
        assert header.length == 1
        self.cache_table.receive_cache_response(header)

    async def _receive_packet(self, queue):
        while not queue:
            await self.clock.next_cycle
        header = queue.popleft()
        assert isinstance(header, Header)
        await self.clock.next_cycle
        if header.message_type == MessageType.INSTRUCTIONS:
            await self._receive_instructions_packet(header, queue)
        elif header.message_type == MessageType.READ_LINE_RESP:
            await self._receive_read_line_resp_packet(header, queue)
        elif header.message_type == MessageType.WRITE_LINE_RESP:
            await self._receive_write_line_resp_packet(header, queue)
        else:
            raise NotImplementedError

    async def _receive_packets(self):
        while True:
            await self.clock.next_cycle
            for router in self.routers:
                queue = router._output_buffers[Direction.H]
                if queue:
                    await self._receive_packet(queue)
                else:
                    #logger.debug(f'{self.clock.cycle}: jamlet({self.x}, {self.y}): No input queue')
                    pass

    async def _monitor_cache_requests(self):
        while True:
            await self.clock.next_cycle
            for request in self.cache_table.cache_requests:
                if request is None:
                    continue
                if not all(request.sent):
                    if request.request_type == CacheRequestType.WRITE_LINE_READ_LINE:
                        await self.read_cache_line(cache_slot=request.slot, address_in_memory=request.k_maddr, ident=request.ident)
                        assert len(request.sent) == 1
                        request.sent[0].set(True)
                    else:
                        # Don't do anything for READ_LINE
                        # since those messages are sent at the kamlet level
                        pass

    async def run(self):
        for router in self.routers:
            self.clock.create_task(router.run())
        self.clock.create_task(self._send_packets())
        self.clock.create_task(self._receive_packets())

    SEND = 0
    INSTRUCTIONS = 1


