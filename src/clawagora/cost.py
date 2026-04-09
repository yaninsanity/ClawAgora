from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CostPolicy:
    input_cost_per_mtok_usd: float = 0.0
    output_cost_per_mtok_usd: float = 0.0
    token_chars_estimate: int = 4


def estimate_tokens(text: str, *, token_chars_estimate: int) -> int:
    if not text:
        return 0
    return max((len(text) + token_chars_estimate - 1) // token_chars_estimate, 1)


def estimate_cost_usd(input_tokens: int, output_tokens: int, *, policy: CostPolicy) -> float:
    in_cost = (input_tokens / 1_000_000.0) * policy.input_cost_per_mtok_usd
    out_cost = (output_tokens / 1_000_000.0) * policy.output_cost_per_mtok_usd
    return round(in_cost + out_cost, 8)
