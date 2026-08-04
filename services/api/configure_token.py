from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


ROLES = {"analyst", "operator", "model_engineer", "admin"}


def update_token_store(path: Path, subject: str, role: str, token: str) -> None:
    if role not in ROLES:
        raise ValueError("unsupported role")
    if len(token) < 24:
        raise ValueError("token is too short")
    value = {"schema_version": "1.0.0", "principals": []}
    if path.is_file():
        value = json.loads(path.read_text(encoding="utf-8"))
    principals = [
        item
        for item in value.get("principals", [])
        if isinstance(item, dict) and item.get("subject") != subject
    ]
    principals.append(
        {
            "subject": subject,
            "role": role,
            "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {"schema_version": "1.0.0", "principals": principals},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: configure_token.py PATH SUBJECT ROLE")
    update_token_store(Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.stdin.read())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
