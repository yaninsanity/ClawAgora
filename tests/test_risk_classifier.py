from clawagora.governance.risk import RiskClassifier, RiskTier


def test_high_risk_default_keywords():
    classifier = RiskClassifier()
    assert classifier.classify("Please DROP TABLE users;") == RiskTier.HIGH
    assert classifier.classify("Investigate payment reconciliation bug.") == RiskTier.HIGH
    assert classifier.classify("Rotate api_key for external service.") == RiskTier.HIGH


def test_drop_word_no_longer_forces_high():
    classifier = RiskClassifier()
    assert classifier.classify("Update the dropdown style in the UI.") == RiskTier.MEDIUM


def test_custom_patterns_override_defaults():
    classifier = RiskClassifier(
        high_patterns=[r"\bfraud\b"],
        medium_patterns=[r"\baudit\b"],
    )
    assert classifier.classify("Need fraud anomaly detection now.") == RiskTier.HIGH
    assert classifier.classify("Run an audit checklist.") == RiskTier.MEDIUM
    assert classifier.classify("Rotate api_key for external service.") == RiskTier.LOW
