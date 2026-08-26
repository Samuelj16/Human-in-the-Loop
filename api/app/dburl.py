"""Normalise a hosted-Postgres connection string for asyncpg.

Managed providers hand you a URL written for libpq (`psycopg`), and asyncpg does
not accept the same query parameters. Neon's copy-paste string is the common
case:

    postgresql://u:p@ep-x-pooler.eu-central-1.aws.neon.tech/neondb
        ?sslmode=require&channel_binding=require

Passed through unchanged that fails twice - the driver is wrong, and asyncpg
rejects `sslmode` and `channel_binding` outright. Rather than make every
deployment guide say "now hand-edit your connection string", the app fixes it.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ASYNC_DRIVER = "postgresql+asyncpg"

# libpq understands these; asyncpg does not and raises on them.
_LIBPQ_ONLY_PARAMS = {"channel_binding", "sslmode", "target_session_attrs", "gssencmode"}

# sslmode values that mean "encrypt the connection".
_SSL_REQUIRED = {"require", "verify-ca", "verify-full", "prefer", "allow"}


def normalize_database_url(url: str) -> str:
    """Return `url` in a form SQLAlchemy's asyncpg dialect accepts.

    Non-Postgres URLs (sqlite, for instance) are returned untouched.
    """
    if not url:
        return url

    parts = urlsplit(url)
    scheme = parts.scheme.lower()

    if not scheme.startswith(("postgres", "postgresql")):
        return url

    # postgres:// and postgresql:// both mean "use the default driver", which
    # under an async engine must be asyncpg.
    if "+" not in scheme:
        scheme = ASYNC_DRIVER
    elif not scheme.endswith("+asyncpg"):
        return url  # an explicit non-asyncpg driver is the caller's choice

    params = parse_qsl(parts.query, keep_blank_values=True)
    kept: list[tuple[str, str]] = []
    ssl_required = False

    for key, value in params:
        lowered = key.lower()
        if lowered == "sslmode":
            ssl_required = value.lower() in _SSL_REQUIRED
            continue
        if lowered in _LIBPQ_ONLY_PARAMS:
            continue
        kept.append((key, value))

    # asyncpg spells it `ssl`, and hosted Postgres always wants TLS.
    if ssl_required and not any(k.lower() == "ssl" for k, _ in kept):
        kept.append(("ssl", "require"))

    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))
