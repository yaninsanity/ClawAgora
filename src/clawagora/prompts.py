from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptVersion:
    key: str
    version: str
    rollout: int
    system: str


PROMPT_REGISTRY: dict[str, tuple[PromptVersion, ...]] = {
    "classify.system": (
        PromptVersion(
            key="classify.system",
            version="v1",
            rollout=100,
            system=(
                "You are a task classifier. Output ONLY valid JSON, no other text.\n"
                'Format: {"label": "engineering"|"research"|"support"|"general", '
                '"confidence": <0.5-1.0>, "tags": [<string>, ...]}\n'
                "Labels:\n"
                "  engineering — coding, debugging, APIs, repos, tests, refactoring\n"
                "  research    — papers, citations, summaries, literature review\n"
                "  support     — tickets, customers, SLA, billing, incidents\n"
                "  general     — anything else"
            ),
        ),
    ),
    "synthesize.system": (
        PromptVersion(
            key="synthesize.system",
            version="v1",
            rollout=100,
            system=(
                "You summarize completed AI pipeline tasks in exactly one sentence. "
                "Be specific, direct, and mention both the intent and a key result metric."
            ),
        ),
    ),
}


def resolve_prompt(
    key: str,
    *,
    context_id: str = "",
    forced_versions: dict[str, str] | None = None,
) -> PromptVersion:
    variants = PROMPT_REGISTRY.get(key)
    if variants is None:
        raise KeyError(f"Unknown prompt key: {key}")
    ordered = tuple(v for v in variants if v.rollout > 0)
    if not ordered:
        raise KeyError(f"No active prompt versions for key: {key}")
    if forced_versions:
        want = forced_versions.get(key)
        if want:
            for variant in ordered:
                if variant.version == want:
                    return variant
            for variant in variants:
                if variant.version == want:
                    return variant
    if len(ordered) == 1:
        return ordered[0]
    bucket = _rollout_bucket(key=key, context_id=context_id)
    cursor = 0
    for variant in ordered:
        cursor += min(max(variant.rollout, 0), 100)
        if bucket < cursor:
            return variant
    return ordered[-1]


def system_prompt(
    key: str, *, context_id: str = "", forced_versions: dict[str, str] | None = None
) -> str:
    return resolve_prompt(key, context_id=context_id, forced_versions=forced_versions).system


def _rollout_bucket(*, key: str, context_id: str) -> int:
    seed = f"{key}:{context_id}".encode("utf-8")
    digest = hashlib.sha256(seed).hexdigest()
    return int(digest[:8], 16) % 100
