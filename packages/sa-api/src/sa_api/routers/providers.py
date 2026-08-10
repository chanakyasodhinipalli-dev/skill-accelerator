"""Model provider endpoints: inspect, switch, register, and compare.

This is the operator's view of the routing layer. It exists so that "which model
is answering, and can we move off it" is a question with a live answer rather
than a deployment archaeology exercise.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, SecretStr

from sa_connectors.llm import LLMRouter, get_router
from sa_connectors.llm.base import Message
from sa_platform.config import GatewayDialect, LLMProfile, Vendor
from sa_platform.errors import ValidationError

router = APIRouter(prefix="/providers", tags=["providers"])


def get_llm_router() -> LLMRouter:
    return get_router()


RouterDep = Annotated[LLMRouter, Depends(get_llm_router)]


class RegisterProfileRequest(BaseModel):
    """A profile added at runtime.

    Credentials supplied here live in process memory only: they are never
    written to disk and never returned by any endpoint. That makes the console
    usable for trying a vendor without editing configuration, while keeping the
    durable path — environment variables and config files — the one that
    survives a restart.
    """

    name: str = Field(description="Identifier used to select this profile")
    vendor: Vendor
    model: str
    label: str = ""
    description: str = ""
    base_url: str | None = None
    api_key: SecretStr | None = None
    api_key_env: str | None = None
    api_version: str | None = None
    dialect: GatewayDialect | None = None
    auth_header: str = ""
    auth_scheme: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    max_tokens: int = Field(default=8000, ge=1)
    temperature: float | None = None
    effort: str | None = None
    activate: bool = False


class CompletionRequest(BaseModel):
    prompt: str
    system: str | None = None
    profile: str | None = Field(default=None, description="Overrides the active profile")
    max_tokens: int | None = None


class CompareRequest(BaseModel):
    prompt: str
    system: str | None = None
    profiles: list[str] = Field(min_length=1, description="Profiles to run the same prompt against")
    max_tokens: int | None = Field(default=512, ge=1)


@router.get("", summary="List model profiles")
async def list_profiles(llm: RouterDep) -> dict[str, Any]:
    """Every configured route to a model, with live counters."""
    return {
        "active": llm.active,
        "count": len(llm.names()),
        "profiles": llm.describe_all(),
    }


@router.get("/active", summary="Which profile is serving requests")
async def active_profile(llm: RouterDep) -> dict[str, Any]:
    decision = llm.last_decision
    return {
        **llm.describe(llm.active),
        "last_call": (
            {
                "served_by": decision.profile,
                "attempted": decision.attempted,
                "fell_back": decision.fell_back,
            }
            if decision
            else None
        ),
    }


@router.get("/health", summary="Probe every profile")
async def provider_health(llm: RouterDep) -> dict[str, Any]:
    return await llm.health_all()


@router.get("/{name}", summary="Describe one profile")
async def describe_profile(name: str, llm: RouterDep) -> dict[str, Any]:
    return llm.describe(name)


@router.get("/{name}/models", summary="Models this endpoint will serve")
async def list_models(name: str, llm: RouterDep) -> dict[str, Any]:
    """Ask the endpoint what it offers.

    Pointed at a gateway this returns the organisation's approved model list,
    which is otherwise a wiki page that goes stale.
    """
    return {"profile": name, "models": await llm.list_models(name)}


@router.post("", status_code=201, summary="Register a profile at runtime")
async def register_profile(request: RegisterProfileRequest, llm: RouterDep) -> dict[str, Any]:
    profile = LLMProfile(**request.model_dump(exclude={"activate"}))
    llm.register(profile, activate=request.activate)
    return llm.describe(profile.name)


@router.post("/{name}/activate", summary="Switch the active profile")
async def activate_profile(name: str, llm: RouterDep) -> dict[str, Any]:
    llm.use(name)
    return llm.describe(name)


@router.post("/{name}/test", summary="Send a probe prompt to one profile")
async def test_profile(
    name: str,
    llm: RouterDep,
    prompt: str = Query(default="Reply with the single word: ready."),
) -> dict[str, Any]:
    """Prove a profile works end to end — credential, endpoint, and model id.

    A health probe only shows the endpoint answers. This shows a completion
    actually comes back, which is the thing that fails in practice.
    """
    started = time.perf_counter()
    try:
        response = await llm.complete([Message.user(prompt)], max_tokens=64, profile=name)
    except Exception as exc:  # noqa: BLE001 - reported as a result, not a 500
        return {
            "profile": name,
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    return {
        "profile": name,
        "ok": True,
        "text": response.text,
        "model": response.model,
        "stop_reason": response.stop_reason.value,
        "usage": response.usage.model_dump(),
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


@router.post("/complete", summary="Run a prompt through the router")
async def complete(request: CompletionRequest, llm: RouterDep) -> dict[str, Any]:
    """One completion, honouring the routing and fallback rules."""
    response = await llm.complete(
        [Message.user(request.prompt)],
        system=request.system,
        max_tokens=request.max_tokens,
        profile=request.profile,
    )
    decision = llm.last_decision
    return {
        "text": response.text,
        "thinking": response.thinking,
        "model": response.model,
        "stop_reason": response.stop_reason.value,
        "refused": response.was_refused,
        "usage": response.usage.model_dump(),
        "served_by": decision.profile if decision else llm.active,
        "fell_back": decision.fell_back if decision else False,
    }


@router.post("/compare", summary="Run one prompt against several profiles")
async def compare(request: CompareRequest, llm: RouterDep) -> dict[str, Any]:
    """Side-by-side output from several vendors.

    The honest way to choose a model for a task, and the honest way to check a
    gateway routes where it claims to.
    """
    if len(request.profiles) > 6:
        raise ValidationError(
            "compare at most six profiles at once",
            details={"requested": len(request.profiles)},
        )

    results: list[dict[str, Any]] = []
    for name in request.profiles:
        started = time.perf_counter()
        try:
            response = await llm.complete(
                [Message.user(request.prompt)],
                system=request.system,
                max_tokens=request.max_tokens,
                profile=name,
            )
        except Exception as exc:  # noqa: BLE001 - one failure must not hide the rest
            results.append({"profile": name, "ok": False, "error": str(exc)})
            continue
        results.append(
            {
                "profile": name,
                "ok": True,
                "text": response.text,
                "model": response.model,
                "usage": response.usage.model_dump(),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
    return {"prompt": request.prompt, "results": results}
