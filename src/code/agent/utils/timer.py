import time
from contextlib import contextmanager


class TimerContext:
    def __init__(self):
        self.elapsed = 0


class Timer:
    @contextmanager
    def __call__(self, operation: str):
        print(f"{operation} ...")
        start_time = time.time()
        timer_context = TimerContext()
        try:
            yield timer_context
        finally:
            timer_context.elapsed = time.time() - start_time
            print(f"{operation} finished, cost: {round(timer_context.elapsed, 2)}s")


timer = Timer()
