#!/usr/bin/env python3
"""Regression tests for the reusable workflow security controls."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
CURRENT_SHA = "c" * 40
STALE_SHA = "d" * 40


def load_workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def workflow_call(name: str) -> dict:
    workflow = load_workflow(name)
    # PyYAML implements YAML 1.1, which parses the bare `on` key as True.
    trigger = workflow["on"] if "on" in workflow else workflow[True]
    return trigger["workflow_call"]


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


def ai_review_body(sha: str | None) -> str:
    marker = f"<!-- ai-review-head: {sha} -->\n" if sha else ""
    head_line = f"Reviewed head commit: `{sha}`\n\n" if sha else ""
    return (
        "## AI review (advisory)\n\n"
        f"{marker}{head_line}"
        "_Independent AI review of this diff. This is not a GitHub approval; "
        "a human must review and approve._\n\nLooks good.\n"
    )


def comments_json(*bodies: str) -> str:
    return json.dumps(
        [
            {
                "id": index + 1,
                "user": {"login": "github-actions[bot]"},
                "body": body,
            }
            for index, body in enumerate(bodies)
        ]
    )


FAKE_GH = """#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\\n' "$*" >> "$GH_LOG"
if [ "$1" = "pr" ] && [ "$2" = "view" ]; then
  if [[ "$*" == *headRefOid* ]]; then
    printf '%s\\n' "${GH_HEAD_SHA:-}"
  else
    printf '%s\\n' '{"title":"test","body":"","files":[]}'
  fi
  exit 0
fi
if [ "$1" = "pr" ] && [ "$2" = "diff" ]; then
  printf 'diff --git a/file b/file\\n'
  exit 0
fi
if [ "$1" = "pr" ] && [ "$2" = "comment" ]; then
  printf 'commented\\n'
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
if [ "$1" = "api" ]; then
  case "$*" in
    *"/issues/"*"/comments"*) printf '%s\\n' "${GH_COMMENTS_STDOUT:-[]}" ;;
    *"/pulls/"*"/reviews"*) printf '%s\\n' "${GH_REVIEWS_STDOUT:-[]}" ;;
    *) printf '123\\n' ;;
  esac
  exit 0
fi
printf 'unexpected gh invocation: %s\\n' "$*" >&2
exit 99
"""

FAKE_PYTHON = """#!/usr/bin/env bash
printf 'review body\\n'
"""

FAKE_SLEEP = """#!/usr/bin/env bash
exit 0
"""


def install_fakes(root: Path) -> Path:
    bin_dir = root / "bin"
    bin_dir.mkdir()
    for name, content in (
        ("gh", FAKE_GH),
        ("python3", FAKE_PYTHON),
        ("sleep", FAKE_SLEEP),
    ):
        path = bin_dir / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)
    return bin_dir


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


class AiReviewCredentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.step = workflow_step("ai-review.yml", "Review the PR diff")
        cls.script = textwrap.dedent(cls.step["run"])

    def run_review(self, *, endpoint: str, api_key: str, head_sha: str = CURRENT_SHA):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = install_fakes(root)
            log = root / "gh.log"

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "GH_LOG": str(log),
                    "GH_HEAD_SHA": head_sha,
                    "GH_TOKEN": "test-token",
                    "PR_NUMBER": "1",
                    "AI_REVIEW_ENDPOINT": endpoint,
                    "AI_REVIEW_API_KEY": api_key,
                    "AI_REVIEW_MODEL": "test-model",
                }
            )
            result = run_script(self.script, env, root)
            calls = log.read_text(encoding="utf-8") if log.exists() else ""
            comment = root / ".ai-review" / "comment.md"
            body = comment.read_text(encoding="utf-8") if comment.exists() else None
            return result, calls, body

    def test_secrets_are_optional_so_callers_can_pass_empty_values(self) -> None:
        secrets = workflow_call("ai-review.yml")["secrets"]
        self.assertIs(secrets["AI_REVIEW_ENDPOINT"]["required"], False)
        self.assertIs(secrets["AI_REVIEW_API_KEY"]["required"], False)

    def test_missing_endpoint_skips_successfully(self) -> None:
        result, calls, body = self.run_review(endpoint="", api_key="test-key")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("::notice", result.stdout)
        self.assertIn("AI review skipped", result.stdout)
        self.assertEqual(calls, "")
        self.assertIsNone(body)

    def test_missing_api_key_skips_successfully(self) -> None:
        result, calls, body = self.run_review(
            endpoint="https://review.example/v1/chat/completions", api_key=""
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("::notice", result.stdout)
        self.assertIn("AI review skipped", result.stdout)
        self.assertEqual(calls, "")
        self.assertIsNone(body)

    def test_review_comment_records_current_head(self) -> None:
        result, calls, body = self.run_review(
            endpoint="https://review.example/v1/chat/completions", api_key="test-key"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNotNone(body)
        self.assertIn(f"<!-- ai-review-head: {CURRENT_SHA} -->", body)
        self.assertIn(f"Reviewed head commit: `{CURRENT_SHA}`", body)
        self.assertIn("pr comment", calls)
        self.assertNotIn("event=APPROVE", calls)

    def test_unresolvable_head_sha_fails_without_commenting(self) -> None:
        result, calls, body = self.run_review(
            endpoint="https://review.example/v1/chat/completions",
            api_key="test-key",
            head_sha="",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Could not resolve the PR head commit", result.stderr)
        self.assertNotIn("pr comment", calls)
        self.assertIsNone(body)


class BotApprovalFailClosedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.step = workflow_step("bot-approval.yml", "Verify checks and AI review, then approve")
        cls.script = textwrap.dedent(cls.step["run"])

    def run_bot(
        self,
        *,
        exit_code: int = 0,
        stdout: str = '[{"name":"ci","state":"SUCCESS"}]',
        stderr: str = "",
        head_sha: str = CURRENT_SHA,
        comments: str | None = None,
        reviews: str = "[]",
    ):
        if comments is None:
            comments = comments_json(ai_review_body(CURRENT_SHA))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = install_fakes(root)
            log = root / "gh.log"

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "GH_LOG": str(log),
                    "GH_CHECKS_EXIT": str(exit_code),
                    "GH_CHECKS_STDOUT": stdout,
                    "GH_CHECKS_STDERR": stderr,
                    "GH_HEAD_SHA": head_sha,
                    "GH_COMMENTS_STDOUT": comments,
                    "GH_REVIEWS_STDOUT": reviews,
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

    def test_current_head_review_comment_approves(self) -> None:
        result, calls = self.run_bot(
            comments=comments_json(ai_review_body(CURRENT_SHA))
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("event=APPROVE", calls)

    def test_stale_review_comment_refuses(self) -> None:
        result, calls = self.run_bot(
            comments=comments_json(ai_review_body(STALE_SHA))
        )
        self.assert_refused(result, calls)
        self.assertIn("Stale advisory AI review", result.stderr)
        self.assertIn(CURRENT_SHA, result.stderr)

    def test_review_without_head_marker_is_stale(self) -> None:
        result, calls = self.run_bot(comments=comments_json(ai_review_body(None)))
        self.assert_refused(result, calls)
        self.assertIn("Stale advisory AI review", result.stderr)

    def test_no_review_comment_refuses(self) -> None:
        result, calls = self.run_bot(comments="[]")
        self.assert_refused(result, calls)
        self.assertIn("No advisory AI review comment found", result.stderr)

    def test_current_review_object_approves(self) -> None:
        reviews = json.dumps(
            [
                {
                    "id": 7,
                    "user": {"login": "github-actions[bot]"},
                    "commit_id": CURRENT_SHA,
                    "state": "APPROVED",
                    "body": "AI review (advisory)\n\nLooks good.",
                }
            ]
        )
        result, calls = self.run_bot(comments="[]", reviews=reviews)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("event=APPROVE", calls)

    def test_stale_review_object_refuses(self) -> None:
        reviews = json.dumps(
            [
                {
                    "id": 7,
                    "user": {"login": "github-actions[bot]"},
                    "commit_id": STALE_SHA,
                    "state": "APPROVED",
                    "body": "AI review (advisory)\n\nLooks good.",
                }
            ]
        )
        result, calls = self.run_bot(comments="[]", reviews=reviews)
        self.assert_refused(result, calls)
        self.assertIn("No advisory AI review comment found", result.stderr)

    def test_missing_head_sha_refuses(self) -> None:
        result, calls = self.run_bot(head_sha="")
        self.assert_refused(result, calls)
        self.assertIn("Could not resolve the current head commit", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
