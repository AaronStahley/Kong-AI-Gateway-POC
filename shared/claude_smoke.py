#!/usr/bin/env python3
"""Scripted Claude Code checks through the gateway: proves the real client is routed through Kong.

Runs `claude -p` with the cheap flags of `make -C shared claude` for three checks: a model reply,
a GitHub MCP read (skipped without GITHUB_PAT) and PII redaction. Prints tokens per check.
Run with `make -C shared claude-smoke PART=1|2`. Deterministic checks stay in gateway_suite.py.
Exit code 0 when nothing failed, 1 otherwise. Standard library only.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gateway_suite as base  # noqa: E402

MCP_CONFIG = "shared/claude/mcp.json"
MCP_READ_TOOL = "mcp__github-via-kong__get_file_contents"
TIMEOUT = 180


def claude(prompt, allowed_tools=()):
    """Run one non-interactive Claude Code prompt; return (parsed JSON or None, error text)."""
    cmd = ["claude", "-p", prompt, "--bare", "--model", "claude-main", "--effort", "low",
           "--output-format", "json", "--mcp-config", MCP_CONFIG, "--strict-mcp-config",
           "--tools", ""]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, f"no result after {TIMEOUT}s"
    try:
        return json.loads(proc.stdout), ""
    except json.JSONDecodeError:
        return None, (proc.stderr or proc.stdout).strip()[:200]


class ClaudeSmoke(base.Suite):
    def __init__(self, env):
        super().__init__(env)
        self.tokens = {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0}

    def run(self, name, prompt, check, allowed_tools=()):
        """Run a prompt and record PASS/FAIL from check(result_text) -> (ok, detail)."""
        out, err = claude(prompt, allowed_tools)
        if out is None:
            self.record("claude", name, "FAIL", err)
            return
        usage = out.get("usage") or {}
        used = {"input": usage.get("input_tokens", 0),
                "cache_read": usage.get("cache_read_input_tokens", 0),
                "cache_write": usage.get("cache_creation_input_tokens", 0),
                "output": usage.get("output_tokens", 0)}
        for k, v in used.items():
            self.tokens[k] += v
        tokens = f"{sum(used.values()) - used['output']:,} in / {used['output']:,} out"
        text = out.get("result") or ""
        if out.get("is_error"):
            self.record("claude", name, "FAIL", f"{tokens}; {text[:160]}")
            return
        ok, detail = check(text)
        self.record("claude", name, "PASS" if ok else "FAIL", f"{tokens}; {detail}")

    def checks(self):
        print("\nClaude Code through the gateway")
        self.run("model reply via Claude Code",
                 "What is two plus two? Reply with only the numeral.",
                 lambda t: ("4" in t, repr(t.strip()[:40])))

        if self.env.get("GITHUB_PAT"):
            # Most expensive check (~3k tokens of README). Its first paragraph calls Kong a "Gateway".
            self.run("GitHub MCP read via Claude Code",
                     "Using the github tool, read the public Kong/kong repo's README. Summarize the "
                     "first paragraph in a single sentence.",
                     lambda t: ("gateway" in t.lower(), repr(t.strip()[:80])),
                     allowed_tools=[MCP_READ_TOOL])
        else:
            self.record("claude", "GitHub MCP read via Claude Code", "SKIP", "GITHUB_PAT is empty")

        def redacted(t):
            leaked = [v for v in (base.FAKE_EMAIL, base.FAKE_PHONE) if v in t]
            if leaked:
                return False, f"leaked {', '.join(leaked)}: {t.strip()[:80]!r}"
            return "PLACEHOLDER" in t, repr(t.strip()[:80])
        self.run("PII redacted before Anthropic",
                 f"Repeat exactly, with no other text: Contact {base.FAKE_EMAIL} or {base.FAKE_PHONE}.",
                 redacted)

    def summary(self):
        t = self.tokens
        print(f"\nTokens: {t['input']:,} input, {t['cache_read']:,} cache read, "
              f"{t['cache_write']:,} cache write, {t['output']:,} output")
        return super().summary()


def main():
    if not Path(MCP_CONFIG).exists():
        sys.exit(f"{MCP_CONFIG} not found: run from the repository root (make -C shared claude-smoke)")
    smoke = ClaudeSmoke(dict(os.environ))
    print(f"Gateway: {os.environ.get('ANTHROPIC_BASE_URL', '(ANTHROPIC_BASE_URL not set)')}")
    smoke.checks()
    sys.exit(0 if smoke.summary() else 1)


if __name__ == "__main__":
    main()
