import asyncio
import logging

logger = logging.getLogger(__name__)


class Clock:
    def __init__(self):
        self.cycle = 0
        self.tasks_ready = {}
        self.active_tasks = set()
        self.running = True

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
                self.stop()
        except asyncio.CancelledError:
            pass

    async def next_cycle(self):
        task = asyncio.current_task()
        event = asyncio.Event()
        self.tasks_ready[id(task)] = event
        await event.wait()

    async def clock_driver(self):
        while self.running:
            while len(self.tasks_ready) < len(self.active_tasks):
                await asyncio.sleep(0)

            self.cycle += 1
            logger.debug(f"Advancing to cycle {self.cycle}")
            for event in self.tasks_ready.values():
                event.set()
            self.tasks_ready.clear()

    def stop(self):
        self.running = False
        for task in self.active_tasks:
            task.cancel()
