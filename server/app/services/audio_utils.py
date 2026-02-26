import math
import wave
import struct
from pathlib import Path


def sine_wave(path: str, freq: float = 440.0, duration: float = 1.0, sr: int = 16000) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = int(duration * sr)
    with wave.open(str(p), 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        for i in range(n):
            val = int(32767 * 0.25 * math.sin(2 * math.pi * freq * i / sr))
            wf.writeframes(struct.pack('<h', val))
    return str(p)


def peaks_for_wave(path: str, buckets: int = 64) -> list[float]:
    with wave.open(path, 'rb') as wf:
        frames = wf.readframes(wf.getnframes())
        samples = [abs(struct.unpack('<h', frames[i:i+2])[0]) / 32767 for i in range(0, len(frames), 2)]
    if not samples:
        return [0.0] * buckets
    step = max(1, len(samples) // buckets)
    return [max(samples[i:i+step]) if samples[i:i+step] else 0.0 for i in range(0, len(samples), step)][:buckets]
