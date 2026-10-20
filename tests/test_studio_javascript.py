"""Expose each dependency-free JavaScript unit test through the existing pytest command."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

TEST_FILE = Path(__file__).parent / "js" / "studio_integrity.test.cjs"
NODE = shutil.which("node")
CASES = re.findall(r'^test\("([^"]+)"', TEST_FILE.read_text(encoding="utf-8"), re.MULTILINE)


@pytest.fixture(scope="module")
def node():
    if NODE is None:
        pytest.skip("Node.js 20+ is required for Studio JavaScript unit tests")
    version = subprocess.run([NODE, "--version"], capture_output=True, text=True, timeout=10, check=True)
    if int(version.stdout.strip().lstrip("v").split(".")[0]) < 20:
        pytest.skip("Node.js 20+ is required for Studio JavaScript unit tests")
    return NODE


@pytest.mark.parametrize("case", CASES, ids=CASES)
def test_studio_javascript(case, node):
    result = subprocess.run([node, "--test", f"--test-name-pattern=^{re.escape(case)}$", str(TEST_FILE)],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
