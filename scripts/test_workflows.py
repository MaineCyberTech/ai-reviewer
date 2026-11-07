#!/usr/bin/env python3
"""Regression tests for the reusable workflow security controls."""

from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"


def load_workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def workflow_step(name: str, step_name: str) -> dict:
    workflow = load_workflow(name)
    job = next(iter(workflow["jobs"].values()))
    for step in job["steps"]:
        if step.get("name") == step_name:
            return step
    raise AssertionError(f"step {step_name!r} not found in {name}")


def run_script(script: str, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


class ReviewerPinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.step = workflow_step("ai-review.yml", "Resolve reviewer commit")
        cls.script = textwrap.dedent(cls.step["run"])
        cls.checkout = workflow_step("ai-review.yml", "Checkout the reviewer")
        cls.verify = workflow_step("ai-review.yml", "Verify reviewer checkout")

    def resolve(self, input_ref: str, workflow_sha: str):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "github_output"
            env = os.environ.copy()
            env.update(
                {
                    "INPUT_REF": input_ref,
                    "WORKFLOW_SHA": workflow_sha,
                    "GITHUB_OUTPUT": str(output),
                }
            )
            result = run_script(self.script, env, Path(tmp))
            value = output.read_text(encoding="utf-8") if output.exists() else ""
            return result, value

    def test_defaults_to_workflow_sha(self) -> None:
        sha = "a" * 40
        result, output = self.resolve("", sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, f"sha={sha}\n")

    def test_accepts_explicit_sha_and_normalizes_case(self) -> None:
        sha = "ABCDEF" + "0" * 34
        result, output = self.resolve(sha, "b" * 40)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, f"sha={sha.lower()}\n")

    def test_rejects_mutable_ref(self) -> None:
        for ref in ("main", "refs/heads/main", "d401040c", "d401040c9777a63195396cbf177eec78192284d2x"):
            with self.subTest(ref=ref):
                result, output = self.resolve(ref, "b" * 40)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("40-character commit SHA", result.stderr)
                self.assertEqual(output, "")

    def test_rejects_missing_workflow_sha(self) -> None:
        result, output = self.resolve("", "")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("40-character commit SHA", result.stderr)
        self.assertEqual(output, "")

    def test_checkout_uses_resolved_sha_and_verifies_head(self) -> None:
        self.assertEqual(
            self.checkout["with"]["ref"], "${{ steps.reviewer-ref.outputs.sha }}"
        )
        self.assertIs(self.checkout["with"]["persist-credentials"], False)
        verify_script = textwrap.dedent(self.verify["run"])
        self.assertIn("git -C .ai-reviewer rev-parse HEAD", verify_script)
        self.assertIn("EXPECTED_SHA", verify_script)
        self.assertIn("exit 1", verify_script)

    def test_uses_called_workflow_sha_not_caller_sha(self) -> None:
        self.assertEqual(self.step["env"]["WORKFLOW_SHA"], "${{ job.workflow_sha }}")
        self.assertNotIn("github.workflow_sha", self.script)
        self.assertNotIn("github.workflow_sha", str(self.step))


FAKE_GH = """#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\\n' "$*" >> "$GH_LOG"
if [ "$1" = "api" ] && [ "$2" != "-X" ]; then
  printf '123\\n'
  exit 0
fi
if [ "$1" = "pr" ] && [ "$2" = "checks" ]; then
  if [ -n "${GH_CHECKS_STDERR:-}" ]; then
    printf '%s\\n' "$GH_CHECKS_STDERR" >&2
  fi
  if [ -n "${GH_CHECKS_STDOUT:-}" ]; then
    printf '%s\\n' "$GH_CHECKS_STDOUT"
  fi
  exit "${GH_CHECKS_EXIT:-0}"
fi
if [ "$1" = "api" ] && [ "$2" = "-X" ]; then
  printf 'APPROVED\\n'
  exit 0
fi
printf 'unexpected gh invocation: %s\\n' "$*" >&2
exit 99
"""

FAKE_SLEEP = """#!/usr/bin/env bash
exit 0
"""


class BotApprovalFailClosedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.step = workflow_step("bot-approval.yml", "Verify checks and AI review, then approve")
        cls.script = textwrap.dedent(cls.step["run"])

    def run_bot(self, *, exit_code: int, stdout: str, stderr: str):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            log = root / "gh.log"
            gh = bin_dir / "gh"
            gh.write_text(FAKE_GH, encoding="utf-8")
            gh.chmod(0o755)
            sleep = bin_dir / "sleep"
            sleep.write_text(FAKE_SLEEP, encoding="utf-8")
            sleep.chmod(0o755)

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "GH_LOG": str(log),
                    "GH_CHECKS_EXIT": str(exit_code),
                    "GH_CHECKS_STDOUT": stdout,
                    "GH_CHECKS_STDERR": stderr,
                    "GH_TOKEN": "test-token",
                    "PR": "1",
                    "REPO": "example/repo",
                }
            )
            result = run_script(self.script, env, root)
            calls = log.read_text(encoding="utf-8") if log.exists() else ""
            return result, calls

    def assert_refused(self, result, calls) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("event=APPROVE", calls)

    def test_query_error_refuses(self) -> None:
        result, calls = self.run_bot(
            exit_code=1, stdout="", stderr="HTTP 502: Bad Gateway"
        )
        self.assert_refused(result, calls)
        self.assertIn("Failed to query required checks", result.stderr)

    def test_empty_success_output_refuses(self) -> None:
        result, calls = self.run_bot(exit_code=0, stdout="", stderr="")
        self.assert_refused(result, calls)
        self.assertIn("no usable JSON", result.stderr)

    def test_empty_array_refuses(self) -> None:
        result, calls = self.run_bot(exit_code=0, stdout="[]", stderr="")
        self.assert_refused(result, calls)
        self.assertIn("no usable JSON", result.stderr)

    def test_malformed_json_refuses(self) -> None:
        result, calls = self.run_bot(exit_code=0, stdout="not-json", stderr="")
        self.assert_refused(result, calls)

    def test_no_required_checks_refuses(self) -> None:
        result, calls = self.run_bot(
            exit_code=1,
            stdout="",
            stderr="no required checks reported on the 'main' branch",
        )
        self.assert_refused(result, calls)
        self.assertIn("No required checks are configured", result.stderr)

    def test_failed_check_with_nonzero_exit_refuses(self) -> None:
        result, calls = self.run_bot(
            exit_code=1,
            stdout='[{"name":"ci","state":"FAILURE"}]',
            stderr="",
        )
        self.assert_refused(result, calls)
        self.assertIn("Required checks are not all green", result.stderr)

    def test_failed_check_with_zero_exit_refuses(self) -> None:
        result, calls = self.run_bot(
            exit_code=0,
            stdout='[{"name":"ci","state":"FAILURE"}]',
            stderr="",
        )
        self.assert_refused(result, calls)
        self.assertIn("Required checks are failing", result.stderr)

    def test_pending_checks_time_out_without_approval(self) -> None:
        result, calls = self.run_bot(
            exit_code=8,
            stdout='[{"name":"ci","state":"PENDING"}]',
            stderr="",
        )
        self.assert_refused(result, calls)
        self.assertIn("did not finish in time", result.stderr)

    def test_successful_required_check_approves(self) -> None:
        result, calls = self.run_bot(
            exit_code=0,
            stdout='[{"name":"ci","state":"SUCCESS"}]',
            stderr="",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-X POST", calls)
        self.assertIn("event=APPROVE", calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
