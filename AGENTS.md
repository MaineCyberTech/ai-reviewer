# AGENTS — ai-reviewer

See `README.md` and `docs/` for the reviewer architecture and operations.

## GitHub access (Kestrel broker)

Use `gh-kestrel` for GitHub API work and the configured `git` credential helper
for pushes. Do not use a personal access token, a GitHub App private key or the
shared admin token.

```sh
export KESTREL_BROKER_URL=http://192.168.222.225:8090
export KESTREL_BROKER_TOKEN_FILE=/etc/kestrel-agents/ai-reviewer/broker-token
export KESTREL_GITHUB_APP=kestrel-automation

gh-kestrel pr list --repo MaineCyberTech/ai-reviewer
```

`gh-kestrel` exchanges the repo-scoped `kbt_...` consumer token for a
short-lived GitHub App token. The broker policy pins this repository and the
minimum permissions; the token cannot read or write another repository. Never
print, commit, log or paste either token. If the token file is missing, stop
and ask the owner; do not fall back to a PAT or the admin token. Provisioning
and rotation are in `MaineCyberTech/kestrel` `docs/runbooks/AGENT-GITHUB-ACCESS.md`.
