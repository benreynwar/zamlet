"""
Vector register slide (vslideup.vx/.vi, vslidedown.vx/.vi):

- slideup:   vd[i] = vs2[i - offset] for max(vstart, offset) <= i < vl.
             Elements with i < offset are unchanged (prestart / undisturbed).
- slidedown: vd[i] = vs2[i + offset] for vstart <= i < vl.
             i + offset >= vlmax writes 0.

RF-to-RF like RegGather, but the source element index for each destination
element is computed (i +/- offset) rather than read from an index register.
Routing/sync machinery is shared via the RegPermute base; this file only
supplies the scalar-offset index computation.
"""

from typing import TYPE_CHECKING
from dataclasses import dataclass
from enum import Enum
import logging

from zamlet.transactions.reg_permute import RegPermute, WaitingRegPermute

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet

logger = logging.getLogger(__name__)


class SlideDirection(Enum):
    UP = "up"
    DOWN = "down"


class WaitingRegSlide(WaitingRegPermute):
    """Waiting item for vector register slide."""

    def _compute_src_index(self, jamlet: 'Jamlet', dst_e: int) -> int:
        instr = self.item
        if instr.direction == SlideDirection.UP:
            # Lamlet guarantees start_index >= offset, so dst_e - offset >= 0.
            return dst_e - instr.offset
        else:
            # DOWN: may exceed vlmax -> base class writes 0.
            return dst_e + instr.offset


@dataclass
class RegSlide(RegPermute):
    """Vector register slide instruction.

    slideup:   vd[i] = vs2[i - offset]
    slidedown: vd[i] = vs2[i + offset], 0 when i + offset >= vlmax
    """
    offset: int
    direction: SlideDirection

    def _create_waiting_item(self, kamlet, rf_ident: int, renamed) -> WaitingRegSlide:
        return WaitingRegSlide(
            params=kamlet.params, instr=self, rf_ident=rf_ident,
            dst_pregs=renamed.dst_pregs,
            vs2_pregs=renamed.src2_pregs,
            mask_preg=renamed.mask_preg,
        )
