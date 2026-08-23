# Deployment Design

## Recommended free/private deployment

Use Streamlit Community Cloud. Its current free service permits one private app,
and privacy can be changed in the app's Sharing settings. A private repository
produces a private app by default; a public repository app can also be switched
to **Only specific people can view this app**.

Deployment steps after the GitHub source is committed:

1. Sign in at `share.streamlit.io` with the GitHub account that administers
   `coderdazz/options-analytics`.
2. Create an app from branch `main`, entry point `app.py`.
3. In Advanced settings → Secrets, add:

   ```toml
   [alpaca]
   api_key = "..."
   secret_key = "..."
   option_feed = "indicative"
   stock_feed = "iex"
   ```

4. Deploy, then set Sharing → **Only specific people can view this app**.
5. Never paste keys into GitHub, logs, screenshots or the app UI.

The free Alpaca indicative option feed is appropriate for a private research
preview, not executable-price analytics. Paid OPRA can be selected by changing
`option_feed` to `opra` when the account has that entitlement.

## Persistence

Community Cloud's local filesystem is not a durable portfolio database. The
current SQLite mode is correct for local desktop use only. Before relying on the
cloud journal, configure a free PostgreSQL database (Neon is the recommended
minimal choice; Supabase is also suitable) and migrate the repository through
SQLAlchemy/Alembic. Until then, cloud portfolios may be lost on reboot.

Market history should go to partitioned Parquet/object storage, not into the
transactional portfolio database. See `docs/DATA_ARCHITECTURE.md`.

## Local mode

Local mode remains best for private research with a durable SQLite journal and
Parquet market-data lake:

```bash
streamlit run app.py --server.address 127.0.0.1 --server.port 8512
```

## Docker/Render

The Dockerfile and `render.yaml` remain useful as a portable fallback, but a
free public Render web service does not supply Streamlit Community Cloud's
built-in private-viewer controls. Add application authentication and persistent
storage before using that route with personal portfolio data.

