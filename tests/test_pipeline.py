from clawagora.kernel.classify import ClassifyService
from clawagora.kernel.dispatcher import Dispatcher
from clawagora.kernel.executors.builtin import EchoExecutor, TransformExecutor
from clawagora.kernel.executors.domain import CodingExecutor, ResearchExecutor, SupportExecutor
from clawagora.kernel.executors.base import ExecutorRegistry
from clawagora.kernel.intake import IntakeService
from clawagora.kernel.pipeline import TaskPipeline
from clawagora.kernel.planner import PlannerService
from clawagora.kernel.synthesizer import Synthesizer
from clawagora.kernel.validation import (
    CompositeValidator,
    PolicyValidator,
    SafetyValidator,
    SchemaValidator,
)
from clawagora.contracts.task import TaskState
from clawagora.governance.profile import CONSTITUTIONAL_WESTERN_ROLES
from clawagora.providers.base import ModelProvider
from clawagora.providers.null_provider import NullModelProvider
from clawagora.prompts import resolve_prompt


def _full_registry() -> ExecutorRegistry:
    """Registry containing all built-in and domain executors."""
    return ExecutorRegistry(
        [
            TransformExecutor(),
            EchoExecutor(),
            CodingExecutor(),
            ResearchExecutor(),
            SupportExecutor(),
        ]
    )


def _full_pipeline() -> TaskPipeline:
    return TaskPipeline(
        intake=IntakeService(),
        classify=ClassifyService(),
        planner=PlannerService(),
        validators=CompositeValidator([SchemaValidator(), PolicyValidator(), SafetyValidator()]),
        dispatcher=Dispatcher(),
        registry=_full_registry(),
        synthesizer=Synthesizer(),
    )


def test_pipeline_correlates_request_id():
    pipeline = _full_pipeline()
    rid = "00000000-0000-0000-0000-000000000099"
    result = pipeline.run("Hello world", request_id=rid)
    assert result.envelope.request_id == rid


def test_pipeline_happy_path():
    # "api" keyword → engineering → CODING pack → executor_coding
    result = _full_pipeline().run("Implement a REST endpoint for user profiles.")
    assert result.state == TaskState.COMPLETED
    assert result.synthesis is not None
    assert result.envelope.normalized_text


def test_pipeline_happy_path_research():
    result = _full_pipeline().run("Summarize the latest research paper on transformers.")
    assert result.state == TaskState.COMPLETED
    assert result.synthesis is not None


def test_pipeline_happy_path_support():
    result = _full_pipeline().run("Open a support ticket for the customer's SLA breach.")
    assert result.state == TaskState.COMPLETED
    assert result.synthesis is not None


def test_pipeline_happy_path_general():
    # No domain keywords → general intent → executor_transform / executor_echo
    result = _full_pipeline().run("Hello world, please process this.")
    assert result.state == TaskState.COMPLETED


def test_planner_attaches_constitutional_roles_and_weights():
    intake = IntakeService()
    planner = PlannerService()
    envelope = intake.accept(
        "Implement user auth API with risk checks",
        metadata={
            "governance_profile": "constitutional_western",
            "accountability_feedback": [
                {"role": "Judicial Review Board", "delta": 0.25},
                {"role": "Inspector General", "incidents": 2},
            ],
        },
    )
    classification = ClassifyService().classify(envelope)
    plan = planner.plan(envelope, classification)
    assert "profile=constitutional_western" in plan.rationale
    roles = [step.inputs.get("governance_role") for step in plan.steps]
    assert roles
    assert roles[0] == CONSTITUTIONAL_WESTERN_ROLES[0]
    assert set(roles).issubset(set(CONSTITUTIONAL_WESTERN_ROLES))


def test_dispatcher_prioritizes_higher_governance_weight():
    envelope = IntakeService().accept(
        "Design policy and execute tasks",
        metadata={
            "governance_profile": "constitutional_western",
            "accountability_feedback": [
                {"role": "Intake Clerk", "delta": -0.2},
                {"role": "Policy Drafter", "delta": 0.4},
            ],
        },
    )
    classification = ClassifyService().classify(envelope)
    plan = PlannerService().plan(envelope, classification)
    assignments = Dispatcher().assign(plan)
    assert assignments
    assert assignments[0].governance_weight >= assignments[-1].governance_weight


def test_governance_weight_lifecycle_has_anti_drift_guards():
    envelope = IntakeService().accept(
        "Constitutional drift guard scenario",
        metadata={
            "governance_profile": "constitutional_western",
            "governance_baseline_weights": {
                "Policy Drafter": 1.0,
                "Judicial Review Board": 1.0,
            },
            "accountability_feedback": [
                # Old high positive noise should decay and not dominate forever.
                {
                    "role": "Policy Drafter",
                    "delta": 0.9,
                    "incidents": 0,
                    "observed_at": "2020-01-01T00:00:00+00:00",
                },
                # Recent negative event should matter.
                {
                    "role": "Policy Drafter",
                    "delta": -0.2,
                    "incidents": 1,
                },
                # Strong spikes are bounded by lifecycle cap.
                {
                    "role": "Judicial Review Board",
                    "delta": 10.0,
                    "incidents": 0,
                },
            ],
        },
    )
    classification = ClassifyService().classify(envelope)
    plan = PlannerService().plan(envelope, classification)
    role_weights = {}
    for step in plan.steps:
        role = step.inputs.get("governance_role")
        if role not in role_weights:
            role_weights[role] = float(step.inputs.get("governance_weight"))
    assert 0.2 <= role_weights.get("Policy Drafter", 1.0) <= 2.0
    assert role_weights.get("Policy Drafter", 1.0) < 1.0
    assert 0.2 <= role_weights.get("Judicial Review Board", 1.0) <= 2.0


def test_pipeline_validation_failure_on_empty():
    result = _full_pipeline().run("   ")
    assert result.state == TaskState.FAILED
    assert result.error_stage == "validate"


def test_pipeline_preserves_partial_data_on_exception():
    """Unexpected executor exception preserves classification and plan data."""
    from clawagora.contracts.task import ExecutionArtifact, ExecutionStep
    from clawagora.kernel.executors.base import Executor

    class BoomExecutor(Executor):
        @property
        def executor_id(self) -> str:
            return "executor_transform"

        def run(self, step: ExecutionStep) -> ExecutionArtifact:
            raise RuntimeError("simulated executor crash")

    pipeline = TaskPipeline(
        intake=IntakeService(),
        classify=ClassifyService(),
        planner=PlannerService(),
        validators=CompositeValidator([SchemaValidator(), PolicyValidator(), SafetyValidator()]),
        dispatcher=Dispatcher(),
        registry=ExecutorRegistry([BoomExecutor(), EchoExecutor()]),
        synthesizer=Synthesizer(),
    )
    # "general" intent → executor_transform → BoomExecutor raises
    result = pipeline.run("Hello world")
    assert result.state == TaskState.FAILED
    assert result.error == "pipeline_execution_failed"
    assert result.error_type == "RuntimeError"
    # Classification and plan should be preserved despite crash
    assert result.classification is not None
    assert result.plan is not None
    assert result.error_stage == "execute"


# ---------------------------------------------------------------------------
# ModelProvider injection tests
# ---------------------------------------------------------------------------


class _MockProvider(ModelProvider):
    """Test double: returns a fixed string (or None) from complete()."""

    def __init__(self, response: str | None) -> None:
        self._response = response

    def complete(  # noqa: ARG002
        self,
        prompt: str,
        *,
        system: str | None = None,
        prompt_meta: dict[str, str] | None = None,
    ) -> str | None:
        return self._response


def test_classify_null_provider_falls_back_to_regex():
    """NullModelProvider.complete() returns None → regex baseline fires."""
    svc = ClassifyService(model=NullModelProvider())
    envelope = IntakeService().accept("Implement a sort algorithm")
    result = svc.classify(envelope)
    assert result.label in {"engineering", "research", "support", "general"}
    assert 0.0 <= result.confidence <= 1.0


def test_classify_uses_valid_model_output():
    """Mock provider returning well-formed JSON → model label is adopted."""
    import json

    payload = json.dumps({"label": "research", "confidence": 0.92, "tags": ["ml"]})
    svc = ClassifyService(model=_MockProvider(payload))
    envelope = IntakeService().accept("Anything at all")
    result = svc.classify(envelope)
    assert result.label == "research"
    assert abs(result.confidence - 0.92) < 1e-6


def test_classify_falls_back_on_bad_json():
    """Mock provider returning garbage → regex baseline fires without error."""
    svc = ClassifyService(model=_MockProvider("not json at all !!!"))
    envelope = IntakeService().accept("Research transformers paper")
    result = svc.classify(envelope)
    assert result.label in {"engineering", "research", "support", "general"}


def test_classify_falls_back_on_unknown_label():
    """Model returns valid JSON but with an unrecognised label → regex fallback."""
    import json

    payload = json.dumps({"label": "space_travel", "confidence": 0.99, "tags": []})
    svc = ClassifyService(model=_MockProvider(payload))
    envelope = IntakeService().accept("Fix this bug")
    result = svc.classify(envelope)
    assert result.label in {"engineering", "research", "support", "general"}


def test_domain_executor_receives_text_input():
    """After planner fix, executor_coding receives 'text' key → non-empty token_count."""
    pipeline = _full_pipeline()
    result = pipeline.run("Implement a binary search tree in Python")
    assert result.state == TaskState.COMPLETED
    # Find the executor_coding artifact (if present) and confirm text was non-empty
    coding_arts = [a for a in (result.artifacts or []) if a.executor == "executor_coding"]
    if coding_arts:
        assert coding_arts[0].output.get("token_count", 0) > 0


def test_synthesizer_uses_model_conclusion():
    """When Synthesizer receives a model that returns a string, that string is used."""
    import uuid

    from clawagora.contracts.task import (
        ExecutionArtifact,
        ExecutionStep,
        IntakeEnvelope,
        IntentClassification,
        Plan,
    )

    envelope = IntakeEnvelope(
        request_id=str(uuid.uuid4()),
        raw_text="Test input",
        normalized_text="test input",
    )
    classification = IntentClassification(label="general", confidence=0.8, tags=[])
    step = ExecutionStep(
        step_id="s1",
        title="Echo",
        executor="executor_transform",
        inputs={"text": "Hello"},
    )
    plan = Plan(plan_id="p1", steps=[step])
    artifact = ExecutionArtifact(
        step_id="s1",
        executor="executor_transform",
        output={"echo": "Hello"},
    )
    synth = Synthesizer(model=_MockProvider("All tasks done successfully."))
    out = synth.synthesize(envelope, classification, plan, [artifact])
    assert out["conclusion"] == "All tasks done successfully."


def test_prompt_versioning_resolver_defaults_to_v1():
    picked = resolve_prompt("classify.system", context_id="req-001")
    assert picked.version == "v1"
    assert picked.rollout == 100
