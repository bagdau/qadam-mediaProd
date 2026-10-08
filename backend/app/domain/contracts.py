from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar

T = TypeVar("T")


class UnitOfWork(Protocol):
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


AfterCommit = Callable[[T], Awaitable[None]]
