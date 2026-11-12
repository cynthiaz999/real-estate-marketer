#!/bin/sh
# Starts the app on any host (Render, Railway, Fly.io, a VPS...).
# Put the ENTIRE contents of your secrets file (including the [auth] section)
# into one environment variable named STREAMLIT_SECRETS_TOML.
set -e
if [ -n "$STREAMLIT_SECRETS_TOML" ]; then
  mkdir -p .streamlit
  printf '%s\n' "$STREAMLIT_SECRETS_TOML" > .streamlit/secrets.toml
  chmod 600 .streamlit/secrets.toml
else
  echo "WARNING: STREAMLIT_SECRETS_TOML is not set; the app will show a setup error." >&2
fi
exec streamlit run app.py \
  --server.port "${PORT:-8501}" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false
