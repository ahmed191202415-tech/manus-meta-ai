"""Pip must resolve the locked requirements in Railpack's isolated install layer."""
import json
from pathlib import Path
import shutil
import subprocess
import sys


def test_locked_requirements_install_with_only_build_step_inputs(tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "railpack.json").read_text())
    install = config["steps"]["install"]
    # Preserve the generated package/venv inputs instead of replacing them.
    assert install["inputs"][0] == "..."
    # Official Python provider copyInstallFiles, prior to the full source copy:
    manifests = {"requirements.txt", "pyproject.toml", "Pipfile", "poetry.lock", "uv.lock", "pdm.lock"}
    for layer in install["inputs"]:
        if isinstance(layer, dict) and layer.get("local") is True:
            manifests.update(layer.get("include", []))
    for name in manifests:
        source = root / name
        if source.is_file():
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    # The environment is already installed by CI. This checks real pip parsing
    # and resolution with network disabled, without installing or modifying it.
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--dry-run", "--no-index",
         "--disable-pip-version-check", "-r", "requirements.txt"],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
