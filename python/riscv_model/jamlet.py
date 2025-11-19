import logging
from typing import Set, List, Any

import addresses
from params import LamletParams
from cache_table import CacheTable, WItemType, LoadSrcState, LoadDstState
from message import Direction, SendType, MessageType, CHANNEL_MAPPING
from message import Header, IdentHeader, AddressHeader, ValueHeader, TaggedHeader
from utils import Queue
from router import Router
import kinstructions
import memlet
import utils
import ew_convert
from cache_table import CacheRequestType, WaitingItem, CacheState


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
            MessageType.LOAD_J2J_WORDS: Queue(2),
            MessageType.LOAD_J2J_WORDS_RESP: Queue(2),
            MessageType.LOAD_J2J_WORDS_DROP: Queue(2),
            MessageType.STORE_J2J_WORDS: Queue(2),
            MessageType.STORE_J2J_WORDS_RESP: Queue(2),
            MessageType.STORE_J2J_WORDS_DROP: Queue(2),
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
        logger.warning('&&&&&&&&&&&&&&&&&&&&&& Got a read line resp packet')
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
        elif header.message_type == MessageType.LOAD_J2J_WORDS:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_load_j2j_words_req(packet)
        elif header.message_type == MessageType.LOAD_J2J_WORDS_RESP:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_load_j2j_words_resp(packet)
        elif header.message_type == MessageType.LOAD_J2J_WORDS_DROP:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_load_j2j_words_drop(packet)
        elif header.message_type == MessageType.STORE_J2J_WORDS:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_store_j2j_words_req(packet)
        elif header.message_type == MessageType.STORE_J2J_WORDS_RESP:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_store_j2j_words_resp(packet)
        elif header.message_type == MessageType.STORE_J2J_WORDS_DROP:
            packet = await self._receive_packet_body(queue, header)
            await self.handle_store_j2j_words_drop(packet)
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

    #async def handle_load_instr(self, instr: kinstructions.Load, item_index: int):
    #    logger.debug(f'kamlet: handle_load_instr {hex(instr.k_maddr.addr)}')
    #    item = self.cache_table.waiting_items[item_index]
    #    assert item is not None
    #    assert item.item == instr
    #    # Initially say all response have been received.
    #    for tag in range(instr.n_tags()):
    #        await self.load_j2j_word_send(item_index, tag, assert_sends=False)

    def handle_load_instr_simple(self, instr: kinstructions.Load):
        """
        This is called when we are processing a Load instructions which is aligned to
        local kamlet memory, and the data is in the cache.
        """
        assert self.cache_table.can_read(instr.k_maddr)
        slot = self.cache_table.addr_to_slot(instr.k_maddr)
        sram_addr = slot * self.params.word_bytes
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
        n_vectors = 1 << 20

        start_eb, start_vw, start_we, start_v = ew_convert.split_by_factors(start_addr_bit, [ew, j_in_l, ww//ew, n_vectors])
        final_addr_bit = start_addr_bit + instr.n_elements * ew - 1
        final_eb, final_vw, final_we, final_v = ew_convert.split_by_factors(final_addr_bit, [ew, j_in_l, ww//ew, n_vectors])

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

        logger.warning(f'{self.clock.cycle}: jamlet {(self.x, self.y)}: Running the vector load')
        cache_base_v = start_c * self.params.vlines_in_cache_line
        for mask, v_index in zip(masks, range(start_v, final_v+1)):
            sram_addr = (slot + v_index - cache_base_v) * ww//8
            word = self.sram[sram_addr: sram_addr + ww//8]
            word_as_int = int.from_bytes(word, byteorder='little')
            masked = word_as_int & mask
            masked_as_bytes = masked.to_bytes(ww//8, byteorder='little')
            rf_word_addr = instr.dst + start_v - base_v
            logger.warning(f'{self.clock.cycle}: jamlet {(self.x, self.y)}: Loading {[int(x) for x in masked_as_bytes]}')
            self.rf_slice[rf_word_addr * ww//8: (rf_word_addr+1) * ww//8] = masked_as_bytes
        

    async def load_j2j_words_send(self, item_index: int, tag: int, assert_sends: bool) -> None:
        item = self.cache_table.waiting_items[item_index]
        assert item is not None
        instr = item.item
        assert isinstance(instr, kinstructions.Load)

        src_ordering: addresses.Ordering = instr.k_maddr.ordering
        dst_ordering: addresses.Ordering = instr.dst_ordering
        src_ew = src_ordering.ew
        dst_ew = dst_ordering.ew
        vw_index = addresses.j_coords_to_vw_index(
                self.params, instr.dst_ordering.word_order, self.x, self.y)
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                self.params, word_order=dst_ordering.word_order, vw_index=vw_index)
        logical_addr = instr.k_maddr.to_logical_vline_addr()
        start_logical_addr = logical_addr.offset_bits(-instr.start_index * src_ew)
        offset = start_logical_addr.bit_addr

        mapping = ew_convert.get_mapping_for_dst(
            params=self.params, src_ew=src_ew, dst_ew=dst_ew,
            src_offset=offset, dst_v=0, dst_vw=vw_index, dst_tag=tag)

        if mapping is not None:
            # Work out which elements in the destination word are getting written to.
            # We combine this information with the mask to see if anything is getting updated.
            ww = self.params.word_bytes * 8
            mask_as_bits = utils.uint_to_list_of_uints(mapping.dst_mask(), width=1, size=ww)
            dst_wes_as_bits = [1 if any(mask_as_bits[index*dst_ew: (index+1)*dst_ew]) else 0
                               for index in range(ww//dst_ew)]
            dst_wes = utils.list_of_uints_to_uint(dst_wes_as_bits, width=1)
        else:
            dst_wes = 0
        
        if instr.mask_reg is None:
            use_mask = False
            mask_word = None
        else:
            use_mask = True
            mask_addr = instr.mask_reg * self.params.word_bytes
            mask_word = self.rf_slice[mask_addr]

        item.response_infos[j_in_k_index*instr.n_tags() + tag].dropped = False
        if mapping is None or (use_mask and not (dst_wes & mask_word)):

            # There is are not required dst_we that we have an active mask for
            assert not assert_sends
            item.response_infos[j_in_k_index*instr.n_tags() + tag].received = True
            item.response_infos[j_in_k_index*instr.n_tags() + tag].sent = True
            return
        item.response_infos[j_in_k_index*instr.n_tags() + tag].received = False
        item.response_infos[j_in_k_index*instr.n_tags() + tag].sent = True

        use_offset = (mapping.src_v * self.params.vline_bytes * 8 +
                      mapping.src_vw * self.params.word_bytes * 8)
        start_physical_addr = start_logical_addr.to_physical_vline_addr()

        use_physical_addr = start_physical_addr.offset_bits(use_offset)
        use_k_maddr = use_physical_addr.to_k_maddr()
        src_vw = mapping.src_vw
        target_x, target_y = addresses.vw_index_to_j_coords(
                self.params, src_ordering.word_order, src_vw)
        src_k_index, src_j_in_k_index = addresses.vw_index_to_k_indices(
                self.params, src_ordering.word_order, src_vw)
        assert use_k_maddr.k_index == src_k_index

        k_maddr = addresses.KMAddr(
            params=self.params,
            k_index=use_k_maddr.k_index,
            ordering=src_ordering,
            bit_addr=use_k_maddr.bit_addr,
            )
        header = TaggedHeader(
            target_x=target_x,
            target_y=target_y,
            source_x=self.x,
            source_y=self.y,
            length=2,
            message_type=MessageType.LOAD_J2J_WORDS,
            send_type=SendType.SINGLE,
            ident=item_index,
            tag=tag,
            )
        packet = [header, k_maddr]
        await self.send_packet(packet)


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
        sram_addr = slot * self.params.word_bytes
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
        n_vectors = 1 << 20

        start_eb, start_vw, start_we, start_v = ew_convert.split_by_factors(start_addr_bit, [ew, j_in_l, ww//ew, n_vectors])
        final_addr_bit = start_addr_bit + instr.n_elements * ew - 1
        final_eb, final_vw, final_we, final_v = ew_convert.split_by_factors(final_addr_bit, [ew, j_in_l, ww//ew, n_vectors])

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
            el_mask[0: final_v-start_v+1] = mask_bits[start_v-base_v: final_v-base_v]
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
        for mask, v_index in zip(masks, range(start_v, final_v+1)):
            rf_word_addr = instr.src + start_v - base_v
            word = self.rf_slice[rf_word_addr * ww//8: (rf_word_addr+1) * ww//8]
            word_as_int = int.from_bytes(word, byteorder='little')
            masked = word_as_int & mask
            sram_addr = (slot + v_index - cache_base_v) * ww//8
            masked_as_bytes = masked.to_bytes(ww//8, byteorder='little')
            logger.warning(f'{self.clock.cycle}: jamlet {(self.x, self.y)}: storing {[int(x) for x in masked_as_bytes]}')
            self.sram[sram_addr: sram_addr + ww//8] = masked_as_bytes

    async def store_j2j_words_send(self, item_index: int, tag: int, assert_sends: bool) -> None:
        '''
        Reads data from the local reg and send it to a remote jamlet to store it.

        item_index: The index of the WaitingItem corresponding to the Store kinstruction.
        tag: Identifies a particular segment in this word that needs to be sent to a particular
               other jamlet.  We can iteration through tags to send all the required data.
        asserts_sends: This tag should correspond to data that needs to be sent. Asserted when
                       we're resending a dropped packet just as a check.
        '''
        item = self.cache_table.waiting_items[item_index]
        assert item is not None
        instr = item.item
        assert isinstance(instr, kinstructions.Store)
        src_ordering: addresses.Ordering = instr.src_ordering
        dst_ordering: addresses.Ordering = instr.k_maddr.ordering
        src_ew = src_ordering.ew
        dst_ew = dst_ordering.ew
        vw_index = addresses.j_coords_to_vw_index(
                self.params, instr.src_ordering.word_order, self.x, self.y)
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                self.params, word_order=src_ordering.word_order, vw_index=vw_index)
        logical_addr = instr.k_maddr.to_logical_vline_addr()
        start_logical_addr = logical_addr.offset_bits(-instr.start_index * src_ew)
        offset = start_logical_addr.bit_addr
        mapping = ew_convert.get_mapping_for_src(
                params=self.params, src_ew=src_ew, dst_ew=dst_ew,
                dst_offset=offset, src_v=0, src_vw=vw_index, src_tag=tag)
        item.response_infos[j_in_k_index*instr.n_tags() + tag].dropped = False
        # Check if there is any data to send.
        elements_in_range = []
        if mapping is None:
            # This segment doesn't exist.
            pass
        else:
            # This segment is not in the specified range.
            element_index = mapping.src_ve
            index = 0
            while element_index < instr.start_index + instr.n_elements:
                if element_index >= instr.start_index:
                    elements_in_range.append(index)
                element_index += self.params.vline_bytes*8//src_ew
                index += 1
        if not elements_in_range:
            # We don't need to send this message so we mark it already sent and received
            assert not assert_sends
            item.response_infos[j_in_k_index*instr.n_tags() + tag].received = True
            item.response_infos[j_in_k_index*instr.n_tags() + tag].sent = True
            return
        item.response_infos[j_in_k_index*instr.n_tags() + tag].received = False
        item.response_infos[j_in_k_index*instr.n_tags() + tag].sent = True

        target_x, target_y = addresses.vw_index_to_j_coords(
                self.params, dst_ordering.word_order, mapping.dst_vw)

        word_bytes = self.params.word_bytes
        words = [self.rf_slice[(instr.src+index)*word_bytes: (instr.src+index+1)*word_bytes]
                 for index in elements_in_range]

        # We need to send data that is masked out still, because we need to tell the receiver
        # that the data is masked out.
        # TODO: Send shorter data when it is masked out.

        if instr.mask_reg is not None:
            mask_word = self.rf_slice[instr.mask_reg * word_bytes: (instr.mask_reg+1) * word_bytes]
            mask_bits = []
            for index in elements_in_range:
                vector_element = mapping.src_ve + index * self.params.vline_bytes*8//src_ew
                word_element = vector_element//self.params.j_in_l
                mask_bits.append((mask_word << word_element) & 1)
        else:
            mask_bits = [1] * len(words)
        mask_bits_as_int = utils.list_of_uints_to_uint(mask_bits, width=1)

        header = TaggedHeader(
            target_x=target_x,
            target_y=target_y,
            source_x=self.x,
            source_y=self.y,
            length=1 + len(words),
            message_type=MessageType.STORE_J2J_WORDS,
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
        assert header.message_type == MessageType.STORE_J2J_WORDS

        # We got a request to store some data.
        # Let's check to see if we have a waiting item for this.
        item = self.cache_table.get_waiting_item_by_instr_ident(header.ident)
        if item is None:
            # We not expected this message.
            # Presumably we haven't processed that instruction yet.
            # Drop the packet.
            await self.send_store_j2j_words_drop(header)
            return
        slot = item.cache_slot
        instr = item.instr
        assert isinstance(instr, kinstructions.Store)

        if self.cache_table.can_write(instr.k_maddr):
            assert item.cache_is_avail
            src_ew = instr.src_ordering.ew
            dst_ew = instr.k_maddr.ordering.ew
            vw_index = addresses.j_coords_to_vw_index(
                    self.params, instr.src_ordering.word_order, self.x, self.y)
            mapping = ew_convert.get_mapping_for_dst(
                    params=self.params, src_ew=src_ew, dst_ew=dst_ew,
                    dst_v=0, dst_vw=vw_index, dst_tag=header.tag)
            # Workout how much we need to shift the word.
            shift = mapping.src_wb - mapping.dst_wb
            # Work out what mask to apply
            segment_mask = ((1 << mapping.n_bits)-1) << mapping.dst_wb

            v_in_c = self.params.vlines_in_cache_line
            word_bytes = self.params.word_bytes

            for word_index, word in enumerate(words):
                mask_bit = (header.mask >> word_index) & 1
                word_as_int = int.from_bytes(word, byteorder='little')
                if shift > 0:
                    shifted = word_as_int >> shift
                else:
                    shifted = word_as_int << (-shift)
                if mask_bit:
                    old_word = self.sram[slot*v_in_c*word_bytes: (slot*v_in_c + 1)*word_bytes]
                    old_word_as_int = int.from_bytes(old_word, byteorder='little')
                    old_word_masked = old_word_as_int & (~segment_mask)
                    new_word = old_word_masked | shifted
                    new_word_bytes = new_word.to_bytes(word_bytes, byteorder='little')
                    self.sram[slot*v_in_c*word_bytes: (slot*v_in_c + 1)*word_bytes] = new_word_bytes
            item.response_infos[header.tag].received.set(True)
            cache_state = self.cache_table.slot_states[slot]
            assert cache_state.state in (CacheState.SHARED, CacheState.MODIFIED)
            cache_state.state = CacheState.MODIFIED
            await self.send_store_j2j_words_resp(header)
        else:
            # We can't write to the cache table.
            # When the cache is made available we'll send a Retry message back.
            item.response_infos[header.tag].retry.set(True)
            assert not item.cache_is_avail

    def get_item_and_response_index(self, header: TaggedHeader) -> (WaitingItem, int):
        item = self.cache_table.get_waiting_item_by_instr_ident(header.ident)
        assert item is not None
        assert item.response_infos[header.tag].received is False
        instr = item.item
        src_ordering = instr.k_maddr.ordering
        vw_index = addresses.j_coords_to_vw_index(
                self.params, instr.dst_ordering.word_order, self.x, self.y)
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                self.params, src_ordering.word_order, vw_index)
        response_index = j_in_k_index * instr.n_tags() + header.tag
        return item, response_index

    async def handle_store_j2j_words_drop(self, packet: List[Any]) -> None:
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        assert header.message_type == MessageType.STORE_J2J_WORDS_DROP
        assert len(packet) == 1
        item, response_index = self.get_item_and_response_index(header)
        # We mark sent as false so that it gets sent again.
        item.response_infos[response_index].sent = False

    async def handle_store_j2j_words_resp(self, packet: List[Any]) -> None:
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        assert header.message_type == MessageType.STORE_J2J_WORDS_RESP
        assert len(packet) == 1
        item, response_index = self.get_item_and_response_index(header)
        item.response_infos[response_index].received_resp = True

    async def handle_store_j2j_words_retry(self, packet: List[Any]) -> None:
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        assert header.message_type == MessageType.STORE_J2J_WORDS_RESP
        assert len(packet) == 1
        item, response_index = self.get_item_and_response_index(header)
        # We mark sent as false so that it gets sent again.
        item.response_infos[response_index].sent = False

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

    async def send_store_j2j_words_retry(self, item: WaitingItem, tag: int) -> None:
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
        target_x, target_y = addresses.vw_index_to_j_coords(
                self.params, instr.k_maddr.ordering.word_order, mapping.dst_vw)

        header = TaggedHeader(
            target_x=target_x,
            target_y=target_y,
            source_x=self.x,
            source_y=self.y,
            send_type=SendType.SINGLE,
            message_type=MessageType.STORE_J2J_WORDS_RESP,
            length=1,
            ident=item.instr_ident,
            tag=tag,
            )
        packet = [header]
        await self.send_packet(packet)
        



    ###########################################################
    #
    #  LOAD
    #  Various functions that deal with processing the vector store.
    #  using jamlet-to-jamlet message passing
    #
    ############################################################

    async def handle_load_j2j_words(self, instr: kinstructions.Load) -> None:
        raise NotImplementedError()

    async def handle_load_j2j_words_drop(self, packet: List[Any]) -> None:
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        assert header.message_type == MessageType.LOAD_J2J_WORDS_DROP
        assert len(packet) == 1
        item = self.cache_table.waiting_items[header.ident]
        assert item is not None
        assert item.response_infos[header.tag].received is False
        instr = item.item
        src_ordering = instr.k_maddr.ordering
        vw_index = addresses.j_coords_to_vw_index(
                self.params, instr.dst_ordering.word_order, self.x, self.y)
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                self.params, src_ordering.word_order, vw_index)
        instr = item.item
        item.response_infos[j_in_k_index * instr.n_tags() + header.tag].received = True
        item.response_infos[j_in_k_index * instr.n_tags() + header.tag].drop_notification = False

    async def handle_load_j2j_words_resp(self, packet: List[Any]) -> None:
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        assert header.message_type == MessageType.LOAD_J2J_WORDS_RESP
        item = self.cache_table.waiting_items[header.ident]
        assert item is not None
        assert isinstance(item.item, kinstructions.Load)
        instr = item.item
        src_ordering = instr.k_maddr.ordering
        dst_ordering = instr.dst_ordering
        src_ew = src_ordering.ew
        dst_ew = dst_ordering.ew
        logical_addr = instr.k_maddr.to_logical_vline_addr()
        start_logical_addr = logical_addr.offset_bits(-instr.start_index * src_ew)
        offset = start_logical_addr.bit_addr
        vw_index = addresses.j_coords_to_vw_index(
                self.params, instr.dst_ordering.word_order, self.x, self.y)
        use = ew_convert.dst_use_from_tag(
                self.params, dst_ew, src_ew, instr.start_index, instr.n_elements,
                offset, vw_index, header.tag)
        assert use is not None
        assert len(packet) == 2
        word = packet[1]
        assert isinstance(word, bytes) or isinstance(word, bytearray)
        assert len(word) == self.params.word_bytes
        word_as_int = int.from_bytes(packet[1], byteorder='little')
        if use.shift < 0:
            shifted = word_as_int >> (-use.shift)
        else:
            shifted = word_as_int << use.shift
        masked = shifted & use.mask
        rf_address = instr.dst * self.params.word_bytes
        reg_word = self.rf_slice[rf_address: rf_address + self.params.word_bytes]
        reg_word_as_int = int.from_bytes(reg_word, byteorder='little')
        masked_reg_word = reg_word_as_int & (~use.mask)
        updated_reg_word = masked_reg_word | masked
        updated_reg_word_as_bytes = updated_reg_word.to_bytes(self.params.word_bytes, byteorder='little')
        self.rf_slice[rf_address: rf_address + self.params.word_bytes] = updated_reg_word_as_bytes
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                self.params, src_ordering.word_order, vw_index)
        response_index = j_in_k_index * instr.n_tags() + header.tag
        assert item.response_infos[response_index].received is False
        item.response_infos[response_index].received = True
        item.response_infos[response_index].drop_notification = False

    async def handle_store_j2j_words_resp(self, packet: List[Any]) -> None:
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        assert header.message_type == MessageType.STORE_J2J_WORDS_RESP
        item = self.cache_table.waiting_items[header.ident]
        assert item is not None
        assert isinstance(item.item, kinstructions.Store)
        instr = item.item
        vw_index = addresses.j_coords_to_vw_index(
                self.params, instr.src_ordering.word_order, self.x, self.y)
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                self.params, instr.src_ordering.word_order, vw_index)
        item.response_infos[j_in_k_index * instr.n_tags() + header.tag].received = True
        item.response_infos[j_in_k_index * instr.n_tags() + header.tag].drop_notification = False

    async def handle_load_j2j_words_req(self, packet: List[Any]) -> None:
        """
        Handle a jamlet-to-jamlet request to load a word.
        If it can't immediately handle this message it must send a drop response.
        """
        header = packet[0]
        assert isinstance(header, TaggedHeader)
        assert header.message_type == MessageType.LOAD_J2J_WORDS
        assert len(packet) == 2
        assert isinstance(packet[1], addresses.KMAddr)
        k_maddr = packet[1]
        if not self.cache_table.can_read(k_maddr):
            # It's not in cache we need to retrieve it.
            item_index = self.cache_table.get_free_item_index_if_exists()
            if item_index is None:
                # We need to drop this packet.
                await self.send_load_j2j_words_drop(header)
            else:
                cache_slot = self.cache_table.addr_to_slot(k_maddr)
                self.cache_table.waiting_items[item_index] = WaitingItem(
                    response_infos=[],
                    item=header,
                    cache_is_read=True,
                    cache_slot=cache_slot,
                    )
        else:
            await self.send_load_j2j_words_resp(header, k_maddr)


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

    async def send_load_j2j_words_resp(self, rcvd_header: TaggedHeader, k_maddr: addresses.KMAddr):
        slot = self.cache_table.addr_to_slot(k_maddr)
        cache_line_offset = k_maddr.addr % self.params.cache_line_bytes
        sram_addr = slot * self.params.cache_line_bytes + cache_line_offset
        assert cache_line_offset % self.params.word_bytes == 0
        word = self.sram[sram_addr: sram_addr + self.params.word_bytes]
        assert self.x == rcvd_header.target_x
        assert self.y == rcvd_header.target_y
        header = TaggedHeader(
            target_x=rcvd_header.source_x,
            target_y=rcvd_header.source_y,
            source_x=self.x,
            source_y=self.y,
            send_type=SendType.SINGLE,
            message_type=MessageType.LOAD_J2J_WORDS_RESP,
            length=2,
            ident=rcvd_header.ident,
            tag=rcvd_header.tag,
            )
        packet = [header, word]
        await self.send_packet(packet)


    async def _monitor_waiting_items(self) -> None:
        while True:
            await self.clock.next_cycle
            for item_index, item in enumerate(self.cache_table.waiting_items):
                if item is None:
                    continue
                instr: kinstructions.KInstr
                if item.witem_type == WItemType.LOAD_J2J_WORDS:
                    instr = item.item
                    assert isinstance(instr, kinstructions.Load)
                    vw_index = addresses.j_coords_to_vw_index(
                            self.params, instr.dst_ordering.word_order, self.x, self.y)
                    src_ordering = instr.k_maddr.ordering
                    k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                            self.params, src_ordering.word_order, vw_index)
                    n_tags = instr.n_tags()
                    for tag in range(n_tags):
                        response_index = j_in_k_index * n_tags + tag
                        protocol_state = item.protocol_states[response_index]
                        if not protocol_state.src_state == LoadSrcState.NEED_TO_SEND:
                            await self.load_j2j_words_send(item_index, tag, assert_sends=False)
                elif item.witem_type == WItemType.STORE_J2J_WORDS:
                    instr = item.item
                    assert isinstance(instr, kinstructions.Store)
                    vw_index = addresses.j_coords_to_vw_index(
                            self.params, instr.src_ordering.word_order, self.x, self.y)
                    src_ordering = instr.k_maddr.ordering
                    k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                            self.params, src_ordering.word_order, vw_index)
                    n_tags = instr.n_tags()
                    for tag in range(n_tags):
                        response_index = j_in_k_index * n_tags + tag
                        protocol_state = item.protocol_states[response_index]
                        if not protocol_state.src_state == LoadSrcState.NEED_TO_SEND:
                            await self.store_j2j_words_send(item_index, tag, assert_sends=False)
                        if not protocol_state.dst_state == LoadDstState.NEED_TO_ASK_FOR_RESEND:
                            await self.send_store_j2j_words_retry(item, tag)

    async def run(self):
        for router in self.routers:
            self.clock.create_task(router.run())
        self.clock.create_task(self._send_packets())
        self.clock.create_task(self._receive_packets())
        self.clock.create_task(self._monitor_waiting_items())

    SEND = 0
    INSTRUCTIONS = 1


