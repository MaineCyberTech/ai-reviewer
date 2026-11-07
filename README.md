# AI reviewer

Reusable GPU-backed AI review and human-triggered bot approval for MaineCyberTech repositories.

This repository contains:

- `.github/workflows/ai-review.yml` — reusable advisory AI review workflow.
- `.github/workflows/bot-approval.yml` — reusable approval workflow triggered by the `bot-approve` label.
- `.github/scripts/ai_review.py` — OpenAI-compatible review client.
- `.github/prompts/ai-review.md` — review instructions.
- `proxy/` — authenticated proxy for the GPU-backed Ollama endpoint.
- `docs/` — setup, security and optional GitHub App notes.
- `examples/` — caller workflows for a consuming repository.

## Design

```text
consumer repo PR
  -> reusable ai-review workflow
  -> https://<reviewer endpoint>/v1/chat/completions
  -> authenticated proxy
  -> Ollama on the GPU host
  -> advisory PR comment

maintainer applies bot-approve label
  -> reusable bot-approval workflow
  -> verify AI review comment + required checks
  -> approve with the caller repo GITHUB_TOKEN
```

The AI review is advisory and never approves or merges. The approval workflow
is a human-triggered action: a maintainer applies the label after reviewing.

## Use in another repository

Add these repository secrets:

| Secret | Required | Purpose |
|---|---|---|
| `AI_REVIEW_ENDPOINT` | yes | OpenAI-compatible endpoint, for example `https://ai.example.com/v1/chat/completions` |
| `AI_REVIEW_API_KEY` | yes | Bearer token accepted by the proxy |
| `AI_REVIEW_MODEL` | no | Model name, defaults to `qwen2.5-coder:3b` |

Create `.github/workflows/ai-review.yml`:

```yaml
name: ai-review

on:
  pull_request:
    types: [opened, reopened, ready_for_review]
  workflow_dispatch:
    inputs:
      pr:
        description: Pull request number
        required: true
        type: number

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    uses: MaineCyberTech/ai-reviewer/.github/workflows/ai-review.yml@REPLACE_WITH_AI_REVIEWER_SHA
    secrets:
      AI_REVIEW_ENDPOINT: ${{ secrets.AI_REVIEW_ENDPOINT }}
      AI_REVIEW_API_KEY: ${{ secrets.AI_REVIEW_API_KEY }}
      AI_REVIEW_MODEL: ${{ secrets.AI_REVIEW_MODEL }}
    with:
      pr: ${{ inputs.pr || 0 }}
```

Create `.github/workflows/bot-approval.yml`:

```yaml
name: bot-approval

on:
  pull_request:
    types: [labeled]

permissions:
  contents: read
  pull-requests: write
  checks: read

jobs:
  approve:
    uses: MaineCyberTech/ai-reviewer/.github/workflows/bot-approval.yml@REPLACE_WITH_AI_REVIEWER_SHA
```

Then create the `bot-approve` label in the consuming repository.
Pin the `uses:` reference to a full 40-character commit SHA, not `@main`.
Many repository security gates (including the MaineCyberTech portal) reject
unpinned external actions. Get the current SHA with:

```sh
git ls-remote https://github.com/MaineCyberTech/ai-reviewer.git refs/heads/main
```

The reusable workflow checks out the reviewer at `job.workflow_sha` — the same
commit the caller pinned — and refuses to run if the resolved ref is not a full
40-character SHA. It also verifies the checkout's `HEAD` matches that SHA.
`reviewer_ref` may override this with another full commit SHA, but branch and
tag names are rejected. Pass only the three `AI_REVIEW_*` secrets explicitly;
do not use `secrets: inherit`.

Dependabot-triggered runs and PRs from forks do not receive repository Actions
secrets. The reusable workflow treats an empty `AI_REVIEW_ENDPOINT` or
`AI_REVIEW_API_KEY` as an advisory skip: it emits a notice, exits successfully,
and posts no comment or approval. To review Dependabot PRs, add the
`AI_REVIEW_*` values as Dependabot secrets in the consuming repository.

The calling repository must allow GitHub Actions to approve pull requests
(Settings → Actions → General → Workflow permissions → **Allow GitHub Actions
to create and approve pull requests**). The label is the human approval
decision; the bot only submits the formal approval after checks pass.

Bot approval fails closed. It resolves the PR's current `headRefOid` and only
accepts an advisory AI review comment carrying the matching
`<!-- ai-review-head: <sha> -->` marker (or an advisory PR review whose API
`commit_id` is that head). A comment from an earlier push, or a legacy comment
without the marker, is rejected as stale. If `gh pr checks --required` exits
non-zero (including API/authentication errors), returns empty or malformed
JSON, or reports that no required checks are configured, the workflow refuses
to approve. At least one required context must resolve to a non-failed state.

## Security

- The model endpoint is protected by a bearer token; the proxy returns `401`
  without it.
- The workflow never executes PR code and never gives the model a write token.
- Reviewer code is executed from the same immutable commit SHA as the pinned
  reusable workflow, verified before use; `reviewer_ref` only accepts a full
  commit SHA.
- The only write is the advisory PR comment or the approval review. A skipped
  review (missing Dependabot/fork secrets) writes nothing and approves nothing.
- Bot approval only accepts an AI review for the current head commit; stale or
  marker-less comments are refused.
- Bot approval refuses to approve when the required-check query fails, returns
  empty/malformed data, or finds no required contexts.
- Protected changes (workflows, infra, auth, migrations, secrets) should still
  receive a human review before the `bot-approve` label is applied.
- Do not put the endpoint token in this repository.

## Service identities and secret custody

- `AI_REVIEW_API_KEY` — bearer token accepted by the authenticated model
  proxy. Caller repositories store it as a repository secret; the proxy token
  lives at `/etc/kestrel-ai-proxy/token` on review VM 101 (0600). Rotate both
  sides together.
- `GITHUB_TOKEN` — workflow token with `contents: read` and
  `pull-requests: write`. It posts the advisory comment and submits the formal
  approval. The calling repository must set
  `can_approve_pull_request_reviews=true`.
- `bot-approve` — the human decision label. The reusable `bot-approval.yml`
  verifies the advisory review and required checks before approving. Do not
  apply the label automatically.
- Optional GitHub App — `config/review-bot-manifest.json` is a sanitized
  manifest for a distinct approval identity; it is not created or installed by
  this repository.
- The endpoint token is not a model-provider key and must never be committed.

## Related docs

- [`docs/AI-REVIEW.md`](docs/AI-REVIEW.md) — architecture, limits and operations.
- [`docs/REVIEW-BOT-APP.md`](docs/REVIEW-BOT-APP.md) — optional separate GitHub App identity.
- [`proxy/README.md`](proxy/README.md) — authenticated proxy installation.
