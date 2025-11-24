import logging
import asyncio
import random

from router import Router
from runner import Clock
from params import LamletParams
from message import Header, MessageType, SendType, Direction


logger = logging.getLogger(__name__)


def make_packet():
    length = random.randint(1, 10)
    header = Header(
            target_x = 4,
            target_y = 4,
            source_x = -4,
            source_y = -4,
            ident=0,
            length=length,
            message_type=MessageType.SEND,
            send_type=SendType.BROADCAST,
            )
    payload = [random.randint(0, 10) for x in range(length-1)]


    return [header] + payload


async def update(clock, r):
    while True:
        await clock.next_update
        r.update()


async def get_packet(clock, output_buffer):
    while True:
        if output_buffer:
            header = output_buffer.popleft()
            assert isinstance(header, Header)
            break
        else:
            logger.info(f'Nothing in output buffer {output_buffer}')
        await clock.next_cycle
    remaining = header.length - 1
    packet = [header]
    while remaining > 0:
        await clock.next_cycle
        for i in range(random.randint(1, 20)):
            await clock.next_cycle
        if output_buffer:
            word = output_buffer.popleft()
            assert not isinstance(word, Header)
            packet.append(word)
            remaining -= 1
        else:
            logger.info(f'Nothing in output buffer {output_buffer}')
    await clock.next_cycle
    return packet



async def get_n_packets(clock, n_packets, output_buffer):
    packets = []
    while len(packets) < n_packets:
        packets.append(await get_packet(clock, output_buffer))
    return packets


async def run(clock):
    params = LamletParams()
    r = Router(clock, params, 0, 0)
    clock.create_task(update(clock, r))
    clock.create_task(r.run())
    
    n_packets = 4

    task_south = clock.create_task(get_n_packets(clock, n_packets, r._output_buffers[Direction.S]))
    task_east = clock.create_task(get_n_packets(clock, n_packets, r._output_buffers[Direction.E]))
    task_here = clock.create_task(get_n_packets(clock, n_packets, r._output_buffers[Direction.H]))

    # 1) Send a packet that wants to go south and east
    # 2) Pop from south for a long time.
    # 3) Pop from east for a long time.
    # 4) Keep going. Make sure that the result is correct in both dirs.

    sent_packets = []

    ib = r._input_buffers[Direction.N]
    for i in range(n_packets):
        packet = make_packet()
        sent_packets.append(packet)
        for word in packet:
            while not ib.can_append():
                for direction, buffer in r._input_buffers.items():
                    xx = r._input_buffers[direction]
                    logger.info(f'input buffer {xx} {direction} has length {len(xx)}')
                for direction, buffer in r._output_buffers.items():
                    xx = r._output_buffers[direction]
                    logger.info(f'output buffer {xx} {direction} has length {len(xx)}')
                await clock.next_cycle
            ib.append(word)

    await task_south
    await task_east
    await task_here
    south_packets = task_south.result()
    east_packets = task_east.result()
    here_packets = task_here.result()
    assert [x[1:] for x in sent_packets] == [x[1:] for x in south_packets]
    assert [x[1:] for x in sent_packets] == [x[1:] for x in east_packets]
    assert [x[1:] for x in sent_packets] == [x[1:] for x in here_packets]
    logger.info('SUCCESS!!')



async def main(clock):
    clock.register_main()
    run_task = clock.create_task(run(clock))
    clock_driver_task = clock.create_task(clock.clock_driver())
    await run_task
    clock.stop()


if __name__ == '__main__':
    level = logging.INFO
    import sys
    import os
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    root_logger.info('Starting main')
    clock = Clock(max_cycles=1000)
    asyncio.run(main(clock))
