# AGENTS — ai-reviewer

See `README.md` and `docs/` for the reviewer architecture and operations.

## Kestrel GitHub access

Kestrel is the only supported source of GitHub credentials for this repository.
Do not create, store or use a personal access token, a GitHub App private key,
or the shared admin token. Never print, commit, log or paste a broker or minted
token.

Canonical documentation lives in the private `MaineCyberTech/kestrel`
repository: `docs/runbooks/AGENT-GITHUB-ACCESS.md` and `docs/SECRETS.md`.

- Use the repo-scoped Kestrel broker consumer for work in this repository when
  the owner has provisioned one; `gh-kestrel` mints a short-lived, repo-scoped
  GitHub App token.
- Use the shared `repo-cross` consumer (`gh-kestrel-cross`) for pull requests
  against another repository. It covers all active MaineCyberTech repositories
  with `metadata:read`, `contents:write`, `pull_requests:write`,
  `actions:read` and `checks:read`.
- The broker policy is the permission boundary. It does not grant
  administration, organization runners, secrets, environments or workflow
  edits unless explicitly listed.

### Rules

- Work through pull requests; never push `main`, force-push, merge or use admin
  overrides from an agent.
- Do not edit `.github/workflows` unless the owner grants `workflows:write` for
  a reviewed task.
- No secrets in the repository, issues, pull requests, logs, evidence or chat.
- If credential minting fails, stop and ask the owner; do not fall back to a
  personal access token or the admin token.
- Cross-repo work is PR-only: push a branch and open a pull request. Do not
  create tags or publish releases from an agent unless the owner explicitly
  asks.
- The shared cross-repo credential is rotated quarterly by Kestrel. Do not
  copy token files into this repository or into CI variables.
