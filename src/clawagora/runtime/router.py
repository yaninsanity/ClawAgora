"""Dynamic executor routing based on governance weights and trust signals.

``DynamicRouter`` selects among a set of eligible executors for a plan step
by applying a weighted-random selection strategy driven by per-role governance
weights and optionally biased by a ``TrustScore``.

Usage example::

    from clawagora.runtime.router import DynamicRouter, RoutingTarget

    router = DynamicRouter(
        targets=[
            RoutingTarget(executor_id="executor_coding",  weight=1.2),
            RoutingTarget(executor_id="executor_transform", weight=0.8),
        ]
    )
    # Deterministic selection for a request_id / step_id:
    selected = router.select(seed="task-uuid-step-1")
    # Trust-adjusted selection:
    from clawagora.runtime.trust import TrustScore
    selected = router.select(seed="task-uuid-step-1", trust=TrustScore(value=0.9))
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from clawagora.runtime.trust import TrustScore


@dataclass(frozen=True)
class RoutingTarget:
    """A candidate executor with a base routing weight.

    Args:
        executor_id: Executor identifier as registered in ``ExecutorRegistry``.
        weight: Base routing weight (positive float).  Higher values increase
            the probability of selection relative to other targets.
    """

    executor_id: str
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ValueError(f"RoutingTarget weight must be positive, got {self.weight!r}")


@dataclass
class DynamicRouter:
    """Weighted executor router for dynamic step dispatch.

    Selects one executor from ``targets`` using a deterministic weighted-random
    algorithm seeded by a stable string (e.g. ``task_id + step_id``).

    When a ``TrustScore`` is provided to ``select()``, targets whose weight is
    at or above ``trust_boost_threshold`` receive an additive boost proportional
    to the trust value, allowing high-trust execution paths to bias toward
    heavier (more expensive) executors.

    Args:
        targets: Ordered list of ``RoutingTarget`` entries.  Must be non-empty.
        trust_boost_threshold: Targets with ``weight >= trust_boost_threshold``
            are eligible for trust-proportional boosting (default ``1.0``).
        trust_boost_coefficient: Maximum additive weight boost at full trust
            (default ``0.5``).  Actual boost = ``trust.value * coefficient``.
    """

    targets: list[RoutingTarget]
    trust_boost_threshold: float = 1.0
    trust_boost_coefficient: float = 0.5
    _extra: dict = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.targets:
            raise ValueError("DynamicRouter requires at least one RoutingTarget")

    def select(self, seed: str, *, trust: TrustScore | None = None) -> RoutingTarget:
        """Select one executor deterministically from ``targets``.

        Args:
            seed: A stable string used to seed the selection — typically the
                concatenation of ``task_id`` and ``step_id`` so the same step
                always resolves to the same executor on replay.
            trust: Optional ``TrustScore``; when provided, boosts weights of
                targets that meet the ``trust_boost_threshold``.

        Returns:
            The selected ``RoutingTarget``.
        """
        weights = self._adjusted_weights(trust)
        total = sum(weights)
        # Deterministic fractional index from the seed hash.
        digest = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)
        point = (digest % (10 ** 9)) / (10 ** 9) * total
        cumulative = 0.0
        for target, w in zip(self.targets, weights):
            cumulative += w
            if point <= cumulative:
                return target
        return self.targets[-1]

    def _adjusted_weights(self, trust: TrustScore | None) -> list[float]:
        if trust is None:
            return [t.weight for t in self.targets]
        boost = trust.value * self.trust_boost_coefficient
        return [
            t.weight + boost if t.weight >= self.trust_boost_threshold else t.weight
            for t in self.targets
        ]
