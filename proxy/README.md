# Authenticated model proxy

Small bearer-token proxy in front of an OpenAI-compatible Ollama server.

- listens on `0.0.0.0:8081`
- accepts only `POST /v1/chat/completions`
- requires `Authorization: Bearer <token>` from `/etc/kestrel-ai-proxy/token`
- rate-limits each source IP to 12 requests/minute
- caps request bodies at 2 MB
- forwards to `http://127.0.0.1:11434`

The proxy is intended to sit behind a Cloudflare Tunnel or another authenticated
ingress. Do not expose port 8081 directly to the internet.

## Install on the GPU host

```bash
install -d -m 0750 /etc/kestrel-ai-proxy /opt/kestrel-ai-proxy
openssl rand -hex 32 > /etc/kestrel-ai-proxy/token
chmod 0600 /etc/kestrel-ai-proxy/token
install -m 0755 proxy.py /opt/kestrel-ai-proxy/proxy.py
install -m 0644 ai-reviewer-proxy.service /etc/systemd/system/kestrel-ai-proxy.service
systemctl daemon-reload
systemctl enable --now kestrel-ai-proxy
```

Store the same token as `AI_REVIEW_API_KEY` in each consuming repository.
Set `AI_REVIEW_ENDPOINT=https://<reviewer-host>/v1/chat/completions`.
