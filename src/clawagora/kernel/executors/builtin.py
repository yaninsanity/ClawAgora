from __future__ import annotations

import hashlib
import json

from clawagora.contracts.task import ExecutionArtifact, ExecutionStep
from clawagora.kernel.executors.base import Executor


class TransformExecutor(Executor):
    @property
    def executor_id(self) -> str:
        return "executor_transform"

    def run(self, step: ExecutionStep) -> ExecutionArtifact:
        text = str(step.inputs.get("text", ""))
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        payload = {"summary": text[:280], "fingerprint": digest}
        return ExecutionArtifact(
            step_id=step.step_id,
            executor=self.executor_id,
            output=payload,
            logs=["context gathered"],
        )


class EchoExecutor(Executor):
    @property
    def executor_id(self) -> str:
        return "executor_echo"

    def run(self, step: ExecutionStep) -> ExecutionArtifact:
        payload = {"echo": step.inputs, "format": "json"}
        return ExecutionArtifact(
            step_id=step.step_id,
            executor=self.executor_id,
            output=payload,
            logs=[json.dumps({"stage": "emit"})],
        )
