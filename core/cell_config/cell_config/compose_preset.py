"""Run an operator-provided Compose preset without a second plan renderer.

Preset paths and service names are deployment-time configuration, never values
accepted from an HTTP caller. This shares the deployment serialization boundary.
"""

import os
import subprocess
from pathlib import Path

from .deploy import Deployment


class ComposePreset(Deployment):
    def __init__(self, files, project):
        super().__init__(project)
        self.files = [Path(file).resolve(strict=True) for file in files]

    def command(self, *arguments):
        command = ["docker", "compose", "--project-name", self.project]
        for file in self.files:
            command += ["--file", str(file)]
        return command + list(arguments)

    def run(self, action, doc=None, env=None):
        operations = {
            "plan": ["--profile", "*", "config", "--format", "json"],
            "status": ["ps", "--all", "--format", "json"],
            "up": [
                "up",
                "-d",
                "--no-build",
                "--pull",
                os.environ.get("MRP_IMAGE_PULL_POLICY", "never"),
            ],
            "down": ["down"],
        }
        if action not in operations:
            raise ValueError("Unsupported preset operation.")
        with self.lock:
            environment = None if env is None else {**os.environ, **env}
            return subprocess.run(
                self.command(*operations[action]),
                capture_output=True,
                text=True,
                timeout=3600 if action == "up" else 120,
                check=False,
                env=environment,
            )
