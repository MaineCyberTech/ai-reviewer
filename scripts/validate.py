#!/usr/bin/env python3
from pathlib import Path
import yaml

for path in (
    ".github/workflows/ai-review.yml",
    ".github/workflows/bot-approval.yml",
    ".github/workflows/validate.yml",
):
    yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    print(f"OK {path}")
