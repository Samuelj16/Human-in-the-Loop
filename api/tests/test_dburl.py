"""Hosted-Postgres URLs must survive contact with asyncpg."""
import pytest

from app.dburl import normalize_database_url as norm

NEON = (
    "postgresql://user:pw@ep-cool-name-pooler.eu-central-1.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require"
)


def test_neon_copy_paste_url_becomes_usable():
    """The exact string Neon's dashboard gives you fails twice untouched:
    wrong driver, and two parameters asyncpg rejects outright."""
    result = norm(NEON)

    assert result.startswith("postgresql+asyncpg://")
    assert "channel_binding" not in result
    assert "sslmode" not in result
    assert "ssl=require" in result
    assert "ep-cool-name-pooler.eu-central-1.aws.neon.tech/neondb" in result


def test_credentials_are_preserved():
    assert "user:pw@" in norm(NEON)


@pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
def test_bare_schemes_get_the_async_driver(scheme):
    assert norm(f"{scheme}://u:p@host/db").startswith("postgresql+asyncpg://")


def test_existing_asyncpg_url_is_left_alone():
    url = "postgresql+asyncpg://u:p@localhost:5432/hitl"
    assert norm(url) == url


def test_explicit_sync_driver_is_respected():
    """psycopg is a deliberate choice - do not silently rewrite it."""
    url = "postgresql+psycopg://u:p@localhost/db"
    assert norm(url) == url


def test_sqlite_passes_through():
    url = "sqlite+aiosqlite:///./hitl.db"
    assert norm(url) == url


def test_empty_url_passes_through():
    assert norm("") == ""


def test_sslmode_disable_does_not_add_ssl():
    result = norm("postgresql://u:p@host/db?sslmode=disable")
    assert "ssl=" not in result


def test_unrelated_params_survive():
    result = norm("postgresql://u:p@host/db?sslmode=require&application_name=hitl")
    assert "application_name=hitl" in result
    assert "ssl=require" in result


def test_ssl_is_not_duplicated():
    result = norm("postgresql://u:p@host/db?sslmode=require&ssl=require")
    assert result.count("ssl=require") == 1
