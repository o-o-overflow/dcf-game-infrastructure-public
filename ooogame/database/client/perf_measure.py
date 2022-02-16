import logging
import time
from functools import wraps


l = logging.getLogger("client.db")


LOG_IF_TAKES_MORE_THAN = 0.5 # fractional perf_counter() seconds


def print_runtime_stats(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        ret = f(*args, **kwargs)
        took = time.perf_counter() - start
        if took > LOG_IF_TAKES_MORE_THAN:
            l.warning("TIMED_{}={:.3}".format(f.__name__.upper(), took))
        return ret
    return wrapper


# https://stackoverflow.com/questions/6307761/how-to-decorate-all-functions-of-a-class-without-typing-it-over-and-over-for-eac
def for_all_methods(decorator):
    def decorate(cls):
        for name in cls.__dict__:
            if callable(getattr(cls, name)) \
                    and not name.startswith('_') \
                    and not name.startswith('wait_'):
                setattr(cls, name, decorator(getattr(cls, name)))
        return cls
    return decorate





if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    l.setLevel(logging.DEBUG)


    @for_all_methods(print_runtime_stats)
    class TestDb:
        def __init__(self):
            pass
        def _sleep(self, x):
            # Should not appear by itself
            time.sleep(x)
        def immediate(self):
            pass
        def slow_direct(self):
            time.sleep(2)
        def slow_methodcall(self):
            self._sleep(2)
        def slow_doublecall(self):
            self._sleep(LOG_IF_TAKES_MORE_THAN / 2)
            self._sleep(LOG_IF_TAKES_MORE_THAN / 2)
        def wait_for_something(self):
            self._sleep(3)

    tc = TestDb()
    l.info("immediate"); tc.immediate()
    l.info("slow_direct"); tc.slow_direct()
    l.info("slow_methodcall"); tc.slow_methodcall()
    l.info("slow_doublecall"); tc.slow_doublecall()
    l.info("wait_for_something"); tc.wait_for_something()
