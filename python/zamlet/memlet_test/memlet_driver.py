"""Abstract driver interface for memlet tests.

Packets are lists of [Header, payload...] matching the python model's
internal format. Each router has its own b_queue (input) and a_queue
(output).

Usage:
  await driver.reset()
  driver.start()
  await driver.write_cache_line(params, router_coords, ...)
"""

from abc import ABC, abstractmethod
from collections import deque
import logging

from zamlet.memlet import j_in_k_to_m_router
from zamlet.message import AddressHeader, MessageType, SendType
from zamlet.params import ZamletParams

logger = logging.getLogger(__name__)


class _PendingWrite:
    def __init__(self, fut, addr_pkt: list):
        self.fut = fut
        self.addr_pkt = addr_pkt
        self.data_pkts = {}  # (source_x, source_y) -> packet


class _PendingRead:
    def __init__(self, fut, addr_pkt: list):
        self.fut = fut
        self.addr_pkt = addr_pkt
        self.received_data = {}  # (target_x, target_y) -> data words


class _PendingWriteRead:
    def __init__(self, fut, addr_pkt: list):
        self.fut = fut
        self.addr_pkt = addr_pkt
        self.data_pkts = {}      # (source_x, source_y) -> packet
        self.received_data = {}  # (target_x, target_y) -> data words


class MemletDriver(ABC):

    def __init__(self, params: ZamletParams, router_coords: list,
                 k_base_x: int, k_base_y: int, a_queue_depth: int = 2):
        self.params = params
        self.router_coords = router_coords
        self.k_base_x = k_base_x
        self.k_base_y = k_base_y
        self.n_routers = len(router_coords)
        self.a_queue_depth = a_queue_depth
        self.b_queues = [deque() for _ in range(self.n_routers)]
        self.a_queues = [deque() for _ in range(self.n_routers)]
        self._pending_writes = {}      # ident -> _PendingWrite
        self._pending_reads = {}       # ident -> _PendingRead
        self._pending_write_reads = {} # ident -> _PendingWriteRead
        self.drop_count = 0
        # Set to False to stop draining a_queues, causing network backpressure.
        self.consume_responses = True

    def reset_drop_count(self) -> int:
        """Reset drop count and return the previous value."""
        count = self.drop_count
        self.drop_count = 0
        return count

    def start(self) -> None:
        """Start background coroutines that drive b_queues and drain a_queues."""
        self.start_soon(self._handle_responses())

    @abstractmethod
    async def reset(self) -> None:
        """Reset the memlet and wait for it to be ready."""

    def submit_packet(self, router_idx: int, pkt: list) -> None:
        """Submit a packet for sending. Tracks data packets for resend."""
        header = pkt[0]
        if header.message_type == MessageType.WRITE_LINE_DATA:
            ident = header.ident
            key = (header.source_x, header.source_y)
            if ident in self._pending_writes:
                self._pending_writes[ident].data_pkts[key] = pkt
            else:
                self._pending_write_reads[ident].data_pkts[key] = pkt
        elif header.message_type in (MessageType.WRITE_LINE_ADDR,
                                     MessageType.READ_LINE_ADDR,
                                     MessageType.WRITE_LINE_READ_LINE_ADDR):
            pass
        else:
            raise ValueError(f"Unknown message type: {header.message_type}")
        self.b_queues[router_idx].append(pkt)

    async def _handle_responses(self) -> None:
        """Monitor a_queues. Resolve futures on completion, resend on drop."""
        logger.debug("_handle_responses started")
        while True:
            # When consume_responses is False, responses accumulate in a_queues,
            # filling them up and propagating backpressure into the network.
            if not self.consume_responses:
                await self.tick()
                continue
            for r in range(self.n_routers):
                while self.a_queues[r]:
                    pkt = self.a_queues[r].popleft()
                    header = pkt[0]
                    msg = header.message_type
                    ident = header.ident

                    if msg == MessageType.WRITE_LINE_RESP:
                        pw = self._pending_writes.pop(ident)
                        pw.fut.set_result(None)
                        logger.info(f"write ident={ident} complete")

                    elif msg == MessageType.WRITE_LINE_ADDR_DROP:
                        self.drop_count += 1
                        pw = self._pending_writes[ident]
                        logger.info(f"write addr drop ident={ident}, resending")
                        self.submit_packet(0, pw.addr_pkt)

                    elif msg == MessageType.WRITE_LINE_DATA_DROP:
                        self.drop_count += 1
                        pw = self._pending_writes[ident]
                        sender = (header.target_x, header.target_y)
                        resend_pkt = pw.data_pkts[sender]
                        target_r = self._router_idx_for_target(
                            resend_pkt[0].target_x, resend_pkt[0].target_y)
                        logger.info(f"write data drop ident={ident}, resending")
                        self.submit_packet(target_r, resend_pkt)

                    elif msg == MessageType.READ_LINE_RESP:
                        pr = self._pending_reads[ident]
                        target = (header.target_x, header.target_y)
                        assert target not in pr.received_data
                        pr.received_data[target] = pkt[1:]
                        logger.info(f"read ident={ident} resp for {target}")
                        if len(pr.received_data) == self.params.j_in_k:
                            self._pending_reads.pop(ident)
                            pr.fut.set_result(pr.received_data)
                            logger.info(f"read ident={ident} complete")

                    elif msg == MessageType.READ_LINE_ADDR_DROP:
                        self.drop_count += 1
                        pr = self._pending_reads[ident]
                        logger.info(f"read drop ident={ident}, resending")
                        self.submit_packet(0, pr.addr_pkt)

                    elif msg == MessageType.WRITE_LINE_READ_LINE_RESP:
                        pwr = self._pending_write_reads[ident]
                        target = (header.target_x, header.target_y)
                        assert target not in pwr.received_data
                        pwr.received_data[target] = pkt[1:]
                        logger.info(f"write_read ident={ident} resp for {target}")
                        if len(pwr.received_data) == self.params.j_in_k:
                            self._pending_write_reads.pop(ident)
                            pwr.fut.set_result(pwr.received_data)
                            logger.info(f"write_read ident={ident} complete")

                    elif msg == MessageType.WRITE_LINE_READ_LINE_ADDR_DROP:
                        self.drop_count += 1
                        pwr = self._pending_write_reads[ident]
                        logger.info(f"write_read addr drop ident={ident}, resending")
                        self.submit_packet(0, pwr.addr_pkt)

                    else:
                        raise ValueError(f"Unexpected response type: {msg}")
            await self.tick()

    def _bytes_to_words(self, data: bytes) -> dict:
        """Split cache line bytes into per-jamlet word lists.

        Layout is interleaved: word 0 from each jamlet, then word 1, etc.
        """
        params = self.params
        wb = params.word_bytes
        words_per_jamlet = params.cache_slot_words_per_jamlet
        assert len(data) == words_per_jamlet * params.j_in_k * wb
        result = {j: [] for j in range(params.j_in_k)}
        off = 0
        for _ in range(words_per_jamlet):
            for j in range(params.j_in_k):
                result[j].append(int.from_bytes(data[off:off + wb], 'little'))
                off += wb
        return result

    def _words_to_bytes(self, words: dict) -> bytes:
        """Reassemble per-jamlet word lists into interleaved cache line bytes.

        words is keyed by (target_x, target_y).
        """
        params = self.params
        wb = params.word_bytes
        result = bytearray()
        for w in range(params.cache_slot_words_per_jamlet):
            for j in range(params.j_in_k):
                j_x = self.k_base_x + j % params.j_cols
                j_y = self.k_base_y + j // params.j_cols
                result.extend(words[(j_x, j_y)][w].to_bytes(wb, 'little'))
        return bytes(result)

    async def write_cache_line(self, ident: int, mem_addr: int, data: bytes) -> None:
        """Write a cache line. Queues all packets and awaits completion future."""
        params = self.params
        fut = self._make_future()

        per_jamlet = self._bytes_to_words(data)

        r0_x, r0_y = self.router_coords[0]
        addr_hdr = AddressHeader(
            target_x=r0_x, target_y=r0_y,
            source_x=self.k_base_x, source_y=self.k_base_y,
            length=1, message_type=MessageType.WRITE_LINE_ADDR,
            send_type=SendType.SINGLE, ident=ident, address=0,
        )
        addr_pkt = [addr_hdr, mem_addr]
        self._pending_writes[ident] = _PendingWrite(fut, addr_pkt)
        self.submit_packet(0, addr_pkt)

        for j in range(params.j_in_k):
            r = j_in_k_to_m_router(j, self.n_routers, params.j_in_k)
            r_x, r_y = self.router_coords[r]
            j_x = self.k_base_x + j % params.j_cols
            j_y = self.k_base_y + j // params.j_cols
            data_hdr = AddressHeader(
                target_x=r_x, target_y=r_y, source_x=j_x, source_y=j_y,
                length=params.cache_slot_words_per_jamlet,
                message_type=MessageType.WRITE_LINE_DATA,
                send_type=SendType.SINGLE, ident=ident, address=0,
            )
            self.submit_packet(r, [data_hdr] + per_jamlet[j])

        logger.debug(f"write_cache_line ident={ident} awaiting future")
        return await fut

    async def read_cache_line(self, ident: int, mem_addr: int, sram_addr: int) -> bytes:
        """Read a cache line. Returns cache line as bytes."""
        r0_x, r0_y = self.router_coords[0]

        addr_hdr = AddressHeader(
            target_x=r0_x, target_y=r0_y,
            source_x=self.k_base_x, source_y=self.k_base_y,
            length=1, message_type=MessageType.READ_LINE_ADDR,
            send_type=SendType.SINGLE, ident=ident, address=sram_addr,
        )
        self.submit_packet(0, [addr_hdr, mem_addr])

        fut = self._make_future()
        pr = _PendingRead(fut, [addr_hdr, mem_addr])
        self._pending_reads[ident] = pr
        words = await fut
        return self._words_to_bytes(words)

    async def write_read_cache_line(self, ident: int, write_mem_addr: int,
                                    read_mem_addr: int, sram_addr: int,
                                    data: bytes) -> bytes:
        """Atomic write + read. Returns read-back cache line as bytes."""
        params = self.params
        fut = self._make_future()

        per_jamlet = self._bytes_to_words(data)

        r0_x, r0_y = self.router_coords[0]
        addr_hdr = AddressHeader(
            target_x=r0_x, target_y=r0_y,
            source_x=self.k_base_x, source_y=self.k_base_y,
            length=2, message_type=MessageType.WRITE_LINE_READ_LINE_ADDR,
            send_type=SendType.SINGLE, ident=ident, address=sram_addr,
        )
        addr_pkt = [addr_hdr, write_mem_addr, read_mem_addr]
        self._pending_write_reads[ident] = _PendingWriteRead(fut, addr_pkt)
        self.submit_packet(0, addr_pkt)

        for j in range(params.j_in_k):
            r = j_in_k_to_m_router(j, self.n_routers, params.j_in_k)
            r_x, r_y = self.router_coords[r]
            j_x = self.k_base_x + j % params.j_cols
            j_y = self.k_base_y + j // params.j_cols
            data_hdr = AddressHeader(
                target_x=r_x, target_y=r_y, source_x=j_x, source_y=j_y,
                length=params.cache_slot_words_per_jamlet,
                message_type=MessageType.WRITE_LINE_DATA,
                send_type=SendType.SINGLE, ident=ident, address=0,
            )
            self.submit_packet(r, [data_hdr] + per_jamlet[j])

        words = await fut
        return self._words_to_bytes(words)

    def _router_idx_for_target(self, target_x: int, target_y: int) -> int:
        """Map target coordinates to a router index."""
        for r, (rx, ry) in enumerate(self.router_coords):
            if rx == target_x and ry == target_y:
                return r
        raise ValueError(f"No router at ({target_x}, {target_y})")

    async def a_queue_append(self, r: int, packet: list) -> None:
        """Append a received packet to a_queues[r]. Blocks when queue is full."""
        while self.a_queue_depth and len(self.a_queues[r]) >= self.a_queue_depth:
            await self.tick()
        self.a_queues[r].append(packet)

    @abstractmethod
    def _make_future(self):
        """Create an awaitable future with a .set(value) method."""

    @abstractmethod
    async def tick(self, n: int = 1) -> None:
        """Advance the clock by n cycles."""

    @abstractmethod
    def start_soon(self, coro):
        """Start a coroutine to run concurrently. Returns a handle with .cancel()."""
