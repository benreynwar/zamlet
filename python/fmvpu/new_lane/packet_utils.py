from typing import List
from collections import deque
import logging
from random import Random

from cocotb.triggers import RisingEdge, ReadOnly

from fmvpu.new_lane.instructions import PacketHeader
from fmvpu.new_lane.lane_params import LaneParams


logger = logging.getLogger(__name__)


class PacketDriver:
    """Drives packets into a single network input"""
    
    def __init__(self, dut, seed, valid_signal, ready_signal, data_signal, isheader_signal, p_valid=0.5):
        self.dut = dut
        self.valid_signal = valid_signal
        self.ready_signal = ready_signal
        self.data_signal = data_signal
        self.isheader_signal = isheader_signal
        self.packet_queue: deque[List[int]] = deque()
        self.p_valid = p_valid
        self.rnd = Random(seed)
        
    def add_packet(self, packet: List[int]):
        """Add packet to the queue"""
        self.packet_queue.append(packet)
        
    async def drive_packets(self):
        await RisingEdge(self.dut.clock)
        """Drive packets from queue into the network input"""

        while True:
            if self.packet_queue:
                packet = self.packet_queue.popleft()
                
                for index, word in enumerate(packet):
                    # Set data, isheader, and valid
                    self.data_signal.value = word
                    self.isheader_signal.value = 1 if index == 0 else 0  # First word is header
                    while self.rnd.random() > self.p_valid:
                        self.valid_signal.value = 0
                        await RisingEdge(self.dut.clock)

                    self.valid_signal.value = 1
                    
                    # Wait for ready or just send
                    while True:
                        await ReadOnly()
                        if self.ready_signal.value == 1:
                            break
                        await RisingEdge(self.dut.clock)
                    await RisingEdge(self.dut.clock)
                    self.valid_signal.value = 0
            await RisingEdge(self.dut.clock)


class PacketReceiver:
    """Receives packets from a single network output"""
    
    def __init__(self, dut, seed: int, valid_signal, ready_signal, data_signal, isheader_signal, params: LaneParams = LaneParams(), p_ready=0.5, name=''):
        self.dut = dut
        self.valid_signal = valid_signal
        self.ready_signal = ready_signal
        self.data_signal = data_signal
        self.isheader_signal = isheader_signal
        self.params = params
        self.received_packets: deque[List[int]] = deque()
        self.rnd = Random(seed)
        self.p_ready = p_ready
        self.name = name

    def has_packet(self) -> bool:
        return len(self.received_packets) > 0
        
    def get_packet(self) -> List[int]:
        """Get the next received packet"""
        if self.received_packets:
            return self.received_packets.popleft()
        return None
        
    async def receive_packets(self):
        """Receive packets from the network output"""
        self.ready_signal.value = 1
        
        current_packet = None
        remaining_words = 0
        
        while True:
            await RisingEdge(self.dut.clock)
            if self.rnd.random() > self.p_ready:
                self.ready_signal.value = 0
            else:
                self.ready_signal.value = 1
            await ReadOnly()
            if (self.valid_signal.value == 1) and (self.ready_signal.value == 1):
                word = int(self.data_signal.value)

                if current_packet is None:
                    assert self.isheader_signal.value == 1, "Expected header bit to be set for first word"
                    header = PacketHeader.from_word(word)
                    remaining_words = header.length
                    logger.info(f'{self.name}: Got a packet header with length {header.length} dest ({header.dest_x}, {header.dest_y})')
                    current_packet = [word]
                else:
                    current_packet.append(word)
                    remaining_words -= 1
                if remaining_words == 0:
                    self.received_packets.append(current_packet)
                    current_packet = None

