"""Gateway checks shared by both parts: models, keys, GitHub MCP, token limits and the PII sanitizer.

Not run directly: each part's test_gateway.py subclasses Suite (approved_tools, stop_pii, start_pii)
and calls main() with its own .env. Calls the data plane with tiny max_tokens, so a run costs a few
hundred tokens. Model, MCP and PII checks always use ENG_DEV_1_KEY; the token-limit check uses up
finance's hourly allowance, so finance stays blocked until the window resets.

Known 2.2.0 limitations report XFAIL and don't fail the run; XPASS means one now works.
Exit code 0 when nothing failed, 1 otherwise. Standard library only.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

# Kong caches DNS "not found" per worker for this long (dns_not_found_ttl). Docker forgets a stopped
# container's name, so some workers keep failing this long after the PII service is back.
DNS_NOT_FOUND_TTL = 30

# Values a model will echo back (it refuses to repeat an SSN, which would hide a leak).
FAKE_EMAIL = "jane.doe@example.com"
FAKE_PHONE = "212-555-0147"

# 1x1 PNG for the image checks
TINY_PNG = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data":
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="}}


# --- .env -------------------------------------------------------------------------------------

def load_env(path):
    """Parse KEY=value lines, expanding ${VAR} and ${VAR:-default} like bash does."""
    env = dict(os.environ)
    if not path.exists():
        sys.exit(f"{path} not found; copy {path.name}.example next to it and fill it in")

    def expand(value):
        def repl(m):
            name, default = m.group(1), m.group(3)
            return env.get(name) or (default or "")
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-([^}]*))?\}", repl, value)

    for line in path.read_text().splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if not m:
            continue
        value = m.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        env[m.group(1)] = expand(value)
    return env


# --- HTTP -------------------------------------------------------------------------------------

def post_full(url, body, headers, timeout=60):
    """POST JSON; return (status, text, response headers). Never raises for HTTP error statuses."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode(errors="replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace"), dict(e.headers)
    except urllib.error.URLError as e:
        return 0, f"connection failed: {e.reason}", {}


def post(url, body, headers, timeout=60):
    """POST JSON; return (status, text)."""
    status, text, _ = post_full(url, body, headers, timeout)
    return status, text


def ratelimit_headers(headers):
    return {k: v for k, v in headers.items() if k.lower().startswith("x-ai-ratelimit")}


def error_text(text):
    try:
        j = json.loads(text)
        return (j.get("error") or {}).get("message") or j.get("message") or text
    except (ValueError, AttributeError):
        return text


def reply_text(text):
    try:
        return "".join(p.get("text", "") for p in json.loads(text).get("content", []))
    except (ValueError, AttributeError):
        return ""


def mcp_messages(text):
    """MCP over HTTP answers with JSON or server-sent events; return the JSON-RPC messages."""
    text = text.strip()
    if text.startswith("{"):
        return [json.loads(text)]
    msgs = []
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                msgs.append(json.loads(line[5:].strip()))
            except ValueError:
                pass
    return msgs


# --- Checks -----------------------------------------------------------------------------------

class Suite:
    def __init__(self, env):
        self.env = env
        self.base = (env.get("KONG_PROXY_URL") or "http://localhost:8000").rstrip("/")
        self.results = []

    def record(self, step, name, outcome, detail=""):
        self.results.append((step, name, outcome, detail))
        mark = {"PASS": "\033[32mPASS\033[0m", "FAIL": "\033[31mFAIL\033[0m",
                "SKIP": "\033[33mSKIP\033[0m", "XFAIL": "\033[36mXFAIL\033[0m",
                "XPASS": "\033[35mXPASS\033[0m"}[outcome]
        print(f"  {mark}  {name}" + (f"  ({detail})" if detail else ""))

    def expect_status(self, step, name, status, text, expected):
        ok = status == expected
        detail = f"HTTP {status}" + ("" if ok else f", expected {expected}: {error_text(text)[:120]}")
        self.record(step, name, "PASS" if ok else "FAIL", detail)

    def known_issue(self, step, name, status, text, expected_status, marker):
        """Record a documented 2.2.0 limitation: XFAIL if it still fails as documented, XPASS on 200."""
        if status == expected_status and marker in text:
            self.record(step, name, "XFAIL", f"HTTP {status}, as documented")
        elif status == 200:
            self.record(step, name, "XPASS", "HTTP 200: looks fixed (or the PII policy is detached)")
        else:
            self.record(step, name, "FAIL", f"HTTP {status}: {error_text(text)[:120]}")

    # Models -----------------------------------------------------------------------------------

    def messages_full(self, body, key=None):
        headers = {"anthropic-version": "2023-06-01"}
        key = self.env.get("ENG_DEV_1_KEY") if key is None else key
        if key:
            headers["x-api-key"] = key
        return post_full(f"{self.base}/v1/messages", body, headers)

    def messages(self, body, key=None):
        status, text, _ = self.messages_full(body, key)
        return status, text

    def models(self):
        print("\nStep 3-4: models and developer keys")
        if not self.env.get("ENG_DEV_1_KEY"):
            self.record(3, "model checks", "SKIP", "ENG_DEV_1_KEY is empty")
            return
        hi = [{"role": "user", "content": "Say ok"}]

        s, t = self.messages({"model": "claude-main", "max_tokens": 10, "messages": hi})
        self.expect_status(3, "claude-main answers", s, t, 200)

        s, t = self.messages({"model": "claude-fast", "max_tokens": 10, "messages": hi})
        self.expect_status(3, "claude-fast answers", s, t, 200)

        s, t = self.messages({"model": "claude-opus-5-5", "max_tokens": 10, "messages": hi})
        self.expect_status(3, "unlisted model is rejected", s, t, 503)

        # What Claude Code sends after any tool use (file reads, MCP calls, ...)
        s, t = self.messages({
            "model": "claude-fast", "max_tokens": 30,
            "tools": [{"name": "get_time", "description": "Get the time",
                       "input_schema": {"type": "object", "properties": {}}}],
            "messages": [
                {"role": "user", "content": "What time is it?"},
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "toolu_01", "name": "get_time", "input": {}}]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_01", "content": "10:30"}]},
            ]})
        self.expect_status(3, "conversation with tool call and tool result", s, t, 200)

        s, t = self.messages({"model": "claude-fast", "max_tokens": 10, "messages": hi}, key="")
        self.expect_status(4, "no gateway key is rejected", s, t, 401)

    # GitHub MCP -------------------------------------------------------------------------------

    def approved_tools(self):
        """Tools engineering may use, from the part's own config (YAML in Part 1, Terraform in Part 2)."""
        raise NotImplementedError

    def mcp(self, body, key):
        headers = {"accept": "application/json, text/event-stream"}
        if key:
            headers["x-api-key"] = key
        if self.env.get("GITHUB_PAT"):
            headers["authorization"] = f"Bearer {self.env['GITHUB_PAT']}"
        return post(f"{self.base}/mcp/github", body, headers)

    def tool_names(self, key):
        s, t = self.mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, key)
        names = set()
        for m in mcp_messages(t) if s == 200 else []:
            names |= {tool["name"] for tool in (m.get("result") or {}).get("tools", [])}
        return s, t, names

    def call_tool(self, key, tool, arguments):
        """tools/call; return (HTTP status, JSON-RPC messages, detail text)."""
        s, t = self.mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                         "params": {"name": tool, "arguments": arguments}}, key)
        msgs = mcp_messages(t) if s == 200 else []
        errors = [m["error"] for m in msgs if isinstance(m.get("error"), dict)]
        detail = f"HTTP {s}" + (f", JSON-RPC error {errors[0].get('code')}: "
                                f"{str(errors[0].get('message'))[:100]}" if errors else "")
        return s, msgs, detail

    def expect_denied(self, name, key, tool, arguments):
        """Only the gateway's own refusal counts: HTTP 403, or JSON-RPC -32602 on older Kong versions.
        Any other error may have come from GitHub after the call was forwarded."""
        s, msgs, detail = self.call_tool(key, tool, arguments)
        denied = s == 403 or any((m.get("error") or {}).get("code") == -32602 for m in msgs)
        self.record(5, name, "PASS" if denied else "FAIL", detail)

    def github_mcp(self):
        print("\nStep 5: GitHub MCP")
        missing = [v for v in ("GITHUB_PAT", "ENG_DEV_1_KEY", "FIN_DEV_1_KEY") if not self.env.get(v)]
        if missing:
            self.record(5, "MCP checks", "SKIP", f"empty in .env: {', '.join(missing)}")
            return

        s, t = self.mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, key="")
        self.expect_status(5, "MCP without gateway key is rejected", s, t, 401)

        expected = self.approved_tools()
        s, t, names = self.tool_names(self.env["ENG_DEV_1_KEY"])
        if s != 200:
            self.record(5, "engineering tool list", "FAIL", f"HTTP {s}: {error_text(t)[:120]}")
        elif names == expected:
            self.record(5, "engineering sees exactly the approved tools", "PASS", f"{len(names)} tools")
        else:
            extra, gone = sorted(names - expected), sorted(expected - names)
            self.record(5, "engineering sees exactly the approved tools", "FAIL",
                        f"unexpected: {extra or '-'}; missing: {gone or '-'}")

        s, t, names = self.tool_names(self.env["FIN_DEV_1_KEY"])
        ok = (s == 200 and not names) or s == 403
        self.record(5, "finance sees no GitHub tools", "PASS" if ok else "FAIL",
                    f"HTTP {s}, {len(names)} tools")

        # An approved tool goes through to GitHub. get_me is read-only and takes no arguments.
        s, msgs, detail = self.call_tool(self.env["ENG_DEV_1_KEY"], "get_me", {})
        ok = any("result" in m and not (m["result"] or {}).get("isError") for m in msgs)
        self.record(5, "engineering calling get_me reaches GitHub", "PASS" if ok else "FAIL", detail)

        # Hidden tools must also be refused when called by name. The merge targets a public repo
        # the token can't write to, as a safety net.
        self.expect_denied("engineering calling merge_pull_request is denied by the gateway",
                           self.env["ENG_DEV_1_KEY"], "merge_pull_request",
                           {"owner": "octocat", "repo": "Hello-World", "pullNumber": 1})
        self.expect_denied("finance calling get_me is denied by the gateway",
                           self.env["FIN_DEV_1_KEY"], "get_me", {})

    # Token limits -----------------------------------------------------------------------------

    def day_remaining(self, key):
        """Send a tiny request; return (status, {policy number: remaining day tokens}, tokens used)."""
        s, t, h = self.messages_full({"model": "claude-fast", "max_tokens": 10,
                                      "messages": [{"role": "user", "content": "Say ok"}]}, key=key)
        left = {}
        for k, v in h.items():
            m = re.fullmatch(r"x-ai-ratelimit-remaining-day-policy-(\d+)", k.lower())
            if m and v.isdigit():
                left[int(m.group(1))] = int(v)
        try:
            usage = json.loads(t).get("usage") or {}
        except (ValueError, AttributeError):
            usage = {}
        return s, left, usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

    def engineering_budgets(self):
        """Team allowance (policy-1) is shared by engineers; per-engineer allowance (policy-4) isn't.
        eng-dev-1's tokens must lower eng-dev-2's team counter but not eng-dev-2's own."""
        eng1, eng2 = self.env.get("ENG_DEV_1_KEY"), self.env.get("ENG_DEV_2_KEY")
        if not eng2:
            self.record(7, "engineering team and per-engineer budgets", "SKIP", "ENG_DEV_2_KEY is empty")
            return
        s1, before, _ = self.day_remaining(eng2)
        s2, _, used = self.day_remaining(eng1)
        s3, after, _ = self.day_remaining(eng2)
        if (s1, s2, s3) != (200, 200, 200) or not {1, 4} <= before.keys() or not {1, 4} <= after.keys():
            self.record(7, "engineering team and per-engineer budgets", "FAIL",
                        f"HTTP {s1}/{s2}/{s3}, day counters {before or 'missing'} -> {after or 'missing'}")
            return
        team_drop, own_drop = before[1] - after[1], before[4] - after[4]
        # Both drops include eng-dev-2's own first request; only the team's includes eng-dev-1's.
        self.record(7, "engineering team budget is shared by engineers",
                    "PASS" if team_drop - own_drop >= used > 0 else "FAIL",
                    f"eng-dev-1 used {used}; eng-dev-2's team counter dropped {team_drop}, own {own_drop}")
        self.record(7, "each engineer has their own budget inside the team's",
                    "PASS" if own_drop < team_drop else "FAIL",
                    f"eng-dev-2's own counter dropped {own_drop}"
                    + ("" if own_drop < team_drop else ": eng-dev-1's tokens count against it"))

    def token_limits(self):
        print("\nStep 7: team token limits")
        eng, fin = self.env.get("ENG_DEV_1_KEY"), self.env.get("FIN_DEV_1_KEY")
        if not (eng and fin):
            self.record(7, "token limit checks", "SKIP", "ENG_DEV_1_KEY or FIN_DEV_1_KEY is empty")
            return
        hi = [{"role": "user", "content": "Say ok"}]

        s, t, h = self.messages_full({"model": "claude-fast", "max_tokens": 10, "messages": hi}, key=eng)
        rl = ratelimit_headers(h)
        remaining = {k: v for k, v in rl.items() if "remaining" in k.lower()}
        self.record(7, "engineering is under its allowance, with limit headers",
                    "PASS" if s == 200 and remaining else "FAIL",
                    f"HTTP {s}, " + (", ".join(f"{k}={v}" for k, v in remaining.items()) or "no X-AI-RateLimit headers"))

        self.engineering_budgets()

        # Finance gets 1,000 tokens/hour (policy-2), counted after each response. ~300-token replies
        # trip it in about 4 requests; later runs get the 429 straight away until the window resets.
        name = "finance is refused with 429 once over its allowance"
        prompt = [{"role": "user", "content": "Write a 200-word paragraph about car insurance."}]
        statuses, remaining, last_headers, t = [], None, {}, ""
        for _ in range(10):
            s, t, last_headers = self.messages_full(
                {"model": "claude-fast", "max_tokens": 400, "thinking": {"type": "disabled"},
                 "messages": prompt}, key=fin)
            statuses.append(s)
            left = {k.lower(): v for k, v in ratelimit_headers(last_headers).items()}
            remaining = left.get("x-ai-ratelimit-remaining-hour-policy-2", remaining)
            # No finance counter at all means the limit isn't applied: no point spending more.
            if s != 200 or remaining is None:
                break
        blocked = statuses[-1] == 429
        retry = {k: v for k, v in ratelimit_headers(last_headers).items()
                 if "retry" in k.lower() or "reset" in k.lower()}
        if statuses[-1] == 200 and remaining is None:
            detail = (f"statuses {statuses}: no X-AI-RateLimit-Remaining-hour-policy-2 header on "
                      "finance's response, so finance's limit isn't applied")
        elif blocked:
            detail = f"statuses {statuses}" + (f", {retry}" if retry else "")
        elif statuses[-1] == 200:
            detail = f"statuses {statuses}: allowance not used up, {remaining} of 1,000 left"
        else:
            detail = f"statuses {statuses}: {error_text(t)[:100]}"
        self.record(7, name, "PASS" if blocked else "FAIL", detail)

        # The ceiling (policy-3) has the same limit as engineering's team allowance (policy-1), so it
        # can only have less left if other consumers' tokens (finance's, just above) count against it.
        s, left, _ = self.day_remaining(eng)
        if s != 200 or 1 not in left or 3 not in left:
            self.record(7, "ceiling is counted per consumer, not shared", "FAIL",
                        f"HTTP {s}, day counters {left or 'missing'}")
        else:
            shared = left[3] < left[1]
            self.record(7, "ceiling is counted per consumer, not shared",
                        "FAIL" if shared else "PASS",
                        f"engineering policy-1 {left[1]}, ceiling policy-3 {left[3]}"
                        + (": other consumers' tokens count against it" if shared else ""))

    # PII sanitizer ----------------------------------------------------------------------------

    def pii_request(self):
        # Thinking off so the small max_tokens goes to the echoed text, not to reasoning.
        return self.messages({"model": "claude-fast", "max_tokens": 60,
                              "thinking": {"type": "disabled"}, "messages": [{
            "role": "user",
            "content": f"Echo this text back verbatim, nothing else: "
                       f"Contact {FAKE_EMAIL} or {FAKE_PHONE}."}]})

    def pii(self, fail_closed):
        print("\nStep 6: PII sanitizer")
        if not self.env.get("ENG_DEV_1_KEY"):
            self.record(6, "PII checks", "SKIP", "ENG_DEV_1_KEY is empty")
            return
        s, t = self.pii_request()
        if s != 200:
            self.record(6, "PII is redacted before Anthropic", "FAIL", f"HTTP {s}: {error_text(t)[:120]}")
        else:
            reply = reply_text(t)
            leaked = [v for v in (FAKE_EMAIL, FAKE_PHONE) if v in reply]
            if not reply.strip():
                self.record(6, "PII is redacted before Anthropic", "FAIL", "empty reply, can't tell")
            else:
                self.record(6, "PII is redacted before Anthropic", "FAIL" if leaked else "PASS",
                            f"reply contains {leaked} (policy not attached?)" if leaked
                            else f"reply: {reply[:80]!r}")

        self.sanitizer_known_issues()

        if not fail_closed:
            self.record(6, "fails closed when the PII service is down", "SKIP", "run with --fail-closed")
            return
        self.stop_pii()
        try:
            s, t = self.pii_request()
            # Only the sanitizer's own block counts; a 401/429/503 would mean it never ran.
            closed = s >= 500 and "failed to sanitize" in t
            self.record(6, "fails closed when the PII service is down",
                        "PASS" if closed else "FAIL",
                        "request was forwarded" if s == 200 else f"HTTP {s}: {error_text(t)[:100]}")
        finally:
            self.start_pii()
            self.wait_for_pii()

    def sanitizer_known_issues(self):
        """Requests Claude Code sends that the 2.2.0 sanitizer can't round-trip. All pass with the
        policy detached. The image cases fail before Anthropic, so they cost no tokens."""
        hi = [{"role": "user", "content": "Say ok"}]
        s, t = self.messages({"model": "claude-fast", "max_tokens": 30,
                              "thinking": {"type": "adaptive"}, "messages": hi})
        self.known_issue(6, "adaptive thinking on claude-fast (known 2.2.0 issue)",
                         s, t, 400, "thinking.type.enabled")

        # Claude Code reading an image file
        s, t = self.messages({
            "model": "claude-main", "max_tokens": 10,
            "tools": [{"name": "read_file", "description": "Read a file",
                       "input_schema": {"type": "object", "properties": {}}}],
            "messages": [
                {"role": "user", "content": "What is in the image?"},
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "toolu_01", "name": "read_file", "input": {}}]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_01", "content": [TINY_PNG]}]},
            ]})
        self.known_issue(6, "image in a tool result (known 2.2.0 issue)",
                         s, t, 500, "failed to convert guardrail-modified body")

        # A pasted screenshot with no text
        s, t = self.messages({"model": "claude-main", "max_tokens": 10,
                              "messages": [{"role": "user", "content": [TINY_PNG]}]})
        self.known_issue(6, "message with only an image (known 2.2.0 issue)",
                         s, t, 500, "unknown request format")

    def stop_pii(self):
        """Stop the PII service and return once it's gone (container, Deployment, ...)."""
        raise NotImplementedError

    def start_pii(self):
        """Start the PII service again and return once it's running."""
        raise NotImplementedError

    def wait_for_pii(self, timeout=180):
        """Poll until a sanitized request succeeds, then wait out Kong's negative DNS cache so every
        worker is healthy again. Failed attempts never reach Anthropic, so they cost no tokens."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            s, _ = self.pii_request()
            if s == 200:
                print(f"  (waiting {DNS_NOT_FOUND_TTL}s for the gateway's cached DNS failures to expire)")
                time.sleep(DNS_NOT_FOUND_TTL)
                return
            time.sleep(3)
        self.record(6, "PII service is back after the fail-closed test", "FAIL",
                    f"not ready after {timeout}s")

    # ------------------------------------------------------------------------------------------

    def summary(self):
        counts = {k: sum(1 for r in self.results if r[2] == k)
                  for k in ("PASS", "FAIL", "SKIP", "XFAIL", "XPASS")}
        print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped, "
              f"{counts['XFAIL']} expected failures, {counts['XPASS']} unexpectedly passed")
        return counts["FAIL"] == 0


def main(suite_class, env_file, description):
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fail-closed", action="store_true",
                        help="stop the PII service briefly and expect model requests to be blocked")
    args = parser.parse_args()

    suite = suite_class(load_env(env_file))
    print(f"Gateway: {suite.base}")
    suite.models()
    suite.github_mcp()
    suite.token_limits()
    suite.pii(args.fail_closed)  # last: --fail-closed restarts the PII service
    sys.exit(0 if suite.summary() else 1)
