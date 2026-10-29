#!/usr/bin/env python3
"""Part 1 gateway tests: the shared checks (shared/gateway_suite.py) against the Docker data plane.

Reads part-01/.env, takes engineering's tools from config/github-mcp.yaml, and --fail-closed stops
the ai-pii-service container. From the repository root:
    python3 part-01/test_gateway.py [--fail-closed]
"""

import re
import subprocess
import sys
from pathlib import Path

PART = Path(__file__).resolve().parent
MCP_CONFIG = PART / "config" / "github-mcp.yaml"
COMPOSE = ["docker", "compose", "-f", str(PART / "docker-compose.yaml")]

sys.path.insert(0, str(PART.parent / "shared"))
import gateway_suite as base  # noqa: E402


class DockerSuite(base.Suite):
    def approved_tools(self):
        """Tools engineering may use, read from the uncommented entries in github-mcp.yaml."""
        tools = set()
        for line in MCP_CONFIG.read_text().splitlines():
            if line.lstrip().startswith("#"):
                continue
            m = re.search(r"name:\s*([a-z_]+).*allow:\s*\[[^\]]*\bengineering\b", line)
            if m:
                tools.add(m.group(1))
        return tools

    def stop_pii(self):
        subprocess.run(COMPOSE + ["stop", "ai-pii-service"], check=True, capture_output=True)

    def start_pii(self):
        subprocess.run(COMPOSE + ["start", "ai-pii-service"], check=True, capture_output=True)


if __name__ == "__main__":
    base.main(DockerSuite, PART / ".env", __doc__)
