"""One scene take cut into its lines: each piece holds its own line and nothing of the next."""
import io
import os
import sys
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "gheras_comfy_unit")

from services import shot_pipeline  # noqa: E402

SR = 24000


def _wav(parts: list[tuple[float, float]]) -> bytes:
    """(seconds, tone Hz or 0 for silence) one after the other, as 16-bit mono."""
    chunks = []
    for seconds, hz in parts:
        t = np.arange(int(seconds * SR)) / SR
        chunks.append(0.3 * np.sin(2 * np.pi * hz * t) if hz else np.zeros_like(t))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.concatenate(chunks) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def _samples(data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(data)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float)


def _tone(a: np.ndarray) -> int:
    spectrum = np.abs(np.fft.rfft(a))
    return round(float(np.fft.rfftfreq(len(a), 1 / SR)[spectrum.argmax()]))


def test_each_piece_is_its_own_line_even_after_a_leading_silence():
    # The take opens with half a second of silence, as Gemini's do: the cut used to slide by
    # it, so the second line's first sound ended the first piece and the second began mid-word.
    take = _wav([(0.5, 0), (2.0, 440), (0.4, 0), (2.0, 880), (0.3, 0)])
    pieces = shot_pipeline._split_take(take, ["one two three four", "five six seven eight"], 1.9)
    assert pieces and len(pieces) == 2
    first, second = (_samples(p) for p in pieces)
    edge = int(0.1 * SR)
    assert _tone(first[:edge]) == 440 and _tone(first[-edge:]) == 440
    assert _tone(second[:edge]) == 880 and _tone(second[-edge:]) == 880
    # the second line starts at its very first sound and the first keeps all of its own
    assert abs(len(first) / SR - 2.0) < 0.05 and abs(len(second) / SR - 2.0) < 0.05


def test_the_cut_misses_a_breath_in_the_middle_of_the_pause():
    # A faint breath (quieter than the pause threshold) at the pause's middle: cut there and
    # the first piece ended on half a breath.
    breath = 0.012 * np.sin(2 * np.pi * 150 * np.arange(int(0.1 * SR)) / SR)
    take = np.concatenate([np.zeros(int(0.5 * SR)), 0.3 * np.sin(2 * np.pi * 440 * np.arange(2 * SR) / SR),
                           np.zeros(int(0.1 * SR)), breath, np.zeros(int(0.3 * SR)),
                           0.3 * np.sin(2 * np.pi * 880 * np.arange(2 * SR) / SR), np.zeros(int(0.3 * SR))])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((take * 32767).astype("<i2").tobytes())
    pieces = shot_pipeline._split_take(buf.getvalue(), ["one two three four", "five six seven eight"], 1.9)
    first = _samples(pieces[0])
    assert abs(len(first) / SR - 2.0) < 0.05 and _tone(first[-int(0.1 * SR):]) == 440
