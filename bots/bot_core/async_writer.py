import queue
import threading
from collections.abc import Callable
from typing import TextIO


class SyncItemWriter:
    def __init__(self, stream: TextIO, encode: Callable[[object], str]) -> None:
        self._stream = stream
        self._encode = encode
        self._closed = False

    @property
    def dropped_count(self) -> int:
        return 0

    def submit(self, item: object) -> None:
        if self._closed:
            return
        self._stream.write(self._encode(item))
        self._stream.flush()

    def submit_blocking(self, item: object) -> None:
        self.submit(item)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stream.flush()


class AsyncItemWriter:
    def __init__(
        self,
        stream: TextIO,
        encode: Callable[[object], str],
        *,
        queue_size: int,
        flush_every: int = 64,
        flush_interval: float = 0.25,
        thread_name: str = "async-item-writer",
    ) -> None:
        self._stream = stream
        self._encode = encode
        self._queue: queue.Queue[object | None] = queue.Queue(maxsize=max(1, queue_size))
        self._flush_every = max(1, flush_every)
        self._flush_interval = max(0.01, flush_interval)
        self._dropped_count = 0
        self._dropped_lock = threading.Lock()
        self._closed = False
        self._close_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name=thread_name, daemon=True)
        self._thread.start()

    @property
    def dropped_count(self) -> int:
        with self._dropped_lock:
            return self._dropped_count

    def submit(self, item: object) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            with self._dropped_lock:
                self._dropped_count += 1

    def submit_blocking(self, item: object) -> None:
        if self._closed:
            return
        self._queue.put(item)

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._queue.put(None)
        self._thread.join()
        self._stream.flush()

    def _run(self) -> None:
        pending_since_flush = 0
        while True:
            try:
                item = self._queue.get(timeout=self._flush_interval)
            except queue.Empty:
                if pending_since_flush:
                    self._stream.flush()
                    pending_since_flush = 0
                continue
            if item is None:
                break
            self._stream.write(self._encode(item))
            pending_since_flush += 1
            if pending_since_flush >= self._flush_every:
                self._stream.flush()
                pending_since_flush = 0
        self._stream.flush()
