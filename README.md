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
    uses: MaineCyberTech/ai-reviewer/.github/workflows/ai-review.yml@main
    secrets: inherit
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
    uses: MaineCyberTech/ai-reviewer/.github/workflows/bot-approval.yml@main
```

Then create the `bot-approve` label in the consuming repository.

The calling repository must allow GitHub Actions to approve pull requests
(Settings → Actions → General → Workflow permissions → **Allow GitHub Actions
to create and approve pull requests**). The label is the human approval
decision; the bot only submits the formal approval after checks pass.

## Security

- The model endpoint is protected by a bearer token; the proxy returns `401`
  without it.
- The workflow never executes PR code and never gives the model a write token.
- The only write is the advisory PR comment or the approval review.
- Protected changes (workflows, infra, auth, migrations, secrets) should still
  receive a human review before the `bot-approve` label is applied.
- Do not put the endpoint token in this repository.

## Related docs

- [`docs/AI-REVIEW.md`](docs/AI-REVIEW.md) — architecture, limits and operations.
- [`docs/REVIEW-BOT-APP.md`](docs/REVIEW-BOT-APP.md) — optional separate GitHub App identity.
- [`proxy/README.md`](proxy/README.md) — authenticated proxy installation.
