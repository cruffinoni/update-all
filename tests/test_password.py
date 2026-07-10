"""Tests for update_all.password."""

import threading
import time

from update_all.password import PasswordBroker, _FIFOLock


def test_fifo_lock_grants_in_arrival_order():
    lock = _FIFOLock()
    order: list[int] = []
    started = threading.Event()

    # Hold the lock so every worker must queue behind it.
    lock.acquire()

    def worker(i: int, ready: threading.Event) -> None:
        ready.set()
        lock.acquire()
        order.append(i)
        lock.release()

    threads = []
    for i in range(5):
        ready = threading.Event()
        t = threading.Thread(target=worker, args=(i, ready))
        t.start()
        ready.wait()
        time.sleep(0.02)  # let this worker reach acquire() and enqueue before the next
        threads.append(t)

    lock.release()  # release to the front of the queue
    for t in threads:
        t.join(timeout=5)

    assert order == [0, 1, 2, 3, 4]


def test_get_password_returns_bytes_with_newline():
    broker = PasswordBroker(prompt_fn=lambda ctx, reprompt: "secret")
    assert broker.get_password(["a", "b"], reprompt=False) == b"secret\n"


def test_get_password_caches_answer():
    calls: list[bool] = []

    def prompt(ctx, reprompt):
        calls.append(reprompt)
        return "cached"

    broker = PasswordBroker(prompt_fn=prompt)
    assert broker.get_password([], reprompt=False) == b"cached\n"
    assert broker.get_password([], reprompt=False) == b"cached\n"
    assert calls == [False]  # prompted only once


def test_reprompt_invalidates_cache():
    passwords = iter(["wrong", "right"])
    calls: list[bool] = []

    def prompt(ctx, reprompt):
        calls.append(reprompt)
        return next(passwords)

    broker = PasswordBroker(prompt_fn=prompt)
    assert broker.get_password([], reprompt=False) == b"wrong\n"
    assert broker.get_password([], reprompt=True) == b"right\n"
    assert calls == [False, True]


def test_pause_is_entered_while_prompting():
    events: list[str] = []

    class _Pause:
        def __enter__(self):
            events.append("enter")
            return self

        def __exit__(self, *exc):
            events.append("exit")

    broker = PasswordBroker(pause=_Pause, prompt_fn=lambda ctx, r: "pw")
    broker.get_password([], reprompt=False)
    assert events == ["enter", "exit"]
