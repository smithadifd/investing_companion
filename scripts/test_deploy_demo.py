"""Run the demo deploy against local SSH, Docker, and HTTP stubs."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "test_case",
    [
        "scope", "db_delayed", "db", "migration", "data_seed", "user_seed",
        "restore", "build", "api", "frontend", "dry_run",
    ],
)
def test_demo_deploy(test_case: str) -> None:
    script = Path(__file__).with_name("test-deploy-demo.sh")
    deploy_script = os.environ.get("DEPLOY_DEMO_SCRIPT")
    command = ["bash", str(script)]
    if deploy_script:
        command.append(deploy_script)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "DEPLOY_TEST_CASE": test_case},
    )
    assert result.returncode == 0, result.stdout + result.stderr
