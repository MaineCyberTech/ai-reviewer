#!/usr/bin/env python3
"""Call an OpenAI-compatible model and write an advisory PR review to stdout."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

MAX_DIFF = 30_000
MAX_METADATA = 4_000
DEFAULT_ENDPOINT = "https://models.github.ai/inference/chat/completions"
RETRY_STATUS = {429, 500, 502, 503, 504, 524}


def main() -> int:
    if len(sys.argv) != 5:
        print("usage: ai_review.py MODEL PROMPT METADATA DIFF", file=sys.stderr)
        return 2
    model, prompt_path, metadata_path, diff_path = sys.argv[1:5]
    prompt = Path(prompt_path).read_text(encoding="utf-8")
    metadata = Path(metadata_path).read_text(encoding="utf-8")[:MAX_METADATA]
    diff = Path(diff_path).read_text(encoding="utf-8", errors="replace")
    if len(diff) > MAX_DIFF:
        diff = diff[:MAX_DIFF] + "\n\n[Diff truncated to 30 KB.]\n"

    user = (
        "Pull request metadata:\n```json\n"
        + metadata
        + "\n```\n\nDiff:\n```diff\n"
        + diff
        + "\n```\n"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 2000,
    }
    endpoint = os.environ.get("AI_REVIEW_ENDPOINT", DEFAULT_ENDPOINT)
    token = os.environ.get("AI_REVIEW_API_KEY", os.environ.get("GITHUB_TOKEN", ""))
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Kestrel-AI-Review/1.0",
    }
    if token:
        headers["Authorization"] = "Bearer " + token

    body = None
    for attempt in range(1, 4):
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode(),
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                body = json.load(response)
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:2000]
            if exc.code in RETRY_STATUS and attempt < 3:
                print(
                    f"model request returned HTTP {exc.code}; "
                    f"retrying ({attempt}/3)",
                    file=sys.stderr,
                )
                time.sleep(15 * attempt)
                continue
            print(detail, file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001
            if attempt < 3:
                print(
                    f"model request failed: {exc}; retrying ({attempt}/3)",
                    file=sys.stderr,
                )
                time.sleep(15 * attempt)
                continue
            print(f"model request failed: {exc}", file=sys.stderr)
            return 1
    if body is None:
        print("model request failed after retries", file=sys.stderr)
        return 1

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        print(json.dumps(body)[:2000], file=sys.stderr)
        return 1
    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
