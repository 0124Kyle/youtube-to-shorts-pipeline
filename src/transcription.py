"""Local STT with VAD, preserving original audio timestamps."""

from pathlib import Path
import sys
import time


def transcribe(audio: Path, model_name: str, device: str, compute_type: str, language: str | None, vad: bool) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Install dependencies: pip install -r requirements.txt") from exc
    try:
        print(f"Loading transcription model '{model_name}' on {device} ({compute_type})...", file=sys.stderr, flush=True)
        started = time.monotonic()
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        print(f"Model ready after {time.monotonic() - started:.1f}s. Preparing audio...", file=sys.stderr, flush=True)
        segments, info = model.transcribe(
            str(audio), beam_size=5, language=language,
            vad_filter=vad, word_timestamps=False,
        )
        print(f"Transcribing {info.duration / 60:.1f} min of audio; progress uses source timestamps...", file=sys.stderr, flush=True)
        # The iterator is lazy: consume it here so errors do not leave a valid-looking transcript.
        rows = []
        last_reported_second = 0
        for segment in segments:
            if segment.text.strip():
                rows.append({"start": round(segment.start, 3), "end": round(segment.end, 3), "text": segment.text.strip()})
            if segment.end - last_reported_second >= 60:
                print(f"  Reached {segment.end / 60:.1f}/{info.duration / 60:.1f} min of audio", file=sys.stderr, flush=True)
                last_reported_second = segment.end
        print(f"Transcription complete: {len(rows)} segments in {time.monotonic() - started:.1f}s.", file=sys.stderr, flush=True)
    except Exception as exc:
        raise RuntimeError(f"Transcription failed: {exc}") from exc
    return {
        "language": info.language,
        "language_probability": info.language_probability,
        "segments": rows,
    }
