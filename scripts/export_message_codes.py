"""Write the server's message code registry to the console's test fixture.

Run from the repository root after changing ``growbridge.codes``:

    PYTHONPATH=src python scripts/export_message_codes.py
"""

import json
from pathlib import Path

from growbridge.codes import export

TARGET = Path(__file__).resolve().parents[1] / "tests" / "web" / "fixtures" / "message-codes.json"

if __name__ == "__main__":
    TARGET.write_text(json.dumps(export(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {TARGET}")
