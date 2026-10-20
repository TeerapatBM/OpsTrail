"""Optional dependency-free service-worker behavioral harness."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_extension_worker():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is optional; run node --test tests/browser_extension.cjs separately")
    result = subprocess.run([node, "--test", str(Path(__file__).with_name("browser_extension.cjs"))],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
