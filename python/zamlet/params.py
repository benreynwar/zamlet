from dataclasses import dataclass


@dataclass
class LamletParams:
    #k_cols: int = 2
    #k_rows: int = 2

    #j_cols: int = 2
    #j_rows: int = 2

    k_cols: int = 2
    k_rows: int = 1

    j_cols: int = 1
    j_rows: int = 1

    n_vregs: int = 40
    vlines_in_cache_line: int = 2
    word_bytes: int = 8
    page_bytes: int = 1 << 10 # 12
    scalar_memory_bytes: int = 8 << 20
    kamlet_memory_bytes: int = 1 << 20
    #jamlet_sram_bytes: int = 1 << 10
    jamlet_sram_bytes: int = 1 << 6
    tohost_addr: int = 0x80001000
    fromhost_addr: int = 0x80001040
    receive_buffer_depth: int = 16
    router_output_buffer_length: int = 2
    router_input_buffer_length: int = 2
    instruction_queue_length: int = 16
    n_channels: int = 2


    instruction_buffer_length: int = 16
    instructions_in_packet: int = 4
    n_response_idents: int = 32
    #n_waiting: int = 16
    n_response_tags: int = 8
    max_response_tags: int = 128 # 7 bits

    # The number of outstanding instructions or responses waiting
    n_items: int = 16
    # Number of witem slots reserved for message handlers (not used by kinstructions)
    n_items_reserved: int = 8
    # The number of outstanding cache read_line and write_line allowed
    n_cache_requests: int = 16
    # Number of gathering slots in memlet for WRITE_LINE_READ_LINE operations
    n_memlet_gathering_slots: int = 4

    # Ordered indexed operation buffer parameters (for scalar memory targets)
    n_ordered_buffers: int = 2
    ordered_buffer_capacity: int = 16

    def __post_init__(self):
        # Page must be bigger than a vector
        assert self.page_bytes > 0
        assert self.page_bytes % self.maxvl_bytes == 0
        # Vector must be a multiple of words per jamlet
        assert self.maxvl_bytes > 0
        assert self.maxvl_bytes % (self.k_cols*self.k_rows*self.j_cols*self.j_rows*self.word_bytes) == 0
        # Cache line must be bigger than 1 word per jamlet in a kamlet
        assert self.cache_line_bytes > 0
        assert self.cache_line_bytes % (self.j_cols*self.j_rows*self.word_bytes) == 0
        # Page must be bigger than a cache line
        assert self.page_bytes >= self.k_in_l * self.cache_line_bytes
        assert self.page_bytes % (self.k_in_l * self.cache_line_bytes) == 0
        # Sane scalar memory
        assert self.scalar_memory_bytes > self.cache_line_bytes
        assert self.scalar_memory_bytes % self.cache_line_bytes == 0
        # Sane kamlet memory
        assert self.kamlet_memory_bytes > self.cache_line_bytes
        assert self.kamlet_memory_bytes % self.cache_line_bytes == 0

    @property
    def cache_line_bytes(self) -> int:
        return self.vline_bytes * self.vlines_in_cache_line // self.k_in_l

    @property
    def k_vline_bytes(self) -> int:
        return self.j_in_k * self.word_bytes

    @property
    def maxvl_bytes(self):
        return self.j_in_l * self.word_bytes

    @property
    def k_in_l(self):
        return self.k_cols * self.k_rows

    @property
    def j_in_k(self):
        return self.j_cols * self.j_rows

    @property
    def j_in_l(self):
        return self.j_in_k * self.k_in_l

    @property
    def vline_bytes(self):
        return self.j_in_l * self.word_bytes

    @property
    def send_read_line_j_index(self):
        return 1 % self.j_in_k
