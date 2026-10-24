"""Direct AI provider adapters (replaces the Emergent proxy).

Each adapter reads its API key at call time (secure DB override first, then
env), raises AIError on any failure, and never returns placeholder output —
callers decide whether to retry or fail the job.
"""


class AIError(RuntimeError):
    """A provider call failed or returned unusable output (may be transient)."""


class AIPermanentError(AIError):
    """Retrying the same request won't help (rejected request, policy block)."""


class AIConfigError(AIPermanentError):
    """The account/key can't serve this stage: missing or invalid key, no
    credits, zero quota, or a provider/model without an executor."""


def classify_http_error(stage: str, provider: str, status: int | None, message: str) -> AIError:
    """Map a provider HTTP error to the right AIError subclass."""
    text = f"{provider} call failed ({stage}): HTTP {status}: {message}"
    message = message if isinstance(message, str) else str(message)  # fal sends 422 details as a list
    lowered = message.lower()
    if status in (401, 403) or "insufficient_quota" in lowered or "no credits" in lowered \
            or "credit balance" in lowered or "limit: 0" in lowered:
        return AIConfigError(text)
    if status in (400, 404, 422):
        return AIPermanentError(text)
    return AIError(text)  # 408/409/429/5xx and network issues: worth retrying


async def require_key(env_key: str) -> str:
    from services.secret_overrides_service import get_secret

    value = await get_secret(env_key)
    if not value:
        raise AIConfigError(f"{env_key} is not configured")
    return value
