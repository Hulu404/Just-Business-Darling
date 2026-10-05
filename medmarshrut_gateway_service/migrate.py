"""Check or apply versioned gateway PostgreSQL migrations in an explicitly selected schema."""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from store import StoreError, checked_dsn, checked_schema

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = Path(__file__).with_name("migrations")


def digest(source: bytes) -> str:
    """Line endings do not count: git with core.autocrlf gives the same file as LF or CRLF."""
    return hashlib.sha256(source.replace(b"\r\n", b"\n")).hexdigest()


def same_migration(stored: str, source: bytes) -> bool:
    """Schemas applied before the fix keep the hash of the raw bytes, LF or CRLF."""
    lf = source.replace(b"\r\n", b"\n")
    return stored in {hashlib.sha256(lf).hexdigest(), hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest()}


def local_env() -> dict[str, str]:
    result = dict(os.environ)
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() in {"GATEWAY_DATABASE_URL", "GATEWAY_DB_SCHEMA", "GATEWAY_SUPABASE_PROJECT_REF"}:
                result.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return result


def run(mode: str, env: dict[str, str]) -> None:
    dsn = checked_dsn(env.get("GATEWAY_DATABASE_URL", ""))
    schema = checked_schema(env.get("GATEWAY_DB_SCHEMA", ""))
    ref = env.get("GATEWAY_SUPABASE_PROJECT_REF", "")
    if not ref:
        raise StoreError("Укажите GATEWAY_SUPABASE_PROJECT_REF назначенного проекта.")
    from urllib.parse import urlsplit
    parts = urlsplit(dsn)
    local = ref == "local" and parts.hostname in {"127.0.0.1", "localhost"}
    if not local and ref not in (parts.hostname or "") and ref not in (parts.username or ""):
        raise StoreError("GATEWAY_DATABASE_URL не соответствует назначенному проекту Supabase.")
    try:
        import psycopg
    except ImportError:
        raise StoreError("Установите psycopg[binary] из requirements.txt шлюза.") from None
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                if mode == "apply":
                    cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                cur.execute("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = %s)", (schema,))
                exists = cur.fetchone()[0]
                if exists:
                    cur.execute("SELECT has_schema_privilege(current_user, %s, 'USAGE,CREATE')", (schema,))
                    if not cur.fetchone()[0]:
                        raise StoreError("Серверной роли нужны USAGE и CREATE в назначенной схеме.")
                    cur.execute(f'SET search_path TO "{schema}", pg_catalog')
                if mode == "apply":
                    cur.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                                "(version text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
                    cur.execute("ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY")
                applied = {}
                if exists:
                    cur.execute("SELECT to_regclass(%s)", (f'{schema}.schema_migrations',))
                    if cur.fetchone()[0] is not None:
                        cur.execute("SELECT version, sha256 FROM schema_migrations")
                        applied = dict(cur.fetchall())
            for file in sorted(MIGRATIONS.glob("[0-9]*.sql")):
                source = file.read_bytes()
                if file.stem in applied:
                    if not same_migration(applied[file.stem], source):
                        raise StoreError(f"Миграция {file.name} изменена после применения.")
                    print(f"[ок] {file.name} уже применена")
                elif mode == "check":
                    print(f"[ожидает] {file.name}")
                else:
                    with conn.transaction():
                        with conn.cursor() as cur:
                            cur.execute(source.decode("utf-8"))
                            cur.execute("INSERT INTO schema_migrations (version, sha256) VALUES (%s, %s)",
                                        (file.stem, digest(source)))
                    print(f"[ок] {file.name} применена")
    except StoreError:
        raise
    except Exception:
        raise StoreError("Миграция не выполнена. Проверьте подключение, права и схему PostgreSQL.") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "apply"))
    args = parser.parse_args()
    try:
        run(args.mode, local_env())
    except StoreError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
