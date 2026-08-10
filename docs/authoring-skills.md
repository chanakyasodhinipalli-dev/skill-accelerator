# Authoring skills

## The minimum

```python
from sa_skills import skill

@skill()
async def normalize_address(raw: str, country: str = "US") -> dict:
    """Normalize a free-text postal address into structured components.

    Args:
        raw: The address as entered by a user.
        country: ISO 3166-1 alpha-2 country code.
    """
    ...
```

That is a complete skill. The name, description, and input schema are derived
from the function; parameter descriptions come from the `Args:` block.

The decorator returns the function unchanged, so it stays directly callable and
unit-testable without the runtime.

## Where skills live

Three discovery sources, all optional:

| Source | Use it when |
|---|---|
| `skills/<name>/` with `skill.yaml` | The skill belongs to this repo |
| A package advertising the `sa.skills` entry point | The skill ships as a versioned artifact from another team |
| An explicit module import | Tests, or dynamic registration |

A filesystem skill package is two files:

```
skills/address_normalizer/
├── skill.yaml     # the manifest — reviewable without reading Python
└── skill.py       # the implementation
```

`skill.yaml` overrides anything the decorator derived. Put permissions,
stability, ownership, and timeouts there: a compliance reviewer should be able
to audit what a skill is allowed to do without reading the code.

## The manifest

| Field | Why it matters |
|---|---|
| `name` | Lowercase dotted, e.g. `finance.score_counterparty`. Becomes the tool name `skill_finance_score_counterparty`. |
| `version` | Semantic. Callers can pin; the registry resolves "latest" numerically. |
| `description` | Shown to operators **and to models**. State what it does and when to use it. |
| `required_permissions` | Enforced before the skill runs. |
| `allowed_tools` | Caps what the skill may reach for. Empty means the global policy applies. |
| `idempotent` | `False` disables retries entirely. Set it honestly. |
| `stability` | `experimental` skills are blocked in production by default. |
| `owner` | Required for `stable` skills — this is incident routing. |
| `expose_as_tool` | `False` keeps a skill out of the model-callable surface. |

### Two fields people get wrong

**`idempotent`.** It controls whether the platform will retry after a failure.
A skill that charges a card or sends an email is not idempotent, and marking it
so means a transient network error can produce a double charge. When in doubt,
set it `False` — the contract test rejects `max_retries > 0` on a
non-idempotent skill.

**`description`.** It is not documentation. It is the text a model uses to
decide whether to call your skill. "Processes data" produces bad tool
selection. "Score a counterparty's credit risk from their latest regulatory
filings; call this before approving a new trading relationship" produces good
tool selection.

## Validation

The runtime validates the payload against `input_schema` before your code runs,
and the output against `output_schema` after. Neither is optional work you can
skip — declaring an output schema is what lets a downstream workflow step bind
to a field with confidence.

Override `validate_input` for coercion:

```python
class AddressSkill(Skill):
    async def validate_input(self, payload: dict) -> dict:
        payload = await super().validate_input(payload)
        payload["country"] = payload.get("country", "US").upper()
        return payload
```

## Errors

Raise. The runtime converts the exception into a `SkillResult` with the right
code and decides retryability from it.

```python
from sa_platform.errors import ValidationError, DependencyError, NotFoundError

if not text.strip():
    raise ValidationError("text must not be empty", details={"field": "text"})
```

Choosing the right type matters: `ValidationError` is not retried (the input
will not improve), while `DependencyError` is (the upstream may recover). A bare
`RuntimeError` becomes a non-retryable `ExecutionError`, which is a safe default
but usually not what you meant.

## The class form

Use it when you need lifecycle hooks or injected dependencies:

```python
from sa_skills import Skill, SkillManifest

class CounterpartyScorer(Skill):
    manifest = SkillManifest(
        name="finance.score_counterparty",
        version="2.1.0",
        description="Score a counterparty's credit risk from recent filings.",
        category="analysis",
        stability="stable",
        owner="risk-platform",
        required_permissions=["skills:finance:score"],
        input_schema={
            "type": "object",
            "properties": {"counterparty_id": {"type": "string"}},
            "required": ["counterparty_id"],
            "additionalProperties": False,
        },
    )

    def __init__(self, model_store):
        super().__init__()
        self._store = model_store
        self._model = None

    async def on_load(self):
        self._model = await self._store.load("credit-v2")

    async def health(self) -> bool:
        return self._model is not None

    async def run(self, ctx, payload):
        ctx.check_deadline()
        return await self._model.score(payload["counterparty_id"])
```

`on_load` runs once at registration. A hook that raises is logged and does not
abort startup — one broken skill must not take the service down.

## Using tools from a skill

```python
from sa_tools.executor import tool_executor

async def run(self, ctx, payload):
    result = await tool_executor.invoke("http_request", {...}, ctx=ctx)
    if not result.ok:
        raise DependencyError(result.error["message"])
    return result.output
```

Declare those tools in `allowed_tools`. The executor enforces the scope, which
is what stops a skill from quietly acquiring capabilities its manifest never
disclosed.

## Testing

```python
from sa_skills.testing import SkillHarness, assert_contract

async def test_normalizes():
    harness = SkillHarness(my_skill)
    output = await harness.expect_success({"raw": "1600 Penn Ave"})
    assert output["street"] == "1600 Pennsylvania Avenue"

async def test_rejects_empty():
    harness = SkillHarness(my_skill)
    await harness.expect_failure({"raw": ""}, code="validation_error")

async def test_contract():
    report = await assert_contract(my_skill)
    report.raise_for_failures()
```

`SkillHarness` runs the real runtime against a private registry, so the skill
under test is unaffected by whatever else the process registered.

`assert_contract` is also enforced in CI via `sa skills verify`. It checks:

* the description is substantial enough to be useful
* an input schema is declared and describes an object
* stable skills name an owner
* retries are not enabled on a non-idempotent skill
* deprecated skills explain themselves
* cacheable skills declare a TTL
* the example payload succeeds and its output matches the schema
* an empty payload is rejected when required fields exist

Add an `examples` entry to the manifest and the execution checks run
automatically.

## Versioning

Bump `version` for any change to behaviour or contract. Both versions stay
registered, so callers can pin while they migrate.

Deprecating:

```yaml
stability: deprecated
deprecated_reason: Superseded by the v3 scoring model.
replaced_by: finance.score_counterparty_v3
```

Deprecated skills log a warning on every invocation and are blocked outright in
production environments.

## Checklist

- [ ] Description states what it does **and when to call it**
- [ ] `Args:` documents every parameter
- [ ] `required_permissions` set
- [ ] `idempotent` set honestly; no retries if `False`
- [ ] `owner` set if `stability: stable`
- [ ] `output_schema` declared
- [ ] At least one manifest `examples` entry
- [ ] `allowed_tools` declared if the skill calls tools
- [ ] `sa skills verify` passes
