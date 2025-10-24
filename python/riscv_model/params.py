from dataclasses import dataclass


@dataclass
class LamletParams:
    k_cols: int = 2
    k_rows: int = 1

    j_cols: int = 1
    j_rows: int = 2

    n_vregs: int = 40
    cache_line_bytes: int = 32 #64
    word_bytes: int = 8
    page_bytes: int = 1 << 10 # 12
    scalar_memory_bytes: int = 3 << 20
    kamlet_memory_bytes: int = 1 << 20
    jamlet_sram_bytes: int = 1 << 6
    tohost_addr: int = 0x80001000
    fromhost_addr: int = 0x80001040
    receive_buffer_depth: int = 16
    router_output_buffer_length: int = 2
    router_input_buffer_length: int = 2
    instruction_queue_length: int = 16

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
