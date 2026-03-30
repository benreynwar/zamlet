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


def jamlet_routing_coords(params: ZamletParams, j_in_k_index: int,
                          k_base_x: int, k_base_y: int):
    """Routing (x, y) for a jamlet given its index within the kamlet."""
    return (k_base_x + j_in_k_index % params.j_cols,
            k_base_y + j_in_k_index // params.j_cols)


async def write_cache_line(driver: MemletDriver, params: ZamletParams,
                          router_coords, k_base_x: int, k_base_y: int,
                          ident: int, mem_addr: int, sram_addr: int,
                          data: dict) -> None:
    """Write a cache line and verify the response.

    Sends WRITE_LINE_ADDR on router 0, then WRITE_LINE_DATA for each
    jamlet on the appropriate router. Waits for WRITE_LINE_RESP.

    data: dict mapping jamlet index to list of words.
    """
    n_routers = driver.n_routers
    words_per_jamlet = params.cache_slot_words_per_jamlet

    # WRITE_LINE_ADDR from jamlet 0, sent to router 0
    j0_x, j0_y = jamlet_routing_coords(params, 0, k_base_x, k_base_y)
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
        j_x, j_y = jamlet_routing_coords(params, j, k_base_x, k_base_y)
        data_hdr = AddressHeader(
            target_x=r_x, target_y=r_y,
            source_x=j_x, source_y=j_y,
            length=words_per_jamlet,
            message_type=MessageType.WRITE_LINE_DATA,
            send_type=SendType.SINGLE,
            ident=ident, address=sram_addr,
        )
        pkt = [data_hdr.encode(params)] + data[j]
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

    # Start drop monitors on non-zero routers
    drop_tasks = [driver.start_soon(monitor_drops(r))
                  for r in range(1, n_routers)]

    # Router 0 handles drops and receives the final WRITE_LINE_RESP
    resp_fields = await monitor_drops(0)

    for task in drop_tasks:
        task.cancel()

    assert resp_fields['message_type'] == MessageType.WRITE_LINE_RESP, (
        f"Expected WRITE_LINE_RESP ({MessageType.WRITE_LINE_RESP}),"
        f" got {resp_fields['message_type']}")
    assert resp_fields['ident'] == ident
    assert resp_fields['target_x'] == j0_x
    assert resp_fields['target_y'] == j0_y

    logger.info("write_cache_line complete")


async def read_cache_line(driver: MemletDriver, params: ZamletParams,
                         router_coords, k_base_x: int, k_base_y: int,
                         ident: int, mem_addr: int, sram_addr: int) -> dict:
    """Read a cache line and return the data keyed by jamlet index.

    Sends READ_LINE_ADDR on router 0, collects READ_LINE_RESP for each
    jamlet, retries on READ_LINE_ADDR_DROP.
    """
    words_per_jamlet = params.cache_slot_words_per_jamlet

    j0_x, j0_y = jamlet_routing_coords(params, 0, k_base_x, k_base_y)
    r0_x, r0_y = router_coords[0]

    def build_addr_packet():
        addr_hdr = AddressHeader(
            target_x=r0_x, target_y=r0_y,
            source_x=j0_x, source_y=j0_y,
            length=1,
            message_type=MessageType.READ_LINE_ADDR,
            send_type=SendType.SINGLE,
            ident=ident, address=sram_addr,
        )
        return [addr_hdr.encode(params), mem_addr]

    driver.b_queues[0].append(build_addr_packet())

    received_data = {}

    while len(received_data) < params.j_in_k:
        resp = await driver.recv(0)
        fields = unpack_int_to_fields(resp[0], params.address_header_fields)
        msg_type = fields['message_type']

        if msg_type == MessageType.READ_LINE_ADDR_DROP:
            logger.info("READ_LINE_ADDR_DROP, resending")
            driver.b_queues[0].append(build_addr_packet())
            continue

        assert msg_type == MessageType.READ_LINE_RESP, (
            f"Expected READ_LINE_RESP or READ_LINE_ADDR_DROP, got {msg_type}")
        assert fields['ident'] == ident

        j_in_k_x = fields['target_x'] - k_base_x
        j_in_k_y = fields['target_y'] - k_base_y
        j_index = j_in_k_y * params.j_cols + j_in_k_x
        assert 0 <= j_index < params.j_in_k, (
            f"Bad jamlet index {j_index} from target"
            f" ({fields['target_x']}, {fields['target_y']})")
        assert j_index not in received_data, (
            f"Duplicate READ_LINE_RESP for jamlet {j_index}")

        data_words = resp[1:]
        assert len(data_words) == words_per_jamlet, (
            f"Expected {words_per_jamlet} data words, got {len(data_words)}")
        received_data[j_index] = data_words
        logger.info(f"READ_LINE_RESP for jamlet {j_index}:"
                    f" {[f'0x{w:x}' for w in data_words]}")

    logger.info("read_cache_line complete")
    return received_data


async def test_write_read(driver: MemletDriver, params: ZamletParams,
                          router_coords, k_base_x: int, k_base_y: int,
                          timeout: int = 1000) -> None:
    """Write a cache line, read it back, and verify data matches."""
    mem_addr = 0x1000
    sram_addr = 0
    words_per_jamlet = params.cache_slot_words_per_jamlet

    data = {}
    for j in range(params.j_in_k):
        data[j] = [0xCAFE_0000 + j * 0x100 + w
                   for w in range(words_per_jamlet)]

    async def watchdog():
        for _ in range(timeout):
            await driver.tick()
        raise TimeoutError(f"test_write_read timed out after {timeout} cycles")

    wd = driver.start_soon(watchdog())

    await write_cache_line(
        driver, params, router_coords, k_base_x, k_base_y,
        ident=1, mem_addr=mem_addr, sram_addr=sram_addr, data=data)

    read_data = await read_cache_line(
        driver, params, router_coords, k_base_x, k_base_y,
        ident=2, mem_addr=mem_addr, sram_addr=sram_addr)

    for j in range(params.j_in_k):
        assert j in read_data, f"Missing READ_LINE_RESP for jamlet {j}"
        for w in range(words_per_jamlet):
            assert read_data[j][w] == data[j][w], (
                f"Jamlet {j} word {w}: expected 0x{data[j][w]:x},"
                f" got 0x{read_data[j][w]:x}")

    wd.cancel()
    logger.info("test_write_read passed")
