# AI review

The reusable review workflow is advisory. It posts one comment with findings by
severity and a merge recommendation.

## What it does

1. Reads the consumer PR title, body, file list and diff.
2. Caps the diff at 30 KB and treats it as untrusted data.
3. Sends the diff to the configured OpenAI-compatible endpoint.
4. Posts a Markdown comment.

## What it does not do

- It does not approve, request changes or merge.
- It does not satisfy branch protection by itself.
- It does not execute PR code.
- It does not expose repository secrets to the model.

## Approval

A maintainer reviews the PR, then applies the `bot-approve` label. The separate
`bot-approval.yml` workflow verifies the advisory AI review and required checks
and submits the formal approval with the caller's `GITHUB_TOKEN`.

The approval step fails closed. A non-zero `gh pr checks --required` exit
(other than the documented pending exit 8), empty output, malformed JSON, no
required contexts, or any failed/pending required check stops the workflow
without approving. It never treats a failed query as "zero pending checks".

The caller must pin the reusable workflow to a full 40-character commit SHA.
The review workflow checks out the reviewer source at `job.workflow_sha`, the
same commit that defines the called workflow, verifies the checkout's `HEAD`
matches, and refuses branch/tag refs. An optional `reviewer_ref` input can
select another full commit SHA but is validated the same way. Pass only the
three `AI_REVIEW_*` secrets explicitly instead of `secrets: inherit`.

The consuming repository must allow GitHub Actions to approve pull requests:
Settings → Actions → General → Workflow permissions → **Allow GitHub Actions to
create and approve pull requests**.

## Prompt injection

The diff is untrusted input. The prompt tells the model to ignore instructions
inside it. The workflow never executes PR code and never grants the model a
write token; the only write is the final PR comment or approval.

## Reliability

Reviews are serialized per consuming repository with a workflow `concurrency`
group. The client retries HTTP 429, 5xx and Cloudflare 524 up to three times
with backoff. A shared GPU may still be busy across repositories; the retry is
best-effort and the review remains advisory.

## Limitations

A small local model is a first pass, not an authority. Use a larger hosted model
by changing `AI_REVIEW_MODEL` or pointing `AI_REVIEW_ENDPOINT` at a different
OpenAI-compatible service.
