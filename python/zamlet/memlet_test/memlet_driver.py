"""Abstract driver interface for memlet tests.

Packets are lists of [Header, payload...] matching the python model's
internal format. Each router has its own b_queue (input) and a_queue
(output).

Usage:
  await driver.reset()
  driver.start()
  driver.b_queues[router_idx].append([header, body0, ...])
  response = await driver.recv(router_idx)
"""

from abc import ABC, abstractmethod
from collections import deque
from typing import List
import logging


logger = logging.getLogger(__name__)


class MemletDriver(ABC):

    def __init__(self, n_routers: int):
        self.n_routers = n_routers
        self.b_queues = [deque() for _ in range(n_routers)]
        self.a_queues = [deque() for _ in range(n_routers)]

    @abstractmethod
    def start(self) -> None:
        """Start background coroutines that drive b_queues and drain a_queues."""

    @abstractmethod
    async def reset(self) -> None:
        """Reset the memlet and wait for it to be ready."""

    async def recv(self, router_idx: int = 0,
                   timeout: int = 10000) -> list:
        """Wait for a packet in a_queues[router_idx] and return it."""
        for _ in range(timeout):
            if self.a_queues[router_idx]:
                return self.a_queues[router_idx].popleft()
            await self.tick()
        raise TimeoutError(
            f"No packet on router {router_idx} after {timeout} cycles")

    @abstractmethod
    async def tick(self, n: int = 1) -> None:
        """Advance the clock by n cycles."""

    @abstractmethod
    def start_soon(self, coro):
        """Start a coroutine to run concurrently. Returns a handle with .cancel()."""
