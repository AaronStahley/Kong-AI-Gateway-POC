#!/usr/bin/env python3
"""Part 2 gateway tests: the shared checks (shared/gateway_suite.py) against the kind data plane.

Reads part-02/.env, takes engineering's tools from `terraform output engineering_tools`, and
--fail-closed scales the ai-pii-service Deployment to 0 and back. Needs terraform and kubectl.
    python3 part-02/test_gateway.py [--fail-closed]     # or: make -C part-02 test
"""

import json
import subprocess
import sys
from pathlib import Path

PART = Path(__file__).resolve().parent
TERRAFORM = ["terraform", f"-chdir={PART / 'terraform'}"]
NAMESPACE = "kong"   # where `make gateway` installs the poc-ai-gateway chart
PII = ["kubectl", "-n", NAMESPACE]

sys.path.insert(0, str(PART.parent / "shared"))
import gateway_suite as base  # noqa: E402


class KubernetesSuite(base.Suite):
    def approved_tools(self):
        out = subprocess.run(TERRAFORM + ["output", "-json", "engineering_tools"],
                             check=True, capture_output=True, text=True).stdout
        return set(json.loads(out))

    def stop_pii(self):
        subprocess.run(PII + ["scale", "deploy/ai-pii-service", "--replicas=0"],
                       check=True, capture_output=True)
        subprocess.run(PII + ["wait", "--for=delete", "pod", "-l", "app.kubernetes.io/name=ai-pii-service",
                              "--timeout=120s"], check=True, capture_output=True)

    def start_pii(self):
        subprocess.run(PII + ["scale", "deploy/ai-pii-service", "--replicas=1"],
                       check=True, capture_output=True)
        subprocess.run(PII + ["rollout", "status", "deploy/ai-pii-service", "--timeout=300s"],
                       check=True, capture_output=True)


if __name__ == "__main__":
    base.main(KubernetesSuite, PART / ".env", __doc__)
