"""Decorator for RISC-V instruction update_state methods.

Wraps the body with a RISCV_INSTR span so that scalar register writes and
any child kinstrs can attach to it. The span is FIRE_AND_FORGET and
auto-completes once all children (kinstrs, futures, messages) finish.

Usage:

    @riscv_instr
    async def update_state(self, s: 'Oamlet', span_id: int):
        s.scalar.write_reg(self.rd, result_bytes, span_id)
        s.pc += 4
"""

import functools
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from zamlet.monitor import CompletionType, SpanType

if TYPE_CHECKING:
    from zamlet.oamlet.oamlet import Oamlet


UpdateStateFn = Callable[[Any, 'Oamlet', int], Awaitable[None]]
WrappedUpdateStateFn = Callable[[Any, 'Oamlet'], Awaitable[None]]


def riscv_instr(fn: UpdateStateFn) -> WrappedUpdateStateFn:
    @functools.wraps(fn)
    async def wrapper(self: Any, s: 'Oamlet') -> None:
        span_id = s.monitor.create_span(
            span_type=SpanType.RISCV_INSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            pc=hex(s.pc),
            instr=str(self),
        )
        try:
            await fn(self, s, span_id)
        finally:
            s.monitor.finalize_children(span_id)
    return wrapper
