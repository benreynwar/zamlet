"""
Vector register-to-register operations for the lamlet.

Handles operations like vrgather that are register-to-register but require
cross-jamlet communication and synchronization.
"""

import logging
from typing import TYPE_CHECKING

from zamlet.addresses import WordOrder
from zamlet.transactions.reg_gather import RegGather
from zamlet.lamlet import ident_query

if TYPE_CHECKING:
    from zamlet.lamlet.lamlet import Lamlet

logger = logging.getLogger(__name__)


async def vrgather(lamlet: 'Lamlet', vd: int, vs2: int, vs1: int,
                   start_index: int, n_elements: int,
                   index_ew: int, data_ew: int,
                   word_order: WordOrder, vlmax: int,
                   mask_reg: int | None, parent_span_id: int) -> int:
    """
    Execute vrgather.vv: vd[i] = (vs1[i] >= VLMAX) ? 0 : vs2[vs1[i]]

    Gathers elements from vs2 using indices from vs1 into vd.

    Returns: completion_sync_ident that can be awaited with wait_for_sync()
    """
    instr_ident = await ident_query.get_instr_ident(lamlet)

    kinstr = RegGather(
        vd=vd,
        vs2=vs2,
        vs1=vs1,
        start_index=start_index,
        n_elements=n_elements,
        index_ew=index_ew,
        data_ew=data_ew,
        word_order=word_order,
        vlmax=vlmax,
        mask_reg=mask_reg,
        instr_ident=instr_ident,
    )
    await lamlet.add_to_instruction_buffer(kinstr, parent_span_id)
    kinstr_span_id = lamlet.monitor.get_kinstr_span_id(instr_ident)

    # Create sync span at lamlet level (before KINSTR children are finalized)
    completion_sync_ident = instr_ident
    lamlet.monitor.create_sync_local_span(completion_sync_ident, 0, -1, kinstr_span_id)
    lamlet.synchronizer.local_event(completion_sync_ident)

    return completion_sync_ident
