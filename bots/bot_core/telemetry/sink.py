from typing import Protocol


class TelemetrySink(Protocol):
    def log(self, event: str, **fields: object) -> None: ...

    def sample(self, event: str, **fields: object) -> None: ...
