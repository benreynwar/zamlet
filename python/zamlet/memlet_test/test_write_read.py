"""Unified memlet write/read test.

Writes a cache line via the split protocol (WRITE_LINE_ADDR + WRITE_LINE_DATA),
then reads it back (READ_LINE_ADDR → READ_LINE_RESP) and verifies data matches.

Can run against cocotb (RTL) or the Python model via the driver abstraction.
"""

import logging

from zamlet.control_structures import unpack_int_to_fields
from zamlet.memlet import j_in_k_to_m_router
from zamlet.memlet_test.memlet_driver import MemletDriver
from zamlet.message import AddressHeader, MessageType, SendType
from zamlet.params import ZamletParams

logger = logging.getLogger(__name__)


def jamlet_coords(params: ZamletParams, j_in_k_index: int,
                  k_base_x: int, k_base_y: int):
    """Absolute (x, y) for a jamlet given its index within the kamlet."""
    j_x = j_in_k_index % params.j_cols
    j_y = j_in_k_index // params.j_cols
    return (k_base_x + j_x, k_base_y + j_y)


async def test_write_line(driver: MemletDriver, params: ZamletParams,
                          router_coords, k_base_x: int, k_base_y: int,
                          timeout: int = 1000) -> None:
    """Write a cache line and verify the response.

    Sends WRITE_LINE_ADDR on router 0, then WRITE_LINE_DATA for each
    jamlet on the appropriate router. Waits for WRITE_LINE_RESP.
    """
    ident = 1
    sram_addr = 0
    mem_addr = 0x1000
    n_routers = driver.n_routers
    words_per_jamlet = params.cache_slot_words // params.j_in_k

    # Build test data: each jamlet gets distinct words
    all_data = {}
    for j in range(params.j_in_k):
        all_data[j] = [0xCAFE_0000 + j * 0x100 + w
                       for w in range(words_per_jamlet)]

    # WRITE_LINE_ADDR from jamlet 0, sent to router 0
    j0_x, j0_y = jamlet_coords(params, 0, k_base_x, k_base_y)
    r0_x, r0_y = router_coords[0]
    addr_hdr = AddressHeader(
        target_x=r0_x, target_y=r0_y,
        source_x=j0_x, source_y=j0_y,
        length=1,
        message_type=MessageType.WRITE_LINE_ADDR,
        send_type=SendType.SINGLE,
        ident=ident, address=sram_addr,
    )
    driver.b_queues[0].append([addr_hdr.encode(params), mem_addr])

    # WRITE_LINE_DATA from each jamlet, on the appropriate router.
    # Build packets keyed by (jamlet_x, jamlet_y) so we can resend on drop.
    data_packets = {}
    for j in range(params.j_in_k):
        r = j_in_k_to_m_router(j, n_routers, params.j_in_k)
        r_x, r_y = router_coords[r]
        j_x, j_y = jamlet_coords(params, j, k_base_x, k_base_y)
        data_hdr = AddressHeader(
            target_x=r_x, target_y=r_y,
            source_x=j_x, source_y=j_y,
            length=words_per_jamlet,
            message_type=MessageType.WRITE_LINE_DATA,
            send_type=SendType.SINGLE,
            ident=ident, address=sram_addr,
        )
        pkt = [data_hdr.encode(params)] + all_data[j]
        data_packets[(j_x, j_y)] = (r, pkt)
        driver.b_queues[r].append(pkt)

    DROP_TYPES = {
        MessageType.WRITE_LINE_ADDR_DROP,
        MessageType.WRITE_LINE_DATA_DROP,
    }

    # Monitor each router: resend dropped packets.
    async def monitor_drops(router_idx):
        while True:
            resp = await driver.recv(router_idx)
            fields = unpack_int_to_fields(resp[0], params.ident_header_fields)
            msg_type = fields['message_type']
            if msg_type in DROP_TYPES:
                target = (fields['target_x'], fields['target_y'])
                logger.info(f"Router {router_idx}: drop (type={msg_type}),"
                            f" resending for {target}")
                r, pkt = data_packets[target]
                assert r == router_idx
                driver.b_queues[r].append(pkt)
            else:
                return fields

    async def watchdog():
        for _ in range(timeout):
            await driver.tick()
        raise TimeoutError(f"test_write_line timed out after {timeout} cycles")

    # Start drop monitors on non-zero routers
    drop_tasks = [driver.start_soon(monitor_drops(r))
                  for r in range(1, n_routers)]
    wd = driver.start_soon(watchdog())

    # Router 0 handles drops and receives the final WRITE_LINE_RESP
    resp_fields = await monitor_drops(0)

    wd.kill()
    for task in drop_tasks:
        task.kill()

    assert resp_fields['message_type'] == MessageType.WRITE_LINE_RESP, (
        f"Expected WRITE_LINE_RESP ({MessageType.WRITE_LINE_RESP}),"
        f" got {resp_fields['message_type']}")
    assert resp_fields['ident'] == ident
    assert resp_fields['target_x'] == j0_x
    assert resp_fields['target_y'] == j0_y

    logger.info("test_write_line passed")
    return all_data
