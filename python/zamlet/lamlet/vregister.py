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
    Processes in chunks of j_in_l elements when n_elements > j_in_l.

    Returns: completion_sync_ident of the last chunk
    """
    j_in_l = lamlet.params.j_in_l
    n_active = n_elements - start_index
    completion_sync_ident = None

    for chunk_offset in range(0, n_active, j_in_l):
        chunk_n = min(j_in_l, n_active - chunk_offset)
        instr_ident = await ident_query.get_instr_ident(lamlet)

        kinstr = RegGather(
            vd=vd,
            vs2=vs2,
            vs1=vs1,
            start_index=start_index + chunk_offset,
            n_elements=chunk_n,
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
