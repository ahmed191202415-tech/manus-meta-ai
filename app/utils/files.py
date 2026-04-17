from pathlib import Path
from datetime import datetime
from typing import Optional
import re


def sanitize_file_name(name: Optional[str], default_prefix: str, extension: str) -> str:
    if name:
        base = Path(name).name
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{default_prefix}_{timestamp}.{extension}"

    if not base.lower().endswith(f".{extension.lower()}"):
        base = f"{base}.{extension}"

    stem = Path(base).stem
    stem = re.sub(r"[^\w\-\u0600-\u06FF ]+", "_", stem).strip()

    if not stem:
        stem = f"{default_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    return f"{stem}.{extension}"
