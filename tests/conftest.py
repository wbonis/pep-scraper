import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def dashboard_json() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (FIXTURES / "shifts_dashboard.json").read_text(encoding="utf-8")
    )
    return data
