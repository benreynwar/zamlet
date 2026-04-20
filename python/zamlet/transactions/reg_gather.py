"""
Vector register gather (vrgather.vv): vd[i] = (vs1[i] >= VLMAX) ? 0 : vs2[vs1[i]]

RF-to-RF gather: reads from arbitrary register positions based on index vector.
This is the inverse of RegScatter (used by vcompress).

Supports different element widths for index and data:
- vrgather.vv: index_ew = data_ew = SEW
- vrgatherei16.vv: index_ew = 16, data_ew = SEW

The routing/sync machinery is shared with RegSlide via the RegPermute base;
this file only supplies the vs1-backed index read.
"""

from typing import TYPE_CHECKING
from dataclasses import dataclass
import logging

from zamlet.transactions.reg_permute import RegPermute, WaitingRegPermute

if TYPE_CHECKING:
    from zamlet.jamlet.jamlet import Jamlet

logger = logging.getLogger(__name__)


class WaitingRegGather(WaitingRegPermute):
    """Waiting item for vector register gather (vrgather.vv)."""

    def __init__(self, params, instr: 'RegGather', rf_ident: int,
                 dst_pregs: dict[int, int], vs1_pregs: dict[int, int],
                 vs2_pregs: dict[int, int], mask_preg: int | None):
        super().__init__(
            params=params, instr=instr, rf_ident=rf_ident,
            dst_pregs=dst_pregs, vs2_pregs=vs2_pregs, mask_preg=mask_preg,
        )
        self.vs1_pregs = vs1_pregs

    def _extra_read_regs(self) -> list[int]:
        return list(self.vs1_pregs.values())

    def _compute_src_index(self, jamlet: 'Jamlet', dst_e: int) -> int:
        """Read the index value from vs1[dst_e].

        Uses index_ew since vs1 uses index element width.
        """
        instr = self.item
        wb = jamlet.params.word_bytes
        ew = instr.index_ew
        eb = ew // 8

        elements_in_vline = jamlet.params.vline_bytes * 8 // ew
        v = dst_e // elements_in_vline
        ve = dst_e % elements_in_vline
        we = ve // jamlet.params.j_in_l

        preg = self.vs1_pregs[v]
        byte_in_word = (we * eb) % wb

        word_data = jamlet.rf_slice[preg * wb: (preg + 1) * wb]
        return int.from_bytes(word_data[byte_in_word:byte_in_word + eb],
                              byteorder='little', signed=False)


@dataclass
class RegGather(RegPermute):
    """Vector register gather instruction.

    Each element i of vd gets the value vs2[vs1[i]], or 0 if vs1[i] >= vlmax.

    index_ew: element width for vs1 (indices).
    data_ew (from RegPermute): element width for vs2 (source data) and vd.
    """
    vs1: int
    index_ew: int

    def _compute_extra_src_pregs(self, kamlet, dst_elements_in_vline) -> dict[int, int]:
        params = kamlet.params
        index_elements_in_vline = params.vline_bytes * 8 // self.index_ew

        vs1_start_vline = self.start_index // index_elements_in_vline
        vs1_end_vline = (self.start_index + self.n_elements - 1) // index_elements_in_vline

        return {
            v: kamlet.r(self.vs1 + v)
            for v in range(vs1_start_vline, vs1_end_vline + 1)
        }

    def _create_waiting_item(self, kamlet, rf_ident: int, renamed) -> WaitingRegGather:
        return WaitingRegGather(
            params=kamlet.params, instr=self, rf_ident=rf_ident,
            dst_pregs=renamed.dst_pregs,
            vs1_pregs=renamed.src_pregs,
            vs2_pregs=renamed.src2_pregs,
            mask_preg=renamed.mask_preg,
        )
