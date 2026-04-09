from __future__ import annotations

from abc import ABC, abstractmethod

from clawagora.contracts.task import ExecutionArtifact, ExecutionStep


class Executor(ABC):
    @property
    @abstractmethod
    def executor_id(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def run(self, step: ExecutionStep) -> ExecutionArtifact:
        raise NotImplementedError


class ExecutorRegistry:
    def __init__(self, executors: list[Executor]) -> None:
        self._by_id = {e.executor_id: e for e in executors}

    def get(self, executor_id: str) -> Executor:
        if executor_id not in self._by_id:
            raise KeyError(f"Unknown executor: {executor_id}")
        return self._by_id[executor_id]
