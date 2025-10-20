import asyncio
import logging

logger = logging.getLogger(__name__)


class Clock:
    def __init__(self, max_cycles=None):
        self.cycle = 0
        self.tasks_ready = {}
        self.active_tasks = set()
        self.running = True
        self.max_cycles = max_cycles
        self.pending_futures = set()

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.active_tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task):
        self.active_tasks.discard(task)
        self.tasks_ready.pop(id(task), None)
        try:
            exception = task.exception()
            if exception is not None:
                logger.exception(f"Task failed with exception", exc_info=exception)
                import os
                if os.environ.get('PDB_ON_EXCEPTION'):
                    import pdb
                    import traceback
                    traceback.print_exception(type(exception), exception, exception.__traceback__)
                    pdb.post_mortem(exception.__traceback__)
                self.stop()
        except asyncio.CancelledError:
            pass

    async def wait_future(self, future):
        task = asyncio.current_task()
        self.pending_futures.add(id(task))
        try:
            result = await future
            return result
        finally:
            self.pending_futures.discard(id(task))

    async def next_cycle(self):
        task = asyncio.current_task()
        event = asyncio.Event()
        self.tasks_ready[id(task)] = event
        await event.wait()

    async def clock_driver(self):
        while self.running:
            active_not_done = [t for t in self.active_tasks if not t.done()]
            n_tasks_ready = len(self.tasks_ready)
            n_pending_futures = len(self.pending_futures)
            n_accounted_for = n_tasks_ready + n_pending_futures
            #logger.info(f'active_no_done {len(active_not_done)} n_tasks_ready {n_tasks_ready} n_pending_futures {n_pending_futures}')

            while n_accounted_for < len(active_not_done):
                await asyncio.sleep(0)
                active_not_done = [t for t in self.active_tasks if not t.done()]
                n_tasks_ready = len(self.tasks_ready)
                n_pending_futures = len(self.pending_futures)
                n_accounted_for = n_tasks_ready + n_pending_futures

            self.cycle += 1
            logger.debug(f"Advancing to cycle {self.cycle}")

            if self.max_cycles is not None and self.cycle >= self.max_cycles:
                logger.error(f"Timeout: reached maximum cycles ({self.max_cycles})")
                self.stop()
                break

            for event in self.tasks_ready.values():
                event.set()
            self.tasks_ready.clear()

    def stop(self):
        self.running = False
        for task in self.active_tasks:
            task.cancel()
