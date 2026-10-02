"""Generates a two-tone "ding-dong" chime as 44.1 kHz WAV without leading silence."""

import math
import struct
import sys
import wave

RATE = 44100


def tone(freq: float, length: float, decay: float) -> list[float]:
    samples = []
    for i in range(int(RATE * length)):
        t = i / RATE
        attack = min(1.0, t / 0.005)
        envelope = attack * math.exp(-t / decay)
        value = (
            math.sin(2 * math.pi * freq * t)
            + 0.35 * math.sin(2 * math.pi * freq * 2 * t) * math.exp(-t / (decay / 2))
            + 0.15 * math.sin(2 * math.pi * freq * 3 * t) * math.exp(-t / (decay / 3))
        )
        samples.append(envelope * value)
    return samples


def mix(base: list[float], add: list[float], offset_s: float) -> list[float]:
    offset = int(RATE * offset_s)
    out = base + [0.0] * max(0, offset + len(add) - len(base))
    for i, value in enumerate(add):
        out[offset + i] += value
    return out


def main(path: str) -> None:
    signal = mix(tone(659.25, 1.2, 0.45), tone(523.25, 1.6, 0.55), 0.55)
    peak = max(abs(s) for s in signal)
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(b"".join(struct.pack("<h", int(s / peak * 0.8 * 32767)) for s in signal))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sounds/gong.wav")
