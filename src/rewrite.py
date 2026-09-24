"""Cost-aware candidate selection and attributed draft rewriting.

Candidates are ranked without an API. Generated drafts always need fact review.
"""

import hashlib
import json
import os
import re
from pathlib import Path

from .pipeline import save_json

PROMPT_VERSION = 3
DEFAULT_MODEL = "gemini-3.5-flash-lite"
WINDOW_SECONDS = 120
STRIDE_SECONDS = 60
MAX_SOURCE_CHARS = 1800
MAX_OUTPUT_TOKENS = 1024
INPUT_RATE_PER_MILLION = 0.30  # Gemini 3.5 Flash-Lite paid standard, 2026-09-23
OUTPUT_RATE_PER_MILLION = 2.50
NUMBERS = re.compile(r"\d[\d,.]*\s*(?:%|％|萬|千|億|元|年|坪)?|[零〇一二三四五六七八九十百千兩]+(?:萬|億|元|年|坪|%|％|成|趴)")
# Confirmed by the user for this source video. Keep transcript.json untouched;
# these narrow replacements only affect candidate text sent to the rewriting API.
SOURCE_ASR_CORRECTIONS = {
    "KjAI9r8tnOs": (
        ("星期安2.0", "新青安2.0"),
        ("親親愛有寬限", "新青安有寬限"),
        ("新加坡政策", "新青安政策"),
        ("新西安", "新青安"),
        ("新清安", "新青安"),
        ("新陳安", "新青安"),
    ),
}


def correct_source_terms(text: str, video_id: str | None) -> tuple[str, list[dict]]:
    corrected = text
    changes = []
    for old, new in SOURCE_ASR_CORRECTIONS.get(video_id, ()):
        occurrences = corrected.count(old)
        if occurrences:
            corrected = corrected.replace(old, new)
            changes.append({"heard_as": old, "corrected_to": new, "occurrences": occurrences})
    return corrected, changes


def load_inputs(transcript_path: Path, metadata_path: Path) -> tuple[dict, dict]:
    try:
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot load input JSON: {exc}") from exc
    if not isinstance(transcript, dict) or not isinstance(metadata, dict):
        raise ValueError("Transcript and metadata must be JSON objects")
    video_id = transcript.get("video_id")
    if not video_id or video_id != metadata.get("video_id"):
        raise ValueError("Transcript and metadata video IDs must match")
    if not metadata.get("source_url") or not metadata.get("channel"):
        raise ValueError("Metadata needs source_url and channel for attribution")
    segments = transcript.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("Transcript has no segments")
    previous = -1.0
    for item in segments:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ValueError("Transcript contains an invalid segment")
        start, end = item.get("start"), item.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or start < previous or end <= start:
            raise ValueError("Transcript timestamps must be ordered and positive")
        previous = start
    return transcript, metadata


def _ngrams(text: str) -> set[str]:
    chars = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text)
    return {chars[i:i+2] for i in range(len(chars)-1)}


def make_candidates(segments: list[dict], title: str, count: int = 3, video_id: str | None = None) -> dict:
    if count < 1 or count > 3:
        raise ValueError("--top must be between 1 and 3")
    duration = segments[-1]["end"]
    title_pairs = _ngrams(title)
    candidates = []
    for start in range(0, max(1, int(duration)), STRIDE_SECONDS):
        end = min(start + WINDOW_SECONDS, duration)
        rows = [s for s in segments if start <= s["start"] < end]
        if not rows:
            continue
        content = "".join(s["text"] for s in rows)
        if len(content) < 100 or end - rows[0]["start"] < 45:
            continue
        corrected, corrections = correct_source_terms(content, video_id)
        numbers = len(NUMBERS.findall(corrected))
        title_matches = len(title_pairs & _ngrams(corrected))
        score = round(min(numbers, 12) * 1.2 + min(title_matches, 15) * 0.8 + min(len(corrected), 550) / 100, 2)
        candidate = {
            "id": f"c{len(candidates)+1:02d}",
            "start": round(rows[0]["start"], 2), "end": round(rows[-1]["end"], 2),
            "score": score, "numeric_mentions": numbers,
            "text": content,
        }
        if corrections:
            candidate.update({"corrected_text": corrected, "asr_corrections": corrections})
        candidates.append(candidate)
    ranked = sorted(candidates, key=lambda c: (-c["score"], c["start"]))
    selected = []
    # Prefer widely separated stories. Relax spacing for shorter source videos.
    for spacing in (duration / (count + 0.5), WINDOW_SECONDS * 1.5, 0):
        selected = []
        for candidate in ranked:
            if all(abs(candidate["start"] - x["start"]) >= spacing and
                   (candidate["end"] <= x["start"] or candidate["start"] >= x["end"])
                   for x in selected):
                selected.append(candidate)
                if len(selected) == count:
                    break
        if len(selected) == count:
            break
    if len(selected) < count:
        raise ValueError("Not enough non-overlapping content for the requested number of scripts")
    return {"candidates": candidates, "suggested_ids": [x["id"] for x in sorted(selected, key=lambda c: c["start"])]}


def choose(plan: dict, selection: str | None, top: int) -> list[dict]:
    index = {c["id"]: c for c in plan["candidates"]}
    ids = [x.strip() for x in selection.split(",")] if selection else plan["suggested_ids"][:top]
    if not ids or len(ids) > top or len(ids) != len(set(ids)) or any(i not in index for i in ids):
        raise ValueError("--select must contain 1 to --top distinct IDs from candidates.json")
    chosen = [index[i] for i in ids]
    if any(a["start"] < b["end"] and b["start"] < a["end"] for n, a in enumerate(chosen) for b in chosen[n+1:]):
        raise ValueError("Selected candidates must not overlap")
    return chosen


def make_prompt(candidate: dict, metadata: dict) -> str:
    transcript_header = (
        "轉錄片段（ASR 可能有錯；使用者已確認本片政策名稱為『新青安』，下方已修正已知誤辨詞）："
        if candidate.get("asr_corrections") else "轉錄片段（ASR 可能有錯）："
    )
    return f"""你是繁體中文新聞短影音編輯。請根據下方轉錄片段，寫一支約 35–60 秒的原創短片旁白草稿。
原影片標題：{metadata.get('title', '')}
來源頻道：{metadata['channel']}
來源 URL：{metadata['source_url']}
來源時間：{candidate['start']:.1f}–{candidate['end']:.1f} 秒

規則：
1. 從事實重新構思敘事角度、句型與用字；不可逐句改同義詞、不可照抄受訪者話語。
2. 只用片段能支持的資訊；不要推測政策、數據的因果關係。明顯的語音辨識錯字不要照搬；不確定就略過並列入 review_notes。
3. 數字、地名、政策名稱如果不確定，略過或列為待核對；不可補造數字或引言。
4. 影片來源會由程式另外加在旁白開頭；body 與 hook 中不必重複來源。
5. 畫面以可實際拍攝的日常情境影片為主，不能使用原影片畫面或截圖；不可將資料圖表當成現場實況。若必須呈現圖表，須另依已查證的數據用程式重繪並列入 review_notes。
6. 僅輸出 JSON：title（短標題）、hook（一句開場）、body（約 100–180 個繁體中文字的旁白）、visual_plan（2–3 個按敘事順序的實拍情境描述）、stock_queries（與 visual_plan 一一對應、可在素材庫搜尋的 2–3 個具體英文動態鏡頭搜尋詞，例如 hands using calculator at home；不可要求某位特定人物或事件真實影像）、review_notes（待查事實的陣列）。

{transcript_header}
{candidate.get('corrected_text', candidate['text'])[:MAX_SOURCE_CHARS]}"""


def call_gemini(prompt: str, model: str) -> tuple[str, dict]:
    try:
        from google import genai
        from google.genai import types
        from pydantic import BaseModel
    except ImportError as exc:
        raise RuntimeError(f"Could not import Gemini dependencies: {exc}. Install requirements.txt using the Python interpreter running this command") from exc
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or api_key == "replace_with_your_key":
        raise RuntimeError("Set GEMINI_API_KEY in your environment or .env before --generate")
    client = genai.Client(api_key=api_key)
    class ScriptResponse(BaseModel):
        title: str
        hook: str
        body: str
        visual_plan: list[str]
        stock_queries: list[str]
        review_notes: list[str]

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=ScriptResponse.model_json_schema(),
                temperature=0.4,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
        )
        if not response.text:
            raise ValueError("Empty model response")
        usage = response.usage_metadata
        tokens = {
            "input_tokens": getattr(usage, "prompt_token_count", None),
            "output_tokens": getattr(usage, "candidates_token_count", None),
            "thinking_tokens": getattr(usage, "thoughts_token_count", None),
            "total_tokens": getattr(usage, "total_token_count", None),
        }
        return response.text, tokens
    except Exception as exc:
        if getattr(exc, "code", None) == 404:
            raise RuntimeError(
                f"Model '{model}' is not available to this API key or for generateContent. "
                "Run 'python check_models.py' and choose an accessible model with --model."
            ) from exc
        raise RuntimeError(f"Gemini request failed: {exc}") from exc
    finally:
        client.close()


def _normalized(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text).lower()


def validate_draft(raw: dict, candidate: dict, metadata: dict) -> dict:
    if not isinstance(raw, dict) or any(not isinstance(raw.get(k), str) or not raw[k].strip() for k in ("title", "hook", "body")):
        raise ValueError("Model returned an incomplete script")
    if not isinstance(raw.get("visual_plan"), list) or not all(isinstance(v, str) for v in raw["visual_plan"]):
        raise ValueError("Model returned an invalid visual plan")
    queries = raw.get("stock_queries")
    if (not isinstance(queries, list) or not 2 <= len(queries) <= 3 or
            len(queries) != len(raw["visual_plan"]) or
            any(not isinstance(query, str) or not 3 <= len(query.strip()) <= 100 for query in queries)):
        raise ValueError("Model must provide 2–3 stock queries matching the live-action visual plan")
    notes = raw.get("review_notes", [])
    if not isinstance(notes, list) or not all(isinstance(n, str) for n in notes):
        raise ValueError("Model returned invalid review notes")
    outlet = metadata["channel"]
    narration = f"根據 {outlet} 發布的報導，{raw['hook'].strip()} {raw['body'].strip()}"
    source = _normalized(candidate.get("corrected_text", candidate["text"]))
    output = _normalized(raw["hook"] + raw["body"])
    issues = ["請回聽來源片段，確認政策名稱、地名及因果表述。"] + notes
    if candidate.get("asr_corrections"):
        issues.append("已依使用者確認將逐字稿中的新青安誤辨詞用於改寫時修正；請回聽核對政策細節。")
    # Flag continuous source wording for editing; a local check cannot certify originality.
    if any(output[i:i+24] in source for i in range(max(0, len(output)-23))):
        issues.append("旁白與來源有至少 24 字連續相同，請重寫該句。")
    if NUMBERS.search(raw["hook"] + raw["body"]):
        issues.append("旁白包含數字；請逐項對照原影片和其數據來源。")
    return {
        "video_id": metadata["video_id"], "source_url": metadata["source_url"],
        "source_channel": outlet,
        "source_interval": {"start": candidate["start"], "end": candidate["end"]},
        "candidate_id": candidate["id"], "title": raw["title"].strip(),
        "narration": narration, "visual_plan": raw["visual_plan"],
        "stock_queries": [query.strip() for query in queries],
        "review_status": "needs_human_review", "review_notes": issues,
    }


def _digest(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def _load_cached(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def estimated_paid_equivalent(tokens: dict | None, model: str) -> float | None:
    """Estimate a standard paid-tier charge; free-tier billing may be zero."""
    if model != DEFAULT_MODEL or not isinstance(tokens, dict):
        return None
    inp = tokens.get("input_tokens")
    if not isinstance(inp, int):
        return None
    output_parts = (tokens.get("output_tokens") or 0) + (tokens.get("thinking_tokens") or 0)
    total = tokens.get("total_tokens")
    out = max(output_parts, total - inp if isinstance(total, int) else 0)
    return round((inp * INPUT_RATE_PER_MILLION + out * OUTPUT_RATE_PER_MILLION) / 1_000_000, 6)


def plan_and_generate(transcript_path: Path, metadata_path: Path, output_dir: Path, generate: bool = False, selection: str | None = None, top: int = 3, model: str = DEFAULT_MODEL) -> tuple[Path, list[Path]]:
    transcript, metadata = load_inputs(transcript_path, metadata_path)
    plan = make_candidates(transcript["segments"], metadata.get("title", ""), top, transcript["video_id"])
    chosen = choose(plan, selection, top)
    plan.update({
        "video_id": metadata["video_id"], "source_url": metadata["source_url"],
        "selected_ids": [c["id"] for c in chosen],
        "selection_method": "local numeric/title relevance heuristic; review before publishing",
        "estimated_paid_cost_usd": round(len(chosen) * ((MAX_SOURCE_CHARS * 1.5 + 600) * INPUT_RATE_PER_MILLION + MAX_OUTPUT_TOKENS * OUTPUT_RATE_PER_MILLION) / 1_000_000, 5),
        "note": "Estimate assumes maximum source characters and output tokens; real token usage, tier and billing can differ.",
    })
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "candidates.json"
    save_json(plan_path, plan)
    if not generate:
        return plan_path, []

    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError("Install dependencies: pip install -r requirements.txt") from exc
    load_dotenv()
    if not os.environ.get("GEMINI_API_KEY") or os.environ["GEMINI_API_KEY"] == "replace_with_your_key":
        raise RuntimeError("Set GEMINI_API_KEY in .env or your environment before --generate")
    if model != DEFAULT_MODEL:
        plan["estimated_paid_cost_usd"] = None
        save_json(plan_path, plan)

    paths = []
    for candidate in chosen:
        prompt = make_prompt(candidate, metadata)
        key = _digest(model, str(PROMPT_VERSION), prompt)
        raw_path = output_dir / f"response_{key}.json"
        script_path = output_dir / f"script_{candidate['id']}_{key}.json"
        cached = _load_cached(raw_path)
        if cached is None:
            print(f"Calling {model} for {candidate['id']} ({candidate['start']:.0f}–{candidate['end']:.0f}s)...", flush=True)
            response_text, tokens = call_gemini(prompt, model)
            cached = {"response_text": response_text, "usage": tokens, "model": model, "prompt_version": PROMPT_VERSION}
            # Persist the API result before any validation, so a failed validation won't repeat a paid call.
            save_json(raw_path, cached)
        if not isinstance(cached.get("response_text"), str):
            raise ValueError(f"Invalid cached API response: {raw_path}")
        try:
            parsed = json.loads(cached["response_text"])
        except ValueError as exc:
            raise ValueError(f"Model response is not JSON; saved for review at {raw_path}") from exc
        draft = validate_draft(parsed, candidate, metadata)
        draft.update({"model": model, "usage": cached.get("usage"),
                      "estimated_paid_equivalent_usd": estimated_paid_equivalent(cached.get("usage"), model),
                      "prompt_cache_key": key})
        save_json(script_path, draft)
        paths.append(script_path)
    return plan_path, paths
