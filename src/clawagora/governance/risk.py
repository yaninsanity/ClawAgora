from __future__ import annotations

import re
from enum import StrEnum


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


DEFAULT_HIGH_RISK_PATTERNS: tuple[str, ...] = (
    # Environment / sensitivity markers
    r"\bprod\b",
    r"\bproduction\b",
    r"\bpayment\b",
    r"\bpii\b",
    r"\bsecrets?\b",
    r"\bcredentials?\b",
    r"private[-_ ]key",
    r"api[-_]?key",
    r"access[-_ ]token",
    r"\boauth\b",
    r"\bpassphrase\b",
    # Destructive SQL / DB operations
    r"\bdrop\s+table\b",
    r"\bdrop\s+database\b",
    r"\bdrop\s+schema\b",
    r"\btruncate\b",
    r"\bdelete\s+from\b",
    r"\bdelete\s+all\b",
    r"\balter\s+table\b",
    r"\bgrant\s+\w",           # GRANT ALL, GRANT SELECT …
    r"\brevoke\s+\w",          # REVOKE … FROM …
    # Dangerous shell patterns
    r"rm\s+-[rRf]+",           # rm -rf, rm -fr, rm -r -f …
    r"curl[^|]*\|\s*(?:ba?sh|sh|zsh|fish)",   # curl … | bash (supply-chain)
    r"wget[^|]*\|\s*(?:ba?sh|sh|zsh|fish)",
    r"\bwipe\b",
    r"\bnuke\b",
    r"\berase\b",
    # Security / intrusion vocabulary
    r"\bcompromise\b",
    r"\bexploit\b",
    r"\bbreach\b",
    r"\bexfiltrat",
    r"\bbackdoor\b",
    r"privilege.escalat",
    r"root.access",
    r"\bsudo\b",
)

DEFAULT_MEDIUM_RISK_PATTERNS: tuple[str, ...] = (
    r"\bdeploy",
    r"\brelease\b",
    r"\bcustomer\b",
    # "write" is too broad (common in docs/code); replaced with more specific
    # write-to-production style phrases
    r"\bwrite\s+to\s+(?:prod|database|db|disk|s3|storage)\b",
    r"\boverwrite\b",
    r"\bdelete\b",
    r"\bremove\b",
    r"\bupdate\b",
    r"\binsert\s+into\b",      # bulk INSERT is a meaningful data-change signal
    r"\bmigrat",
    r"\brollback\b",
    r"\bschema\b",
    r"\bdatabase\b",
    r"\brestart\b",
    r"\bdisable\b",
    r"\bterminate\b",
    r"\bshutdown\b",
)


def _compile_patterns(patterns: list[str] | tuple[str, ...]) -> re.Pattern:
    if not patterns:
        return re.compile(r"$^")
    union = "|".join(f"(?:{pat})" for pat in patterns)
    return re.compile(union, re.IGNORECASE)


class RiskClassifier:
    def __init__(
        self,
        *,
        high_patterns: list[str] | tuple[str, ...] | None = None,
        medium_patterns: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self._high_re = _compile_patterns(list(high_patterns or DEFAULT_HIGH_RISK_PATTERNS))
        self._medium_re = _compile_patterns(list(medium_patterns or DEFAULT_MEDIUM_RISK_PATTERNS))

    def classify(self, text: str) -> RiskTier:
        if self._high_re.search(text):
            return RiskTier.HIGH
        if self._medium_re.search(text):
            return RiskTier.MEDIUM
        return RiskTier.LOW
