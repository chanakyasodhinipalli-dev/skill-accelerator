"""sa-skills — reusable, versioned business capabilities.

Author a skill::

    from sa_skills import skill

    @skill(category="analysis", owner="risk-platform", stability="stable")
    async def score_counterparty(counterparty_id: str, as_of: str | None = None) -> dict:
        '''Score a counterparty's credit risk from the latest filings.

        Args:
            counterparty_id: Internal counterparty identifier.
            as_of: ISO date to score against. Defaults to today.
        '''
        ...

Invoke one::

    from sa_skills import skill_runtime

    result = await skill_runtime.invoke("score_counterparty", {"counterparty_id": "C-1"})
    if result.ok:
        print(result.output)
"""

from __future__ import annotations

from .base import CompositeSkill, FunctionSkill, Skill
from .decorators import drain_pending, skill
from .loader import SkillLoader
from .models import (
    SkillCategory,
    SkillManifest,
    SkillRequest,
    SkillResult,
    SkillStability,
    SkillStatus,
)
from .policy import SkillPolicy
from .registry import SkillRegistry, skill_registry
from .runtime import SkillRuntime, skill_runtime
from .testing import SkillHarness, assert_contract, test_context

__version__ = "0.1.0"

__all__ = [
    "CompositeSkill",
    "FunctionSkill",
    "Skill",
    "SkillCategory",
    "SkillHarness",
    "SkillLoader",
    "SkillManifest",
    "SkillPolicy",
    "SkillRegistry",
    "SkillRequest",
    "SkillResult",
    "SkillRuntime",
    "SkillStability",
    "SkillStatus",
    "__version__",
    "assert_contract",
    "drain_pending",
    "skill",
    "skill_registry",
    "skill_runtime",
    "test_context",
]
