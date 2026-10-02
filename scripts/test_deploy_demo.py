"""Run the demo deploy against local SSH, Docker, and HTTP stubs."""

import os
import subprocess
from pathlib import Path


def test_demo_deploy() -> None:
    script = Path(__file__).with_name("test-deploy-demo.sh")
    deploy_script = os.environ.get("DEPLOY_DEMO_SCRIPT")
    command = ["bash", str(script)]
    if deploy_script:
        command.append(deploy_script)
    result = subprocess.run(
        command, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
