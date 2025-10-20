from dataclasses import dataclass
from collections import deque

from addresses import CacheState
from params import LamletParams
from jamlet import Jamlet


class KamletTLB:

    def __init__(self, params: LamletParams):
        self.params = params
        self.pages = {}

    def allocate_page(self, global_address, local_address, is_vpu, element_width):
        '''
        Associate a page of the global address space with a page in the local vpu
        address space or a page in the local scalar address space.
        Also associate that page (for vpu pages) with an element_width. This will
        effect how the global page gets arranged inside the local page.
        '''
        assert size % self.params.page_size == 0
        for index in range(size//self.params.page_size):
            logical_page_address = address + index * self.params.page_bytes
            physical_page_address = self.get_lowest_free_page(is_vpu)
            assert logical_page_address not in self.pages
            self.pages[logical_address] = PageInfo(
                global_address=global_address,
                is_vpu=is_vpu,
                local_address=local_address,
                element_width=element_width
                )

    def release_page(self, local_address):
        assert local_address in pages
        del self.pages[local_address]

    def get_page_info(self, address):
        assert address % self.params.page_bytes == 0
        return self.pages[address]


@dataclass
class KamletCacheLineInfo:
    # What is the base address of this cache line
    # in the local memory
    local_address: int
    # M: modified (we're written but not updated memory)
    # S: shared (it's a copy of memory)
    # I: it's invalid data
    cache_state: CacheState
    # Can we make local changes to the cache state or is
    # it globally managed.
    locally_managed: bool


class KamletScoreBoard:

    def __init__(self, params: LamletParams):
        self.registers_updating = [False] * self.params.n_vregs
        # Instructions that produce results are put 
        max_pipeline_length = 4
        self.in_flight_funcs = [[] for i in range(max_pipeline_length)]


class Kamlet:

    def __init__(self, params: LamletParams, min_x: int, min_y: int):
        self.params = params
        self.min_x = min_x
        self.min_y = min_y
        self.n_columns = params.j_cols
        self.n_rows = params.j_rows
        self.n_jamlets = self.n_columns * self.n_rows
        
        self.jamlets = [Jamlet(params, min_x+index % self.n_columns, min_y+index//self.n_columns)
                        for index in range(self.n_jamlets)]

        n_cache_lines = params.jamlet_sram_bytes * params.j_rows * params.j_cols // params.cache_line_bytes

        self.cache_info = [
            KamletCacheLineInfo(None, CacheState.I, False) for i in range(n_cache_lines)]

        self.tlb = KamletTLB(params)

        self.instruction_queue = deque()

    def get_jamlet(self, x, y):
        assert self.min_x <= x < self.min_x + self.n_columns
        assert self.min_y <= y < self.min_y + self.n_rows
        jamlet = self.jamlets[(y - self.min_y) * self.n_columns + (x - self.min_x)]
        assert jamlet.x == x
        assert jamlet.y == y
        return jamlet

    def step(self):

        for jamlet in self.jamlets:
            jamlet.step()

        # If we have an instruction then do it
        if self.instruction_queue:
            instr = self.instruction_queue[0]
            instr.update_kamlet(self)

        # Get received instructions from jamlets
        for index, jamlet in enumerate(self.jamlets):
            if jamlet.instruction_buffer is not None:
                if index == 0:
                    self.instruction_queue.append(jamlet.instruction_buffer)
                    assert len(self.instruction_queue) < self.params.instruction_queue_length
                jamlet.instruction_buffer = None
