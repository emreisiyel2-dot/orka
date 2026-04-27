# ORKA Phase 3B — Provider Configuration

## Required Environment Variables

Set these in your shell before starting the backend:

```bash
# REQUIRED — enable real LLM calls
export ORKA_LLM_ENABLED=true

# Pick ONE or more providers (set only the ones you have keys for):

# OpenAI (gpt-4o, gpt-4o-mini)
export OPENAI_API_KEY=sk-...
# export OPENAI_BASE_URL=https://api.openai.com/v1  # optional, default shown
# export OPENAI_QUOTA_TYPE=manual
# export OPENAI_ALLOW_PAID_OVERAGE=false

# Gemini (gemini-2.5-flash — free tier available)
export GEMINI_API_KEY=AIza...
export GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
# export GEMINI_QUOTA_TYPE=manual
# export GEMINI_ALLOW_PAID_OVERAGE=false

# OpenRouter (gateway to many models)
export OPENROUTER_API_KEY=sk-or-...
# export OPENROUTER_QUOTA_TYPE=token_limit
# export OPENROUTER_WEEKLY_LIMIT=1000000
# export OPENROUTER_ALLOW_PAID_OVERAGE=false

# Budget defaults (optional — safe defaults already set)
# export ORKA_DAILY_SOFT_LIMIT=5.0
# export ORKA_DAILY_HARD_LIMIT=10.0
# export ORKA_MONTHLY_HARD_LIMIT=100.0

# Policy
export DEFAULT_AI_MODE=quota_only
export ALLOW_PAID_OVERAGE=false
export PROVIDER_FALLBACK_POLICY=free_or_approved_only
```

## How Provider Registration Works

`ProviderRegistry` is auto-populated from environment variables at startup:

1. `load_config()` in `app/config/model_config.py` reads all `*_API_KEY` vars
2. Non-empty keys create `ProviderConfig` entries
3. `ProviderRegistry.__init__()` converts configs into provider instances
4. OpenAI-compatible providers → `OpenAICompatProvider`
5. OpenRouter → `OpenRouterProvider`

No manual registration needed — just set the env vars.

## Verify Provider Is Active

Start the backend, then:

```bash
# Check providers
curl http://localhost:8000/api/providers

# Expected output (with one provider):
# [
#   {
#     "name": "openai",
#     "healthy": true,
#     "quota_status": "available",
#     "remaining_quota": null,
#     "total_quota": null,
#     "reset_at": null,
#     "allow_paid_overage": false,
#     "models": [
#       {"id": "gpt-4o", "provider": "openai", "tier": "high", ...},
#       {"id": "gpt-4o-mini", "provider": "openai", "tier": "low", ...}
#     ]
#   }
# ]

# Check available models
curl http://localhost:8000/api/models

# Check quota status
curl http://localhost:8000/api/quota/status

# Check budget
curl http://localhost:8000/api/budget/status
```

## Quick Test Command

```bash
# Set your key (example with Gemini):
export ORKA_LLM_ENABLED=true
export GEMINI_API_KEY=your-key-here
export GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/

# Start backend
cd backend && source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# In another terminal, verify:
curl http://localhost:8000/api/providers | python3 -m json.tool
```
