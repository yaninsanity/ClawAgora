from __future__ import annotations

from enum import StrEnum


class PackId(StrEnum):
    CODING = "coding"
    RESEARCH = "research"
    SUPPORT = "support"


class PackRegistry:
    def __init__(self) -> None:
        self._packs: dict[str, dict] = {
            PackId.CODING: {
                "validators": ["schema", "policy", "safety"],
                "executors": ["executor_coding"],
            },
            PackId.RESEARCH: {
                "validators": ["schema", "policy", "safety"],
                "executors": ["executor_research"],
            },
            PackId.SUPPORT: {
                "validators": ["schema", "policy", "safety"],
                "executors": ["executor_support"],
            },
        }

    def register(
        self,
        pack_id: str,
        *,
        executors: list[str],
        validators: list[str] | None = None,
    ) -> None:
        """Register a custom pack at runtime.

        Allows library users to add domain packs (e.g. ``executor_image_gen``)
        without forking the source.  Existing built-in packs cannot be
        overwritten by default; pass ``overwrite=True`` to replace them.

        Example::

            registry = PackRegistry()
            registry.register(
                "image",
                executors=["executor_image_gen"],
                validators=["schema", "safety"],
            )
        """
        if pack_id in self._packs:
            raise ValueError(
                f"Pack '{pack_id}' is already registered. "
                "Use PackRegistry.unregister() first if you intend to replace it."
            )
        self._packs[pack_id] = {
            "validators": validators if validators is not None else ["schema", "policy", "safety"],
            "executors": list(executors),
        }

    def unregister(self, pack_id: str) -> None:
        """Remove a previously registered pack."""
        self._packs.pop(pack_id, None)

    def describe(self, pack_id: str) -> dict:
        return dict(self._packs.get(pack_id, {}))

    def pack_ids(self) -> list[str]:
        """Return all registered pack identifiers."""
        return list(self._packs)
