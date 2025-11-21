import logging
from typing import Set, List, Any, Tuple

import addresses
from params import LamletParams
from cache_table import CacheTable, LoadSrcState, LoadDstState
from message import Direction, SendType, MessageType, CHANNEL_MAPPING
from message import Header, IdentHeader, AddressHeader, ValueHeader, TaggedHeader
from utils import Queue
from router import Router
import kinstructions
import memlet
import utils
import ew_convert
import cache_table
from cache_table import CacheRequestType, WaitingItem, CacheState
from register_file_slot import KamletRegisterFile


logger = logging.getLogger(__name__)


def jamlet_coords_to_frontend_coords(params, x, y):
    return (0, -1)


class Jamlet:
    """
    A single lane of the processor.
    """

    def __init__(self, clock, params: LamletParams, x: int, y: int, cache_table: CacheTable,
                 rf_info: KamletRegisterFile):
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
            #MessageType.WRITE_LINE: Queue(2),
            MessageType.READ_LINE: Queue(2),
            MessageType.WRITE_LINE_READ_LINE: Queue(2),
            MessageType.LOAD_J2J_WORDS_REQ: Queue(2),
            MessageType.LOAD_J2J_WORDS_RESP: Queue(2),
            MessageType.LOAD_J2J_WORDS_DROP: Queue(2),
            MessageType.STORE_J2J_WORDS_REQ: Queue(2),
            MessageType.STORE_J2J_WORDS_RESP: Queue(2),
            MessageType.STORE_J2J_WORDS_DROP: Queue(2),
            MessageType.LOAD_WORD_REQ: Queue(2),
            MessageType.LOAD_WORD_RESP: Queue(2),
            MessageType.LOAD_WORD_DROP: Queue(2),
            MessageType.LOAD_WORD_RETRY: Queue(2),
            }

        self.cache_table = cache_table
        self.rf_info = rf_info

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
        return bool(self._instruction_buffer)

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

    async def write_read_cache_line(self, cache_slot: int, address_in_memory: int, ident: int):
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
            ident=ident,
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

    async def send_load_byte_resp(self, instr: kinstructions.LoadByte):
        slot = self.cache_table.get_state(instr.src)
        assert slot is not None
        src_offset_in_word = instr.src.addr % self.params.word_bytes
        cache_line_bytes_per_jamlet = self.params.cache_line_bytes // self.params.j_in_k
        byt = self.sram[slot * cache_line_bytes_per_jamlet + src_offset_in_word]
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
            cache_line_bytes_per_jamlet = self.params.cache_line_bytes // self.params.j_in_k
            self.rf_slice[instr.dst.reg * self.params.word_bytes + instr.dst.offset_in_word] = self.sram[slot * cache_line_bytes_per_jamlet + src_offset_in_word]
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
        elif header.message_type == MessageType.LOAD_J2J_WORDS_REQ:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_load_j2j_words_req(packet)
        elif header.message_type == MessageType.LOAD_J2J_WORDS_RESP:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_load_j2j_words_resp(packet)
        elif header.message_type == MessageType.LOAD_J2J_WORDS_DROP:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_load_j2j_words_drop(packet)
        elif header.message_type == MessageType.STORE_J2J_WORDS_REQ:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_store_j2j_words_req(packet)
        elif header.message_type == MessageType.STORE_J2J_WORDS_RESP:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_store_j2j_words_resp(packet)
        elif header.message_type == MessageType.STORE_J2J_WORDS_DROP:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_store_j2j_words_drop(packet)
        elif header.message_type == MessageType.LOAD_WORD_REQ:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_load_word_req(packet)
        elif header.message_type == MessageType.LOAD_WORD_RESP:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_load_word_resp(packet)
        elif header.message_type == MessageType.LOAD_WORD_DROP:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_load_word_drop(packet)
        elif header.message_type == MessageType.LOAD_WORD_RETRY:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_load_word_retry(packet)
        else:
            raise NotImplementedError

    async def _receive_packet_body(self, queue, header):
        packet = [header]
        remaining_words = header.length - 1
        while remaining_words > 0:
            if queue:
                word = queue.popleft()
                packet.append(word)
                remaining_words -= 1
            await self.clock.next_cycle
        return packet

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
                        await self.write_read_cache_line(cache_slot=request.slot, address_in_memory=request.k_maddr, ident=request.ident)
                        assert len(request.sent) == 1
                        request.sent[0].set(True)
                    else:
                        # Don't do anything for READ_LINE
                        # since those messages are sent at the kamlet level
                        pass


    ###########################################################
    #
    #  STORE
    #  Various functions that deal with processing the vector store.
    #  using jamlet-to-jamlet message passing
    #
    ############################################################

    def handle_store_instr_simple(self, instr: kinstructions.Store):
        """
        This is called when we are processing a Store instructions which is aligned to
        local kamlet memory, and the data is in the cache.
        """
        #TODO: Pretty much the same has handle_load_instr_simple
        # Should work out how to combine.
        assert self.cache_table.can_read(instr.k_maddr)
        slot = self.cache_table.addr_to_slot(instr.k_maddr)
        # But we need to check which elements we want to write
        # What are the elements in this word.
        dst_ordering = instr.k_maddr.ordering
        src_ordering = instr.src_ordering
        ew = src_ordering.ew
        assert ew == dst_ordering.ew
        vw_index = addresses.j_coords_to_vw_index(
                self.params, src_ordering.word_order, self.x, self.y)
        # We contain vw_index, vw_index+self.j_in_l, vw_index+2*self.j_in_l
        # The total number is ww/dst_ew per word
        start_addr_bit = instr.k_maddr.bit_addr
        assert start_addr_bit % 8 == 0

        j_in_l = self.params.j_in_l
        ww = self.params.word_bytes * 8
        vw = self.params.vline_bytes * 8

        start_eb, start_vw, start_we, start_v = ew_convert.split_by_factors(
                start_addr_bit, [ew, j_in_l, ww//ew])
        final_addr_bit = start_addr_bit + instr.n_elements * ew - 1
        final_eb, final_vw, final_we, final_v = ew_convert.split_by_factors(
                final_addr_bit, [ew, j_in_l, ww//ew])

        start_ve = ew_convert.join_by_factors([start_we, start_vw], [ww//ew, vw//ww])
        assert instr.start_index == start_ve

        # It should all be in a single cache line
        start_c = start_v//self.params.vlines_in_cache_line
        final_c = final_v//self.params.vlines_in_cache_line
        assert start_c == final_c

        base_v = (start_addr_bit - instr.start_index * ew)//vw

        if instr.mask_reg is not None:
            mask_addr = instr.mask_reg * (ww//8)
            mask_word = self.rf_slice[mask_addr: mask_addr + ww//8]
            mask_word_int = int.from_bytes(mask_word, byteorder='little')
            mask_bits = utils.uint_to_list_of_uints(mask_word_int, width=1, size=ww)
            el_mask = [0] * (ww//ew)
            el_mask[0: final_v-start_v+1] = mask_bits[start_v-base_v: final_v-base_v+1]
        else:
            el_mask = [1] * (ww//ew)

        masks = []
        for v_index in range(start_v, final_v+1):
            el_mask_bits = []
            for word_element in range(0, ww//ew):
                element_index = (start_v - base_v) * vw//ew + word_element * j_in_l + vw_index
                in_range = instr.start_index <= element_index < instr.start_index + instr.n_elements
                if instr.mask_reg is None:
                    mask_bit = 1
                else:
                    mask_bit = el_mask[element_index//j_in_l]

                el_mask_bits += [mask_bit and in_range] * ew
            masks.append(utils.list_of_uints_to_uint(el_mask_bits, width=1))

        cache_base_v = start_c * self.params.vlines_in_cache_line
        cache_line_bytes_per_jamlet = self.params.cache_line_bytes // self.params.j_in_k
        for mask, v_index in zip(masks, range(start_v, final_v+1)):
            rf_word_addr = instr.src + start_v - base_v
            word = self.rf_slice[rf_word_addr * ww//8: (rf_word_addr+1) * ww//8]
            word_as_int = int.from_bytes(word, byteorder='little')
            sram_addr = slot * cache_line_bytes_per_jamlet + (v_index - cache_base_v) * ww//8
            old_word = self.sram[sram_addr: sram_addr + ww//8]
            old_word_as_int = int.from_bytes(old_word, byteorder='little')
            new_word = (old_word_as_int & ~mask) | (word_as_int & mask)
            new_word_bytes = new_word.to_bytes(ww//8, byteorder='little')
            self.sram[sram_addr: sram_addr + ww//8] = new_word_bytes
            logger.info(f'STORE_SIMPLE: jamlet ({self.x},{self.y}): wrote to sram[{sram_addr}] bytes={new_word_bytes.hex()} mask=0x{mask:016x} rf_word_addr={rf_word_addr} word_from_rf={word.hex()}')

    def init_store_j2j_words_dst_state(
            self, witem: cache_table.WaitingStoreJ2JWords, tag: int) -> None:
        '''
        Initialize the dst_state for a given tag by checking if we will receive
        data for this tag. If not, mark it complete immediately.
        '''
        instr = witem.item
        src_ordering = instr.src_ordering
        dst_ordering = instr.k_maddr.ordering
        src_ew = src_ordering.ew
        dst_ew = dst_ordering.ew
        logical_addr = instr.k_maddr.to_logical_vline_addr()
        start_logical_addr = logical_addr.offset_bits(-instr.start_index * dst_ew)
        dst_offset = start_logical_addr.bit_addr

        dst_vw_index = addresses.j_coords_to_vw_index(
                self.params, dst_ordering.word_order, self.x, self.y)

        mapping = ew_convert.get_mapping_for_dst(
                params=self.params, src_ew=src_ew, dst_ew=dst_ew,
                dst_v=0, dst_vw=dst_vw_index, dst_tag=tag, dst_offset=dst_offset)

        response_tag = self.j_in_k_index * instr.n_tags() + tag
        if mapping is None:
            witem.protocol_states[response_tag].dst_state = cache_table.StoreDstState.COMPLETE
        else:
            vline_offsets = self.get_vline_offsets(
                    dst_ew, mapping.dst_ve, instr.start_index, instr.n_elements)
            if not vline_offsets:
                witem.protocol_states[response_tag].dst_state = cache_table.StoreDstState.COMPLETE

    async def send_store_j2j_words_req(
            self, witem: cache_table.WaitingStoreJ2JWords, tag: int, assert_sends: bool) -> None:
        '''
        Reads data from the local reg and send it to a remote jamlet to store it.

        item_index: The index of the WaitingItem corresponding to the Store kinstruction.
        tag: Identifies a particular segment in this word that needs to be sent to a particular
               other jamlet.  We can iteration through tags to send all the required data.
        asserts_sends: This tag should correspond to data that needs to be sent. Asserted when
                       we're resending a dropped packet just as a check.
        '''
        instr = witem.item
        src_ordering = instr.src_ordering
        dst_ordering = instr.k_maddr.ordering
        src_ew = src_ordering.ew
        dst_ew = dst_ordering.ew
        response_tag = self.j_in_k_index * instr.n_tags() + tag
        vw_index = addresses.j_coords_to_vw_index(
                self.params, instr.src_ordering.word_order, self.x, self.y)
        logical_addr = instr.k_maddr.to_logical_vline_addr()
        start_logical_addr = logical_addr.offset_bits(-instr.start_index * src_ew)
        offset = start_logical_addr.bit_addr
        mapping = ew_convert.get_mapping_for_src(
                params=self.params, src_ew=src_ew, dst_ew=dst_ew,
                dst_offset=offset, src_v=0, src_vw=vw_index, src_tag=tag)

        if mapping is None:
            vline_offsets = []
        else:
            vline_offsets = self.get_vline_offsets(
                    dst_ve=mapping.dst_ve, dst_ew=dst_ew,
                    start_index=instr.start_index, n_elements=instr.n_elements)

        if not vline_offsets:
            assert not assert_sends
            witem.protocol_states[response_tag].src_state = cache_table.StoreSrcState.COMPLETE
            return
        witem.protocol_states[response_tag].src_state = cache_table.StoreSrcState.WAITING_FOR_RESPONSE

        target_x, target_y = addresses.vw_index_to_j_coords(
                self.params, dst_ordering.word_order, mapping.dst_vw)
        logger.debug(f'jamlet ({self.x}, {self.y}): send_store_j2j_words_req tag={tag} -> ({target_x}, {target_y})')

        word_bytes = self.params.word_bytes
        words = [self.rf_slice[(instr.src+index)*word_bytes: (instr.src+index+1)*word_bytes]
                 for index in vline_offsets]

        # We need to send data that is masked out still, because we need to tell the receiver
        # that the data is masked out.
        # TODO: Send shorter data when it is masked out.

        if instr.mask_reg is not None:
            mask_word = self.rf_slice[instr.mask_reg * word_bytes: (instr.mask_reg+1) * word_bytes]
            mask_word_int = int.from_bytes(mask_word, byteorder='little')
            mask_bits = []
            for index in vline_offsets:
                vector_element = mapping.src_ve + index * self.params.vline_bytes*8//src_ew
                word_element = vector_element//self.params.j_in_l
                mask_bits.append((mask_word_int >> word_element) & 1)
        else:
            mask_bits = [1] * len(words)
        mask_bits_as_int = utils.list_of_uints_to_uint(mask_bits, width=1)

        header = TaggedHeader(
            target_x=target_x,
            target_y=target_y,
            source_x=self.x,
            source_y=self.y,
            length=1 + len(words),
            message_type=MessageType.STORE_J2J_WORDS_REQ,
            send_type=SendType.SINGLE,
            ident=instr.instr_ident,
            tag=mapping.dst_tag,
            mask=mask_bits_as_int,
            )

        packet = [header] + words

        await self.send_packet(packet)

    async def handle_store_j2j_words_req(self, packet: List[Any]) -> None:
        """
        Handle a jamlet-to-jamlet request to store a word.
        If it can't immediately handle this message it must send a drop response.

        If the instruction uses a mask it is (header, mask, word) otherwise just
        (header, word)

        It should all be in one cache-line
        """
        header = packet[0]
        words = packet[1:]
        assert isinstance(header, TaggedHeader)
        assert header.message_type == MessageType.STORE_J2J_WORDS_REQ

        # We got a request to store some data.
        # Let's check to see if we have a waiting item for this.
        witem = self.cache_table.get_waiting_item_by_instr_ident(header.ident)
        if witem is None:
            # We not expected this message.
            # Presumably we haven't processed that instruction yet.
            # Drop the packet.
            logger.debug(f'jamlet ({self.x}, {self.y}): handle_store_j2j_words_req from ({header.source_x}, {header.source_y}) tag={header.tag} ident={header.ident} - no witem, dropping')
            await self.send_store_j2j_words_drop(header)
            return
        logger.debug(f'jamlet ({self.x}, {self.y}): handle_store_j2j_words_req from ({header.source_x}, {header.source_y}) tag={header.tag} ident={header.ident}')
        assert isinstance(witem, cache_table.WaitingStoreJ2JWords)
        slot = witem.cache_slot
        assert slot is not None
        instr = witem.item
        assert isinstance(instr, kinstructions.Store)

        src_ew = instr.src_ordering.ew
        dst_ew = instr.k_maddr.ordering.ew
        src_vw_index = addresses.j_coords_to_vw_index(
                self.params, instr.src_ordering.word_order, header.source_x, header.source_y)
        mapping = ew_convert.get_mapping_for_src(
                params=self.params, src_ew=src_ew, dst_ew=dst_ew,
                src_v=0, src_vw=src_vw_index, src_tag=header.tag)
        assert mapping is not None
        dst_tag = mapping.dst_tag
        response_tag = self.j_in_k_index * instr.n_tags() + dst_tag

        if self.cache_table.can_write(instr.k_maddr, witem=witem):
            assert witem.cache_is_avail
            # Workout how much we need to shift the word.
            shift = mapping.src_wb - mapping.dst_wb
            # Work out what mask to apply
            segment_mask = ((1 << mapping.n_bits)-1) << mapping.dst_wb

            vline_offsets = self.get_vline_offsets(
                    dst_ew=dst_ew, dst_ve=mapping.dst_ve,
                    start_index=instr.start_index, n_elements=instr.n_elements)

            v_in_c = self.params.vlines_in_cache_line
            word_bytes = self.params.word_bytes
            cache_base_addr = slot * v_in_c * word_bytes

            for word_index, (vline_offset, word) in enumerate(zip(vline_offsets, words)):
                mask_bit = (header.mask >> word_index) & 1
                word_as_int = int.from_bytes(word, byteorder='little')
                if shift > 0:
                    shifted = word_as_int >> shift
                else:
                    shifted = word_as_int << (-shift)
                if mask_bit:
                    cache_addr = cache_base_addr + vline_offset * word_bytes
                    old_word = self.sram[cache_addr: cache_addr + word_bytes]
                    old_word_as_int = int.from_bytes(old_word, byteorder='little')
                    old_word_masked = old_word_as_int & (~segment_mask)
                    new_word = old_word_masked | shifted
                    new_word_bytes = new_word.to_bytes(word_bytes, byteorder='little')
                    self.sram[cache_addr: cache_addr + word_bytes] = new_word_bytes
                    logger.info(f'STORE_J2J: jamlet ({self.x},{self.y}): wrote to sram[{cache_addr}] bytes={new_word_bytes.hex()} (shifted from {word.hex()})')
            witem.protocol_states[response_tag].dst_state = cache_table.StoreDstState.COMPLETE
            cache_state = self.cache_table.slot_states[slot]
            assert cache_state.state in (CacheState.SHARED, CacheState.MODIFIED)
            cache_state.state = CacheState.MODIFIED
            logger.debug(f'jamlet ({self.x}, {self.y}): handle_store_j2j_words_req - wrote to cache, sending resp')
            await self.send_store_j2j_words_resp(header)
        else:
            # We can't write to the cache table.
            # When the cache is made available we'll send a Retry message back.
            witem.protocol_states[response_tag].dst_state = (
                    cache_table.StoreDstState.NEED_TO_ASK_FOR_RESEND)
            assert not witem.cache_is_avail
            logger.debug(f'jamlet ({self.x}, {self.y}): handle_store_j2j_words_req - can\'t write, waiting for cache')

    async def handle_store_j2j_words_drop(self, packet: List[Any]) -> None:
        '''
        The src jamlet runs when the dst jamlet sends a drop message.
        '''
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        assert header.message_type == MessageType.STORE_J2J_WORDS_DROP
        assert len(packet) == 1
        witem = self.cache_table.get_waiting_item_by_instr_ident(header.ident)
        assert isinstance(witem, cache_table.WaitingStoreJ2JWords)
        instr = witem.item
        response_tag = self.j_in_k_index * instr.n_tags() + header.tag
        assert witem.protocol_states[response_tag].src_state == cache_table.StoreSrcState.WAITING_FOR_RESPONSE
        witem.protocol_states[response_tag].src_state = cache_table.StoreSrcState.NEED_TO_SEND

    async def handle_store_j2j_words_resp(self, packet: List[Any]) -> None:
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        assert header.message_type == MessageType.STORE_J2J_WORDS_RESP
        assert len(packet) == 1
        witem = self.cache_table.get_waiting_item_by_instr_ident(header.ident)
        assert isinstance(witem, cache_table.WaitingStoreJ2JWords)
        instr = witem.item
        response_tag = self.j_in_k_index * instr.n_tags() + header.tag
        logger.debug(f'jamlet ({self.x}, {self.y}): handle_store_j2j_words_resp from ({header.source_x}, {header.source_y}) tag={header.tag} ident={header.ident}')
        assert witem.protocol_states[response_tag].src_state == cache_table.StoreSrcState.WAITING_FOR_RESPONSE
        witem.protocol_states[response_tag].src_state = cache_table.StoreSrcState.COMPLETE

    async def handle_store_j2j_words_retry(self, packet: List[Any]) -> None:
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        assert header.message_type == MessageType.STORE_J2J_WORDS_RETRY
        assert len(packet) == 1
        witem = self.cache_table.get_waiting_item_by_instr_ident(header.ident)
        assert isinstance(witem, cache_table.WaitingStoreJ2JWords)
        instr = witem.item
        response_tag = self.j_in_k_index * instr.n_tags() + header.tag
        assert witem.protocol_states[response_tag].src_state == cache_table.StoreSrcState.WAITING_FOR_RESPONSE
        witem.protocol_states[response_tag].src_state = cache_table.StoreSrcState.NEED_TO_SEND

    async def send_store_j2j_words_drop(self, rcvd_header: TaggedHeader):
        header = TaggedHeader(
            target_x=rcvd_header.source_x,
            target_y=rcvd_header.source_y,
            source_x=self.x,
            source_y=self.y,
            send_type=SendType.SINGLE,
            message_type=MessageType.STORE_J2J_WORDS_DROP,
            length=1,
            ident=rcvd_header.ident,
            tag=rcvd_header.tag,
            )
        packet = [header]
        await self.send_packet(packet)

    async def send_store_j2j_words_resp(self, rcvd_header: TaggedHeader):
        # Send the response
        header = TaggedHeader(
            target_x=rcvd_header.source_x,
            target_y=rcvd_header.source_y,
            source_x=self.x,
            source_y=self.y,
            send_type=SendType.SINGLE,
            message_type=MessageType.STORE_J2J_WORDS_RESP,
            length=1,
            ident=rcvd_header.ident,
            tag=rcvd_header.tag,
            )
        packet = [header]
        await self.send_packet(packet)

    async def send_store_j2j_words_retry(
            self, item: cache_table.WaitingStoreJ2JWords, tag: int) -> None:
        '''
        Sends a messages to the src asking for it to send the packet again.
        The dst is now ready to receive it.
        '''
        assert item.instr_ident is not None
        instr = item.item
        assert isinstance(instr, kinstructions.Store)

        src_ew = instr.src_ordering.ew
        dst_ew = instr.k_maddr.ordering.ew
        vw_index = addresses.j_coords_to_vw_index(
                self.params, instr.src_ordering.word_order, self.x, self.y)
        logical_addr = instr.k_maddr.to_logical_vline_addr()
        start_logical_addr = logical_addr.offset_bits(-instr.start_index * src_ew)
        dst_offset = start_logical_addr.bit_addr

        mapping = ew_convert.get_mapping_for_dst(
                params=self.params, src_ew=src_ew, dst_ew=dst_ew,
                dst_offset=dst_offset, dst_v=0, dst_vw=vw_index, dst_tag=tag)
        assert mapping is not None
        target_x, target_y = addresses.vw_index_to_j_coords(
                self.params, instr.k_maddr.ordering.word_order, mapping.src_vw)

        header = TaggedHeader(
            target_x=target_x,
            target_y=target_y,
            source_x=self.x,
            source_y=self.y,
            send_type=SendType.SINGLE,
            message_type=MessageType.STORE_J2J_WORDS_RETRY,
            length=1,
            ident=item.instr_ident,
            tag=tag,
            )
        packet = [header]
        await self.send_packet(packet)


    ###########################################################
    #
    #  LOAD
    #  Various functions that deal with processing the vector load.
    #  using jamlet-to-jamlet message passing
    #
    ############################################################

    def handle_load_instr_simple(self, instr: kinstructions.Load):
        """
        This is called when we are processing a Load instructions which is aligned to
        local kamlet memory, and the data is in the cache.
        """
        assert self.cache_table.can_read(instr.k_maddr)
        slot = self.cache_table.addr_to_slot(instr.k_maddr)
        # But we need to check which elements we want to write
        # What are the elements in this word.
        src_ordering = instr.k_maddr.ordering
        dst_ordering = instr.dst_ordering
        ew = src_ordering.ew
        assert ew == dst_ordering.ew
        vw_index = addresses.j_coords_to_vw_index(
                self.params, instr.dst_ordering.word_order, self.x, self.y)
        # We contain vw_index, vw_index+self.j_in_l, vw_index+2*self.j_in_l
        # The total number is ww/dst_ew per word
        start_addr_bit = instr.k_maddr.bit_addr
        assert start_addr_bit % 8 == 0

        j_in_l = self.params.j_in_l
        ww = self.params.word_bytes * 8
        vw = self.params.vline_bytes * 8

        start_eb, start_vw, start_we, start_v = ew_convert.split_by_factors(
                start_addr_bit, [ew, j_in_l, ww//ew])
        final_addr_bit = start_addr_bit + instr.n_elements * ew - 1
        final_eb, final_vw, final_we, final_v = ew_convert.split_by_factors(
                final_addr_bit, [ew, j_in_l, ww//ew])

        start_ve = ew_convert.join_by_factors([start_we, start_vw], [ww//ew, vw//ww])
        assert instr.start_index == start_ve

        # It should all be in a single cache line
        start_c = start_v//self.params.vlines_in_cache_line
        final_c = final_v//self.params.vlines_in_cache_line
        assert start_c == final_c

        base_v = (start_addr_bit - instr.start_index * ew)//vw

        if instr.mask_reg is not None:
            mask_addr = instr.mask_reg * (ww//8)
            mask_word = self.rf_slice[mask_addr: mask_addr + ww//8]
            mask_word_int = int.from_bytes(mask_word, byteorder='little')
            mask_bits = utils.uint_to_list_of_uints(mask_word_int, width=1, size=ww)
            el_mask = [0] * (ww//ew)
            el_mask[0: final_v-start_v+1] = mask_bits[start_v-base_v: final_v-base_v+1]
        else:
            el_mask = [1] * (ww//ew)

        masks = []
        for v_index in range(start_v, final_v+1):
            el_mask_bits = []
            for word_element in range(0, ww//ew):
                element_index = (start_v - base_v) * vw//ew + word_element * j_in_l + vw_index
                in_range = instr.start_index <= element_index < instr.start_index + instr.n_elements
                if instr.mask_reg is None:
                    mask_bit = 1
                else:
                    mask_bit = el_mask[element_index//j_in_l]

                el_mask_bits += [mask_bit and in_range] * ew
            masks.append(utils.list_of_uints_to_uint(el_mask_bits, width=1))

        logger.debug(f'{self.clock.cycle}: jamlet {(self.x, self.y)}: Running the vector load')
        cache_base_v = start_c * self.params.vlines_in_cache_line
        cache_line_bytes_per_jamlet = self.params.cache_line_bytes // self.params.j_in_k
        for mask, v_index in zip(masks, range(start_v, final_v+1)):
            sram_addr = slot * cache_line_bytes_per_jamlet + (v_index - cache_base_v) * ww//8
            word = self.sram[sram_addr: sram_addr + ww//8]
            word_as_int = int.from_bytes(word, byteorder='little')
            masked = word_as_int & mask
            masked_as_bytes = masked.to_bytes(ww//8, byteorder='little')
            rf_word_addr = instr.dst + start_v - base_v
            logger.debug(f'{self.clock.cycle}: jamlet {(self.x, self.y)}: Loading {[int(x) for x in masked_as_bytes]}')
            logger.warning(f'{self.clock.cycle}: LOAD: jamlet ({self.x},{self.y}): vw_index={vw_index}, reg={instr.dst}, rf_word_addr={rf_word_addr}, bytes={masked_as_bytes.hex()}, start_v={start_v}, base_v={base_v}')
            self.rf_slice[rf_word_addr * ww//8: (rf_word_addr+1) * ww//8] = masked_as_bytes

    async def send_load_j2j_words_req(
            self, witem: cache_table.WaitingLoadJ2JWords, tag: int, assert_sends: bool) -> None:
        '''
        This runs on a jamlet when the cache is ready.
        It reads the cache and sends the a LOAD_J2J_WORDS message with the data to the dst jamlet.
        '''
        instr = witem.item
        src_ordering = instr.k_maddr.ordering
        dst_ordering = instr.dst_ordering
        src_ew = src_ordering.ew
        dst_ew = dst_ordering.ew
        vw_index = addresses.j_coords_to_vw_index(
                self.params, instr.dst_ordering.word_order, self.x, self.y)
        logical_addr = instr.k_maddr.to_logical_vline_addr()
        start_logical_addr = logical_addr.offset_bits(-instr.start_index * src_ew)
        offset = start_logical_addr.bit_addr

        logger.info(f'jamlet ({self.x}, {self.y}): send_load_j2j_words_req tag={tag} '
                    f'k_maddr.bit_addr={instr.k_maddr.bit_addr} ({instr.k_maddr.bit_addr//8} bytes) '
                    f'vw_index={vw_index} offset={offset} bits ({offset//8} bytes) '
                    f'logical_addr.index={logical_addr.index} logical_addr.bit_addr={logical_addr.bit_addr} '
                    f'start_index={instr.start_index} start_logical_addr.index={start_logical_addr.index}')

        mapping = ew_convert.get_mapping_for_src(
            params=self.params, src_ew=src_ew, dst_ew=dst_ew,
            src_offset=offset, src_v=0, src_vw=vw_index, src_tag=tag)

        logger.info(f'jamlet ({self.x}, {self.y}): send_load_j2j_words_req tag={tag} '
                    f'mapping={mapping}')

        if mapping is None:
            vline_offsets = []
        else:
            vline_offsets = self.get_vline_offsets(
                    dst_ve=mapping.dst_ve, dst_ew=dst_ew,
                    start_index=instr.start_index, n_elements=instr.n_elements)

        logger.info(f'jamlet ({self.x}, {self.y}): send_load_j2j_words_req tag={tag} '
                    f'vline_offsets={vline_offsets}')

        word_bytes = self.params.word_bytes
        assert witem.cache_slot is not None
        words = []

        kamlet_vline_bytes = self.params.vline_bytes // self.params.k_in_l
        base_vline_in_cache = (instr.k_maddr.addr % self.params.cache_line_bytes) // kamlet_vline_bytes
        logger.warning(f'jamlet ({self.x}, {self.y}): k_maddr.addr={instr.k_maddr.addr} (0x{instr.k_maddr.addr:x}), '
                      f'cache_line_bytes={self.params.cache_line_bytes}, kamlet_vline_bytes={kamlet_vline_bytes}, '
                      f'base_vline_in_cache={base_vline_in_cache}, cache_slot={witem.cache_slot}')

        for vline_offset in vline_offsets:
            cache_base_addr = witem.cache_slot * self.params.vlines_in_cache_line * word_bytes
            cache_addr = cache_base_addr + (base_vline_in_cache + vline_offset) * word_bytes
            logger.warning(f'jamlet ({self.x}, {self.y}): vline_offset={vline_offset}, cache_addr={cache_addr} (0x{cache_addr:x})')
            words.append(self.sram[cache_addr: cache_addr + word_bytes])

        response_tag = self.j_in_k_index * instr.n_tags() + tag
        if not vline_offsets:
            assert not assert_sends
            witem.protocol_states[response_tag].src_state = LoadSrcState.COMPLETE
            return

        target_x, target_y = addresses.vw_index_to_j_coords(
                self.params, dst_ordering.word_order, mapping.dst_vw)
        logger.debug(f'jamlet ({self.x}, {self.y}): send_load_j2j_words_req tag={tag} -> ({target_x}, {target_y})')
        witem.protocol_states[response_tag].src_state = LoadSrcState.WAITING_FOR_RESPONSE

        header = TaggedHeader(
            target_x=target_x,
            target_y=target_y,
            source_x=self.x,
            source_y=self.y,
            length=1 + len(words),
            message_type=MessageType.LOAD_J2J_WORDS_REQ,
            send_type=SendType.SINGLE,
            ident=instr.instr_ident,
            tag=tag,
            )
        packet = [header] + words
        await self.send_packet(packet)

    def init_load_j2j_words_dst_state(
            self, witem: cache_table.WaitingLoadJ2JWords, tag: int) -> None:
        '''
        Initialize the dst_state for a given tag by checking if we will receive
        data for this tag. If not, mark it complete immediately.
        '''
        instr = witem.item
        src_ordering = instr.k_maddr.ordering
        dst_ordering = instr.dst_ordering
        src_ew = src_ordering.ew
        dst_ew = dst_ordering.ew
        logical_addr = instr.k_maddr.to_logical_vline_addr()
        start_logical_addr = logical_addr.offset_bits(-instr.start_index * src_ew)
        offset = start_logical_addr.bit_addr

        dst_vw_index = addresses.j_coords_to_vw_index(
                self.params, dst_ordering.word_order, self.x, self.y)

        mapping = ew_convert.get_mapping_for_dst(
                params=self.params, src_ew=src_ew, dst_ew=dst_ew,
                dst_v=0, dst_vw=dst_vw_index, dst_tag=tag, src_offset=offset)

        response_tag = self.j_in_k_index * instr.n_tags() + tag
        if mapping is None:
            witem.protocol_states[response_tag].dst_state = LoadDstState.COMPLETE
        else:
            vline_offsets = self.get_vline_offsets(
                    dst_ew, mapping.dst_ve, instr.start_index, instr.n_elements)
            if not vline_offsets:
                witem.protocol_states[response_tag].dst_state = LoadDstState.COMPLETE

    def init_load_word_src_state(self, witem: cache_table.WaitingLoadWordSrc):
        """Initialize protocol state for SRC jamlet."""
        instr = witem.item
        is_src = (instr.src.k_index == self.k_index and
                  instr.src.j_in_k_index == self.j_in_k_index)
        if is_src:
            logger.warning(f'{self.clock.cycle}: jamlet {(self.x, self.y)}: setting j_in_k={self.j_in_k_index} to NEED_TO_SEND')
            witem.protocol_states[self.j_in_k_index] = LoadSrcState.NEED_TO_SEND

    def init_load_word_dst_state(self, witem: cache_table.WaitingLoadWordDst):
        """Initialize protocol state for DST jamlet."""
        instr = witem.item
        is_dst = (instr.dst.k_index == self.k_index and
                  instr.dst.j_in_k_index == self.j_in_k_index)
        if is_dst:
            logger.warning(f'{self.clock.cycle}: jamlet {(self.x, self.y)}: setting j_in_k={self.j_in_k_index} to WAITING_FOR_REQUEST')
            witem.protocol_states[self.j_in_k_index] = LoadDstState.WAITING_FOR_REQUEST

    def get_vline_offsets(
            self, dst_ew: int, dst_ve: int, start_index: int, n_elements: int) -> List[int]:
        '''
        This jamlet has an element at position dst_ve in the vector.
        The position of the element in the next vline will be elements_in_vline + dst_ve
        We want to find all the vline_offsets that give elements in the range
        start_index to start_index + n_elements.

        This is useful since if we want to load or store multiple vector lines at a time
        we can easily do a word from each vector line for this jamlet.
        '''
        index = 0
        vline_offsets = []
        elements_in_vline = self.params.vline_bytes * 8 // dst_ew
        while index * elements_in_vline + dst_ve < start_index + n_elements:
            if index * elements_in_vline + dst_ve >= start_index:
                vline_offsets.append(index)
            index += 1
        return vline_offsets

    async def handle_load_j2j_words_req(self, packet: List[Any]) -> None:
        '''
        The dst jamlet recieves a LOAD_J2J_WORDS_REQ packet.  This function
        determines if it can write the values to the register file and sends
        a response.
        '''
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        assert header.message_type == MessageType.LOAD_J2J_WORDS_REQ
        item = self.cache_table.get_waiting_item_by_instr_ident(header.ident)
        if item is None:
            # This kamlet doesn't know about this instruction.
            # There is nothing we can do for now other than send a drop response.
            await self.send_load_j2j_words_drop(header)
            return
        assert isinstance(item, cache_table.WaitingLoadJ2JWords)
        instr = item.item
        dst_ordering = instr.dst_ordering
        src_ew = instr.k_maddr.ordering.ew
        dst_ew = dst_ordering.ew
        logical_addr = instr.k_maddr.to_logical_vline_addr()
        start_logical_addr = logical_addr.offset_bits(-instr.start_index * src_ew)
        offset = start_logical_addr.bit_addr

        src_vw_index = addresses.j_coords_to_vw_index(
                self.params, instr.dst_ordering.word_order, header.source_x, header.source_y)

        mapping = ew_convert.get_mapping_for_src(
                params=self.params, src_ew=src_ew, dst_ew=dst_ew,
                src_v=0, src_vw=src_vw_index, src_tag=header.tag, src_offset=offset)

        assert mapping is not None
        dst_tag = mapping.dst_tag
        response_index = self.j_in_k_index * instr.n_tags() + dst_tag
        current_dst_state = item.protocol_states[response_index].dst_state
        logger.debug(f'jamlet ({self.x}, {self.y}): handle_load_j2j_words_req from ({header.source_x}, {header.source_y}) src_tag={header.tag} -> dst_tag={dst_tag} response_index={response_index} current_dst_state={current_dst_state}')

        assert len(packet) >= 2
        words = packet[1:]
        shift = mapping.src_wb - mapping.dst_wb
        mask = mapping.dst_mask()

        vline_offsets = self.get_vline_offsets(
                dst_ew, mapping.dst_ve, instr.start_index, instr.n_elements)
        assert len(vline_offsets) == len(words)

        dst_regs = [instr.dst + vline_offset for vline_offset in vline_offsets]

        # We should be guarantted to be able to write to this register. Otherwise
        # witem couldn't have been created.

        word_bytes = self.params.word_bytes
        for vline_offset, word in zip(vline_offsets, words):
            assert isinstance(word, (bytes, bytearray))
            assert len(word) == self.params.word_bytes
            word_as_int = int.from_bytes(word, byteorder='little')
            if shift < 0:
                shifted = word_as_int << (-shift)
            else:
                shifted = word_as_int >> shift
            dst_reg = instr.dst + vline_offset
            old_word = self.rf_slice[dst_reg * word_bytes: (dst_reg+1) * word_bytes]
            old_word_as_int = int.from_bytes(old_word, byteorder='little')
            masked_old_word = old_word_as_int & (~mask)
            masked_shifted = shifted & mask
            updated_word = masked_old_word | masked_shifted
            updated_word_bytes = updated_word.to_bytes(word_bytes, byteorder='little')
            logger.warning(f'{self.clock.cycle}: LOAD_J2J: jamlet ({self.x},{self.y}): dst_vw={mapping.dst_vw}, vline_offset={vline_offset}, dst_reg={dst_reg}, bytes={updated_word_bytes.hex()}')
            self.rf_slice[dst_reg * word_bytes: (dst_reg+1) * word_bytes] = updated_word_bytes

        assert item.protocol_states[response_index].dst_state == LoadDstState.WAITING_FOR_REQUEST
        item.protocol_states[response_index].dst_state = LoadDstState.COMPLETE
        await self.send_load_j2j_words_resp(header)

    def get_load_item_and_response_index(
            self, header: TaggedHeader) -> Tuple[WaitingItem, int]:
        '''
        Get the response_index for the src jamlet along with the waiting item.
        '''
        item = self.cache_table.get_waiting_item_by_instr_ident(header.ident)
        assert item is not None
        instr = item.item
        response_index = self.j_in_k_index * instr.n_tags() + header.tag
        return item, response_index

    async def handle_load_j2j_words_drop(self, packet: List[Any]) -> None:
        '''
        The src jamlet runs when the dst jamlet sends a drop message.
        '''
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        assert header.message_type == MessageType.LOAD_J2J_WORDS_DROP
        assert len(packet) == 1
        item = self.cache_table.get_waiting_item_by_instr_ident(header.ident)
        assert isinstance(item, cache_table.WaitingLoadJ2JWords)
        response_tag = self.j_in_k_index * item.item.n_tags() + header.tag
        item.protocol_states[response_tag].src_state = LoadSrcState.NEED_TO_SEND

    async def handle_load_j2j_words_resp(self, packet: List[Any]) -> None:
        '''
        The src jamlet runs when the dst jamlet responds that is has
        processed the LOAD_J2J_WORDS message.
        '''
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        assert header.message_type == MessageType.LOAD_J2J_WORDS_RESP
        assert len(packet) == 1
        item = self.cache_table.get_waiting_item_by_instr_ident(header.ident)
        assert isinstance(item, cache_table.WaitingLoadJ2JWords)
        response_tag = self.j_in_k_index * item.item.n_tags() + header.tag
        item.protocol_states[response_tag].src_state = LoadSrcState.COMPLETE

    async def send_load_j2j_words_drop(self, rcvd_header: TaggedHeader):
        header = TaggedHeader(
            target_x=rcvd_header.source_x,
            target_y=rcvd_header.source_y,
            source_x=self.x,
            source_y=self.y,
            send_type=SendType.SINGLE,
            message_type=MessageType.LOAD_J2J_WORDS_DROP,
            length=1,
            ident=rcvd_header.ident,
            tag=rcvd_header.tag,
            )
        packet = [header]
        await self.send_packet(packet)

    async def send_load_j2j_words_resp(self, rcvd_header: TaggedHeader):
        assert self.x == rcvd_header.target_x
        assert self.y == rcvd_header.target_y
        header = TaggedHeader(
            target_x=rcvd_header.source_x,
            target_y=rcvd_header.source_y,
            source_x=self.x,
            source_y=self.y,
            send_type=SendType.SINGLE,
            message_type=MessageType.LOAD_J2J_WORDS_RESP,
            length=1,
            ident=rcvd_header.ident,
            tag=rcvd_header.tag,
            )
        packet = [header]
        await self.send_packet(packet)

    async def send_load_word_req(self, witem: cache_table.WaitingLoadWordSrc):
        """SRC jamlet sends request with data to DST jamlet."""
        instr = witem.item

        # Convert dst k_index and j_in_k_index to absolute jamlet coordinates
        target_x, target_y = addresses.k_indices_to_j_coords(
            self.params, instr.dst.k_index, instr.dst.j_in_k_index)

        witem.protocol_states[self.j_in_k_index] = LoadSrcState.WAITING_FOR_RESPONSE

        cache_slot = witem.cache_slot
        assert cache_slot is not None

        j_saddr = instr.src.to_j_saddr(self.cache_table)
        wb = self.params.word_bytes
        sram_addr = (j_saddr.addr // wb) * wb
        word = self.sram[sram_addr : sram_addr + self.params.word_bytes]

        logger.warning(f'{self.clock.cycle}: LOAD_WORD: jamlet ({self.x}, {self.y}): send_load_word_req to ({target_x}, {target_y}) ident={instr.instr_ident} sram_addr={sram_addr} k_maddr.bit_addr={instr.src.bit_addr} word={word.hex()}')

        header = TaggedHeader(
            target_x=target_x, target_y=target_y,
            source_x=self.x, source_y=self.y,
            message_type=MessageType.LOAD_WORD_REQ,
            send_type=SendType.SINGLE,
            length=2,
            ident=instr.instr_ident, tag=0)

        await self.send_packet([header, word])

    async def handle_load_word_req(self, packet: List[Any]):
        """DST jamlet receives request with data, writes to register, sends response."""
        header = packet[0]
        word = packet[1]

        logger.warning(f'{self.clock.cycle}: LOAD_WORD: jamlet ({self.x}, {self.y}): handle_load_word_req from ({header.source_x}, {header.source_y}) ident={header.ident}')

        dst_ident = header.ident + 1
        witem = self.cache_table.get_waiting_item_by_instr_ident(dst_ident)
        if witem is None:
            # Debug: show all waiting items with their instr_idents
            witems_debug = [(i, w.instr_ident, type(w).__name__) for i, w in enumerate(self.cache_table.waiting_items) if w is not None]
            logger.warning(f'{self.clock.cycle}: LOAD_WORD: jamlet ({self.x}, {self.y}): DROP - no witem. Waiting items: {witems_debug}')
            await self.send_load_word_drop(header)
            return

        assert isinstance(witem, cache_table.WaitingLoadWordDst)
        assert witem.protocol_states[self.j_in_k_index] == LoadDstState.WAITING_FOR_REQUEST
        instr = witem.item
        word_as_int = int.from_bytes(word, byteorder='little')

        old_word = self.rf_slice[instr.dst.reg * self.params.word_bytes :
                                 (instr.dst.reg + 1) * self.params.word_bytes]
        old_word_as_int = int.from_bytes(old_word, byteorder='little')

        # Calculate shift amount: dst position - src position
        src_word_offset = instr.src.addr % self.params.word_bytes
        dst_word_offset = instr.dst.offset_in_word
        shift_bytes = src_word_offset - dst_word_offset
        shift_bits = shift_bytes * 8

        logger.warning(f'{self.clock.cycle}: LOAD_WORD: jamlet ({self.x}, {self.y}): '
                      f'src.addr={instr.src.addr}, src_word_offset={src_word_offset}, '
                      f'dst.offset_in_word={dst_word_offset}, shift_bytes={shift_bytes}')

        # Expand byte_mask from bit-per-byte to full byte mask
        # byte_mask tells us which bytes in the SOURCE word are valid
        dst_expanded_mask = 0
        for byte_idx in range(self.params.word_bytes):
            if instr.byte_mask & (1 << byte_idx):
                dst_expanded_mask |= (0xFF << (byte_idx * 8))

        # Shift both the data and the mask to destination positions
        if shift_bits < 0:
            shifted_word = word_as_int << (-shift_bits)
        else:
            shifted_word = word_as_int >> shift_bits

        # Merge shifted data with old register value using shifted mask
        masked_new = shifted_word & dst_expanded_mask
        masked_old = old_word_as_int & (~dst_expanded_mask)
        result = masked_old | masked_new

        logger.warning(f'{self.clock.cycle}: LOAD_WORD: jamlet ({self.x}, {self.y}): '
                      f'word=0x{word_as_int:016x}, dst_mask=0x{dst_expanded_mask:016x}, '
                      f'shift_bits={shift_bits}, shifted=0x{shifted_word:016x}, '
                      f'dst_mask=0x{dst_expanded_mask:016x}, old=0x{old_word_as_int:016x}, '
                      f'masked_new=0x{masked_new:016x}')

        result_bytes = result.to_bytes(self.params.word_bytes, byteorder='little')
        self.rf_slice[instr.dst.reg * self.params.word_bytes :
                      (instr.dst.reg + 1) * self.params.word_bytes] = result_bytes

        witem.protocol_states[self.j_in_k_index] = LoadDstState.COMPLETE

        logger.warning(f'{self.clock.cycle}: LOAD_WORD: jamlet ({self.x}, {self.y}): wrote to reg={instr.dst.reg} result={result_bytes.hex()}')

        await self.send_load_word_resp(header)

    async def send_load_word_resp(self, rcvd_header: TaggedHeader):
        """DST sends acknowledgment response to SRC."""
        header = TaggedHeader(
            target_x=rcvd_header.source_x, target_y=rcvd_header.source_y,
            source_x=self.x, source_y=self.y,
            message_type=MessageType.LOAD_WORD_RESP,
            send_type=SendType.SINGLE,
            length=1,
            ident=rcvd_header.ident, tag=0)
        await self.send_packet([header])

    async def send_load_word_drop(self, rcvd_header: TaggedHeader):
        """DST sends drop to SRC when not ready."""
        header = TaggedHeader(
            target_x=rcvd_header.source_x, target_y=rcvd_header.source_y,
            source_x=self.x, source_y=self.y,
            message_type=MessageType.LOAD_WORD_DROP,
            send_type=SendType.SINGLE,
            length=1,
            ident=rcvd_header.ident, tag=0)
        await self.send_packet([header])

    async def handle_load_word_resp(self, packet: List[Any]):
        """SRC jamlet receives acknowledgment response."""
        header = packet[0]
        witem = self.cache_table.get_waiting_item_by_instr_ident(header.ident)
        assert isinstance(witem, cache_table.WaitingLoadWordSrc)

        logger.warning(f'{self.clock.cycle}: LOAD_WORD: jamlet ({self.x}, {self.y}): handle_load_word_resp from ({header.source_x}, {header.source_y}) - COMPLETE')

        witem.protocol_states[self.j_in_k_index] = LoadSrcState.COMPLETE

    async def handle_load_word_drop(self, packet: List[Any]):
        """SRC jamlet receives drop, will retry request."""
        header = packet[0]
        witem = self.cache_table.get_waiting_item_by_instr_ident(header.ident)
        assert isinstance(witem, cache_table.WaitingLoadWordSrc)

        logger.warning(f'{self.clock.cycle}: LOAD_WORD: jamlet ({self.x}, {self.y}): handle_load_word_drop from ({header.source_x}, {header.source_y}) - will RETRY')

        witem.protocol_states[self.j_in_k_index] = LoadSrcState.NEED_TO_SEND

    async def send_load_word_retry(self, witem: cache_table.WaitingLoadWordDst):
        """DST jamlet sends retry to SRC when it becomes ready."""
        instr = witem.item

        src_j_in_k = instr.src.j_in_k_index
        target_x = src_j_in_k % self.params.j_cols
        target_y = src_j_in_k // self.params.j_cols

        witem.protocol_states[self.j_in_k_index] = LoadDstState.WAITING_FOR_REQUEST

        header = TaggedHeader(
            target_x=target_x, target_y=target_y,
            source_x=self.x, source_y=self.y,
            message_type=MessageType.LOAD_WORD_RETRY,
            send_type=SendType.SINGLE,
            length=1,
            ident=instr.instr_ident, tag=0)

        await self.send_packet([header])

    async def handle_load_word_retry(self, packet: List[Any]):
        """SRC jamlet receives retry, resend request."""
        header = packet[0]
        witem = self.cache_table.get_waiting_item_by_instr_ident(header.ident)
        assert isinstance(witem, cache_table.WaitingLoadWordSrc)

        witem.protocol_states[self.j_in_k_index] = LoadSrcState.NEED_TO_SEND


    async def _monitor_waiting_items(self) -> None:
        while True:
            await self.clock.next_cycle
            for witem in self.cache_table.waiting_items:
                if witem is None:
                    continue
                if isinstance(witem, cache_table.WaitingLoadJ2JWords):
                    instr = witem.item
                    assert isinstance(instr, kinstructions.Load)
                    if witem.cache_is_avail:
                        n_tags = instr.n_tags()
                        for tag in range(n_tags):
                            response_index = self.j_in_k_index * n_tags + tag
                            protocol_state = witem.protocol_states[response_index]
                            if protocol_state.src_state == LoadSrcState.NEED_TO_SEND:
                                await self.send_load_j2j_words_req(witem, tag, assert_sends=False)
                elif isinstance(witem, cache_table.WaitingStoreJ2JWords):
                    instr = witem.item
                    assert isinstance(instr, kinstructions.Store)
                    n_tags = instr.n_tags()
                    for tag in range(n_tags):
                        response_index = self.j_in_k_index * n_tags + tag
                        protocol_state = witem.protocol_states[response_index]
                        if protocol_state.src_state == cache_table.StoreSrcState.NEED_TO_SEND:
                            await self.send_store_j2j_words_req(witem, tag, assert_sends=False)
                        if protocol_state.dst_state == cache_table.StoreDstState.NEED_TO_ASK_FOR_RESEND:
                            if witem.cache_is_avail:
                                await self.send_store_j2j_words_retry(witem, tag)
                elif isinstance(witem, cache_table.WaitingLoadWordSrc):
                    if witem.protocol_states[self.j_in_k_index] == LoadSrcState.NEED_TO_SEND:
                        if witem.cache_is_avail:
                            await self.send_load_word_req(witem)
                elif isinstance(witem, cache_table.WaitingLoadWordDst):
                    if witem.protocol_states[self.j_in_k_index] == LoadDstState.NEED_TO_ASK_FOR_RESEND:
                        await self.send_load_word_retry(witem)

    async def run(self):
        for router in self.routers:
            self.clock.create_task(router.run())
        self.clock.create_task(self._send_packets())
        self.clock.create_task(self._receive_packets())
        self.clock.create_task(self._monitor_waiting_items())
        self.clock.create_task(self._monitor_cache_requests())

    SEND = 0
    INSTRUCTIONS = 1
