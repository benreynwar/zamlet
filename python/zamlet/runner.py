import asyncio
import logging
import os
import pdb
import traceback

logger = logging.getLogger(__name__)

class Future:

    def __init__(self, clock: 'Clock'):
        self.clock = clock
        clock.check_counts_good()
        self.n_waiting_on_me = 0
        self.tasks_waiting_on_me = set()
        self.future = asyncio.Future()
        clock.check_counts_good()

    def set_result(self, value):
        self.clock.check_counts_good()
        self.future.set_result(value)
        assert self.n_waiting_on_me == len(self.tasks_waiting_on_me)
        assert not self.clock.running_tasks & self.tasks_waiting_on_me
        self.clock.n_waiting -= self.n_waiting_on_me
        self.clock.running_tasks |= self.tasks_waiting_on_me
        self.clock.check_counts_good()

    def __await__(self):
        self.clock.check_counts_good()
        if not self.future.done():
            current_task = asyncio.current_task()
            self.tasks_waiting_on_me.add(id(current_task))
            self.clock.n_waiting += 1
            self.n_waiting_on_me += 1
            self.clock.running_tasks.remove(id(current_task))
            self.clock.check_counts_good()
        yield from self.future.__await__()

    def result(self):
        return self.future.result()


class Event:

    def __init__(self, clock: 'Clock'):
        self.clock = clock
        self.n_waiting_on_me = 0
        self.tasks_waiting_on_me = set()
        self.event = asyncio.Event()
        self.clock.check_counts_good()

    def set(self):
        self.clock.check_counts_good()
        self.event.set()
        assert self.n_waiting_on_me == len(self.tasks_waiting_on_me)
        assert not self.clock.running_tasks & self.tasks_waiting_on_me
        self.clock.n_waiting -= self.n_waiting_on_me
        self.clock.running_tasks |= self.tasks_waiting_on_me
        self.clock.check_counts_good()

    def __await__(self):
        self.clock.check_counts_good()
        if not self.event.is_set():
            current_task = asyncio.current_task()
            self.tasks_waiting_on_me.add(id(current_task))
            if id(current_task) not in self.clock.running_tasks:
                logger.error(f'current_task is {current_task}')
            self.clock.running_tasks.remove(id(current_task))
            self.clock.n_waiting += 1
            self.n_waiting_on_me += 1
            self.clock.check_counts_good()
        yield from self.event.wait().__await__()


class Task:

    def __init__(self, clock: 'Clock', task: asyncio.Task):
        self.id = id(task)
        self.clock = clock
        self.clock.check_counts_good()
        self.tasks_waiting_on_me = set()
        self.n_waiting_on_me = 0
        self.task = task
        task.add_done_callback(self._task_done)
        self.clock.n_tasks += 1
        self.clock.active_tasks[self.id] = self
        self.clock.running_tasks.add(self.id)
        self.clock.check_counts_good()

    def cancel(self):
        self.clock.check_counts_good()
        self.task.cancel()
        self.clock.check_counts_good()

    def result(self):
        return self.task.result()

    def _task_done(self, task):
        if self.clock.running:
            self.clock.check_counts_good()
        assert id(task) == self.id
        self.clock.n_tasks -= 1
        assert self.n_waiting_on_me == len(self.tasks_waiting_on_me)
        assert not self.clock.running_tasks & self.tasks_waiting_on_me
        self.clock.n_waiting -= self.n_waiting_on_me
        self.clock.running_tasks |= self.tasks_waiting_on_me
        if self.clock.running:
            # It might not be in running tasks if we cancelled it because we finished.
            self.clock.running_tasks.remove(self.id)
        del self.clock.active_tasks[self.id]
        try:
            exception = self.task.exception()
            if exception is not None:
                logger.exception(f"Task failed with exception", exc_info=exception)
                if int(os.environ.get('PDB_ON_EXCEPTION', 0)):
                    traceback.print_exception(type(exception), exception, exception.__traceback__)
                    pdb.post_mortem(exception.__traceback__)
                self.clock.stop()
        except asyncio.CancelledError:
            pass
        if self.clock.running:
            self.clock.check_counts_good()

    def __await__(self):
        self.clock.check_counts_good()
        if not self.task.done():
            current_task_id = id(asyncio.current_task())
            self.tasks_waiting_on_me.add(current_task_id)
            if current_task_id not in self.clock.running_tasks:
                logger.error(f'missing task is {asyncio.current_task()}')
            self.clock.running_tasks.remove(current_task_id)
            self.clock.n_waiting += 1
            self.n_waiting_on_me += 1
            self.clock.check_counts_good()
        yield from self.task.__await__()


class Clock:
    def __init__(self, max_cycles=None, on_timeout=None):
        self.cycle = 0
        self.active_tasks = {}

        self.running_tasks = set()

        self.running = True
        self.max_cycles = max_cycles
        self.on_timeout = on_timeout

        self.n_tasks = 0
        self.n_waiting = 0

        # This fires and then everything that is waiting on the next clock cycle runs.
        self.next_cycle = self.create_event()
        # This is run inbetween clock cycles that does a once a clock cycle update.
        self.next_update = self.create_event()

    def register_main(self):
        '''
        We create a task for the main task that we start the simulation with.
        '''
        Task(self, asyncio.current_task())

    def create_task(self, coro):
        task = Task(self, asyncio.create_task(coro))
        return task

    def create_future(self):
        future = Future(self)
        return future

    def create_event(self):
        event = Event(self)
        return event

    def check_counts_good(self):
        if not self.running:
            return
        assert len(self.running_tasks) == self.n_tasks - self.n_waiting, f'n running tasks is {len(self.running_tasks)} n_tasks {self.n_tasks} n_waiting {self.n_waiting}'

    async def run_until_stuck(self):
        self.check_counts_good()
        count = 0
        # The +1 is there for the 'clock_driver' task.
        while self.n_waiting+1 < self.n_tasks:
            self.check_counts_good()
            if count > 100:
                logger.debug(f'Tasks {self.n_tasks} > tasks waiting {self.n_waiting}')
                for task_id in self.running_tasks:
                    logger.debug(f'running task is {self.active_tasks[task_id].task}')
            await asyncio.sleep(0)
            count += 1

    async def clock_driver(self):
        while self.running:
            await self.run_until_stuck()
            # Trigger the next_cycle events
            self.next_cycle.set()
            self.next_cycle = self.create_event()
            await self.run_until_stuck()
            # Triggers the next_update events
            self.cycle += 1
            old_event = self.next_update
            self.next_update = self.create_event()
            old_event.set()
            if self.max_cycles is not None and self.cycle >= self.max_cycles:
                logger.error(f"Timeout: reached maximum cycles ({self.max_cycles})")
                if self.on_timeout:
                    self.on_timeout()
                self.stop()

    def stop(self):
        logger.debug(f"Clock.stop() called - setting running=False and cancelling {len(self.active_tasks)} active tasks")
        self.running = False
        for task in self.active_tasks.values():
            task.cancel()
