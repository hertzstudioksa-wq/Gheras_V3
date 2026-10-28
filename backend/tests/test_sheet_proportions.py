"""A drawn sheet's big head is made the right size for the age by a Qwen edit (the owner's pick), never by
stretching the body; a failed edit keeps the GPT sheet."""
import asyncio
import os

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "gheras_comfy_unit")

import pytest  # noqa: E402

from services import sheet_proportions as sp  # noqa: E402
from services.ai import AIError, image_client  # noqa: E402


def test_the_edit_says_how_many_heads_tall_for_the_age():
    assert "seven and a half heads tall" in sp.prompt_for(None, adult=True)
    assert "a 4-year-old child about four and a half heads tall" in sp.prompt_for(4, adult=False)
    assert "a 10-year-old child about six heads tall" in sp.prompt_for("10", adult=False)
    assert "a young child about five heads tall" in sp.prompt_for(None, adult=False)
    for text in (sp.prompt_for(None, True), sp.prompt_for(4, False)):
        assert "<image1>" in text and "exactly the same person with the same face" in text and "head drawn smaller" in text
    # the four-year-old came back with a beard when the list said "face, hair, beard"
    assert "no beard or moustache" in sp.prompt_for(4, False) and "none where it has none" not in sp.prompt_for(4, False)
    assert "none where it has none" in sp.prompt_for(None, True) and "no beard" not in sp.prompt_for(None, True)
    assert sp.MODEL == "comfy/sheet_qwen21"
    from services.ai import comfy

    assert "sheet_qwen21" in comfy.WORKFLOWS


def test_the_sheet_comes_back_from_qwen_or_stays_as_drawn(monkeypatch):
    calls = []

    async def qwen(**k):
        calls.append(k)
        return b"smaller head", "image/png", {"gpu_seconds": 12.5}

    monkeypatch.setattr(image_client, "comfy_image", qwen)
    out, done = asyncio.run(sp.real_proportions(b"gpt sheet", age=4, adult=False))
    assert out == b"smaller head" and done == {"applied": True, "gpu_seconds": 12.5}
    assert calls[0]["model"] == sp.MODEL and calls[0]["references"] == [b"gpt sheet"]

    async def down(**k):
        raise AIError("comfy call failed: HTTP 502")

    monkeypatch.setattr(image_client, "comfy_image", down)
    assert asyncio.run(sp.real_proportions(b"gpt sheet", adult=True)) == (b"gpt sheet", {"applied": False,
                                                                                         "reason": "AIError"})

    async def broke(**k):
        raise AIError("comfy: InsufficientFundsError: not enough credits")

    monkeypatch.setattr(image_client, "comfy_image", broke)
    from services import engine_health

    monkeypatch.setattr(engine_health, "is_balance_message", lambda e: "InsufficientFunds" in str(e))
    with pytest.raises(AIError):
        asyncio.run(sp.real_proportions(b"gpt sheet", adult=True))
