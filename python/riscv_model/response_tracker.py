import logging
from dataclasses import dataclass
from typing import List, Dict, Deque, Awaitable, Tuple

from runner import Future


logger = logging.getLogger(__name__)

@dataclass
class MethodAndFuture:
    # We will call this method (the lone argument is the received packet)
    method: Awaitable
    # When the method completes we return this future with the 
    # output set to the futures result.
    future: Future

@dataclass
class SrcCoordsResponseState:
    """
    We expect a bunch of responses all with different packet
    sources.
    """
    ident: int
    src_coords_to_maf: Dict[Tuple[int, int], MethodAndFuture]
    label: str


@dataclass
class DstCoordsResponseState:
    """
    We expect a bunch of responses all with different packet
    targets.
    """
    ident: int
    dst_coords_to_maf: Dict[Tuple[int, int], MethodAndFuture]
    label: str


@dataclass
class CountResponseState:
    """
    We expect a certain number of responses.
    """
    ident: int
    mafs: Deque[MethodAndFuture]
    label: str


class ResponseTracker:
    """
    This takes care of keeping track of who we are expecting responses from.
    """

    def __init__(self, clock, params):
        self.clock = clock
        self.params = params
        self.next_response_ident = 0

        self.waiting_by_ident = {}
        self.waiting_by_label = {}

        self.packets = []

    async def run_maf(self, maf: MethodAndFuture, packet):
        if maf.method is not None:
            result = await maf.method(packet)
        else:
            result = None
        maf.future.set_result(result)

    def check_packet(self, packet):
        self.packets.append(packet)
        header = packet[0]
        response_ident = header.ident
        assert response_ident in self.waiting_by_ident
        response_state = self.waiting_by_ident[response_ident]
        assert response_state.ident == response_ident
        dst_coords = (header.target_x, header.target_y)
        if isinstance(response_state, SrcCoordsResponseState):
            src_coords = (header.source_x, header.source_y)
            maf = response_state.src_coords_to_maf.pop(src_coords)
            self.clock.create_task(self.run_maf(maf, packet))
            if not response_state.src_coords_to_maf:
                self.waiting_by_ident.pop(response_ident)
                self.waiting_by_label.pop(response_state.label)
        elif isinstance(response_state, DstCoordsResponseState):
            dst_coords = (header.target_x, header.target_y)
            maf = response_state.dst_coords_to_maf.pop(dst_coords)
            self.clock.create_task(self.run_maf(maf, packet))
            if not response_state.dst_coords_to_maf:
                self.waiting_by_ident.pop(response_ident)
                self.waiting_by_label.pop(response_state.label)
        elif isinstance(response_state, CountResponseState):
            maf = response_state.mafs.pop(0)
            self.clock.create_task(self.run_maf(maf, packet))
            if not response_state.mafs:
                self.waiting_by_ident.pop(response_ident)
                self.waiting_by_label.pop(response_state.label)
        else:
            raise ValueError()

    async def get_ident(self):
        ident = self.next_response_ident
        while ident in self.waiting_by_ident:
            await self.clock.next_cycle
        assert ident not in self.waiting_by_ident
        return ident

    def register(self, response_state):
        assert response_state.ident not in self.waiting_by_ident
        assert response_state.label not in self.waiting_by_label
        self.waiting_by_ident[response_state.ident] = response_state
        self.waiting_by_label[response_state.label] = response_state
        self.next_response_ident = (self.next_response_ident + 1) % self.params.n_response_idents

    async def register_srcs(self, src_coords_to_methods, label=''):
        ident = await self.get_ident()
        src_coords_to_maf = {}
        src_coords_to_future = {}
        for src_coords, method in src_coords_to_methods.items():
            future = self.clock.create_future()
            src_coords_to_maf[src_coords] = MethodAndFuture(method, future)
            src_coords_to_future[src_coords] = future
        response_state = SrcCoordsResponseState(
                ident=ident, src_coords_to_maf=src_coords_to_maf, label=label)
        self.register(response_state)
        return ident, src_coords_to_future

    async def register_dsts(self, dst_coords_to_methods, label=''):
        ident = await self.get_ident()
        dst_coords_to_maf = {}
        dst_coords_to_future = {}
        for dst_coords, method in dst_coords_to_methods.items():
            future = self.clock.create_future()
            dst_coords_to_maf[dst_coords] = MethodAndFuture(method, future)
            dst_coords_to_future[dst_coords] = future
        response_state = DstCoordsResponseState(
                ident=ident, dst_coords_to_maf=dst_coords_to_maf, label=label)
        self.register(response_state)
        return ident, dst_coords_to_future

    async def register_count(self, methods, label=''):
        ident = await self.get_ident()
        mafs = []
        futures = []
        for method in methods:
            future = self.clock.create_future()
            mafs.append(MethodAndFuture(method, future))
            futures.append(future)
        response_state = CountResponseState(ident=ident, mafs=mafs, label=label)
        self.register(response_state)
        return ident, futures
