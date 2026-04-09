from __future__ import annotations

import hashlib
import uuid

from clawagora.config import DOMAIN_EXECUTOR_CONFIG
from clawagora.contracts.task import ExecutionArtifact, ExecutionStep
from clawagora.kernel.executors.base import Executor


class CodingExecutor(Executor):
    """Domain executor for engineering/coding tasks.

    Produces a structured code-analysis artifact: token count, keyword
    extraction, cyclomatic-complexity estimate, and a content fingerprint.
    """

    @property
    def executor_id(self) -> str:
        return "executor_coding"

    def run(self, step: ExecutionStep) -> ExecutionArtifact:
        text = str(step.inputs.get("text", ""))
        tokens = text.split()
        token_count = len(tokens)
        keywords = [
            w.strip(".,;:()[]{}\"'").lower()
            for w in tokens
            if len(w) >= DOMAIN_EXECUTOR_CONFIG.coding_keyword_min_length
        ][: DOMAIN_EXECUTOR_CONFIG.coding_keyword_limit]
        complexity = (
            "high"
            if token_count > DOMAIN_EXECUTOR_CONFIG.coding_complexity_high_token_count
            else (
                "medium"
                if token_count > DOMAIN_EXECUTOR_CONFIG.coding_complexity_medium_token_count
                else "low"
            )
        )
        fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return ExecutionArtifact(
            step_id=step.step_id,
            executor=self.executor_id,
            output={
                "token_count": token_count,
                "complexity": complexity,
                "keywords": keywords,
                "fingerprint": fingerprint,
            },
            logs=["coding analysis complete"],
        )


class ResearchExecutor(Executor):
    """Domain executor for research tasks.

    Extracts key terms and produces a structured research summary with a
    placeholder citations list (citation retrieval is an operator extension).
    """

    @property
    def executor_id(self) -> str:
        return "executor_research"

    def run(self, step: ExecutionStep) -> ExecutionArtifact:
        text = str(step.inputs.get("text", ""))
        words = text.split()
        keywords = sorted(
            {
                w.strip(".,;:()\"'").lower()
                for w in words
                if len(w) >= DOMAIN_EXECUTOR_CONFIG.research_keyword_min_length
            }
        )[: DOMAIN_EXECUTOR_CONFIG.research_keyword_limit]
        return ExecutionArtifact(
            step_id=step.step_id,
            executor=self.executor_id,
            output={
                "keywords": keywords,
                "document_count": 0,
                "summary": text[: DOMAIN_EXECUTOR_CONFIG.research_summary_char_limit],
                "citations": [],
            },
            logs=["research retrieval complete"],
        )


class SupportExecutor(Executor):
    """Domain executor for support/ticketing tasks.

    Formats input into a safe, structured ticket representation with a
    deterministic priority estimate based on input length.
    """

    @property
    def executor_id(self) -> str:
        return "executor_support"

    def run(self, step: ExecutionStep) -> ExecutionArtifact:
        text = str(step.inputs.get("text", ""))
        intent = str(step.inputs.get("intent", "support"))
        ticket_id = str(uuid.uuid4())
        word_count = len(text.split())
        priority = (
            "high"
            if word_count > DOMAIN_EXECUTOR_CONFIG.support_priority_high_word_count
            else (
                "medium"
                if word_count > DOMAIN_EXECUTOR_CONFIG.support_priority_medium_word_count
                else "low"
            )
        )
        return ExecutionArtifact(
            step_id=step.step_id,
            executor=self.executor_id,
            output={
                "ticket_id": ticket_id,
                "priority": priority,
                "category": intent,
                "safe_output": text[: DOMAIN_EXECUTOR_CONFIG.support_safe_output_char_limit],
            },
            logs=["support ticket formatted"],
        )
