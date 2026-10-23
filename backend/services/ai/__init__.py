"""Direct AI provider adapters (replaces the Emergent proxy).

Each adapter reads its API key at call time (secure DB override first, then
env), raises AIError on any failure, and never returns placeholder output —
callers decide whether to retry or fail the job.
"""


class AIError(RuntimeError):
    """A provider call failed or returned unusable output."""


class AIConfigError(AIError):
    """The stage is configured with a provider/key we cannot call."""


async def require_key(env_key: str) -> str:
    from services.secret_overrides_service import get_secret

    value = await get_secret(env_key)
    if not value:
        raise AIConfigError(f"{env_key} is not configured")
    return value
