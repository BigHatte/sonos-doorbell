"""Generates the built-in chimes as 44.1 kHz 16-bit mono WAV files without leading silence."""

import math
import struct
import sys
import wave
from pathlib import Path

RATE = 44100


def tone(freq: float, length: float, decay: float, bell: float = 0.0) -> list[float]:
    """Soft tone with two overtones; `bell` adds a slightly inharmonic partial."""
    samples = []
    for i in range(int(RATE * length)):
        t = i / RATE
        attack = min(1.0, t / 0.005)
        release = min(1.0, (length - t) / 0.05)
        envelope = attack * release * math.exp(-t / decay)
        value = (
            math.sin(2 * math.pi * freq * t)
            + 0.35 * math.sin(2 * math.pi * freq * 2 * t) * math.exp(-t / (decay / 2))
            + 0.15 * math.sin(2 * math.pi * freq * 3 * t) * math.exp(-t / (decay / 3))
            + bell * math.sin(2 * math.pi * freq * 2.76 * t) * math.exp(-t / (decay / 4))
        )
        samples.append(envelope * value)
    return samples


def mix(base: list[float], add: list[float], offset_s: float) -> list[float]:
    offset = int(RATE * offset_s)
    out = base + [0.0] * max(0, offset + len(add) - len(base))
    for i, value in enumerate(add):
        out[offset + i] += value
    return out


def sequence(notes: list[tuple[float, float, float, float]], bell: float = 0.0) -> list[float]:
    """notes: (start s, frequency Hz, length s, decay s)."""
    signal: list[float] = []
    for start, freq, length, decay in notes:
        signal = mix(signal, tone(freq, length, decay, bell), start)
    return signal


def ding_dong() -> list[float]:
    return mix(tone(659.25, 1.2, 0.45), tone(523.25, 1.6, 0.55), 0.55)


def dreiklang() -> list[float]:
    # C5 E5 G5, rising
    return sequence([(0.0, 523.25, 1.4, 0.5), (0.4, 659.25, 1.4, 0.5), (0.8, 783.99, 2.2, 0.7)])


def einzelton() -> list[float]:
    return tone(880.0, 2.4, 0.8, bell=0.12)


def westminster() -> list[float]:
    # First phrase of the Westminster quarters: G#4 F#4 E4 B3
    step = 0.85
    notes = [(i * step, f, 1.8 if i < 3 else 3.2, 0.8 if i < 3 else 1.3) for i, f in enumerate((415.30, 369.99, 329.63, 246.94))]
    return sequence(notes, bell=0.1)


SOUNDS = {
    "ding-dong": ding_dong,
    "dreiklang": dreiklang,
    "einzelton": einzelton,
    "westminster": westminster,
}


def write(path: Path, signal: list[float]) -> None:
    peak = max(abs(s) for s in signal)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(b"".join(struct.pack("<h", int(s / peak * 0.8 * 32767)) for s in signal))


def main(folder: str) -> None:
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    for name, build in SOUNDS.items():
        signal = build()
        write(target / f"{name}.wav", signal)
        print(f"{name}.wav  {len(signal) / RATE:.1f} s")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sounds")
