"""Server-only PostgreSQL storage for gateway data."""
from __future__ import annotations

import re
import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from queue import Empty, LifoQueue
from urllib.parse import parse_qs, urlsplit

from catalog import FINDING_TEXTS, FOLLOWUPS, SERVICES, STUDY_NAMES

SCHEMA_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")


class StoreError(RuntimeError):
    pass


class StoreConflict(StoreError):
    pass


def checked_schema(name: str) -> str:
    if not isinstance(name, str) or not SCHEMA_NAME.fullmatch(name):
        raise StoreError("GATEWAY_DB_SCHEMA: укажите имя схемы из латинских букв, цифр и подчёркивания.")
    return name


def checked_dsn(dsn: str) -> str:
    if not dsn:
        raise StoreError("GATEWAY_DATABASE_URL не задан. Укажите серверное подключение PostgreSQL.")
    try:
        parts = urlsplit(dsn)
        mode = parse_qs(parts.query).get("sslmode", [""])[-1]
    except ValueError:
        raise StoreError("Неверный GATEWAY_DATABASE_URL.") from None
    if parts.scheme not in {"postgresql", "postgres"} or not parts.hostname or mode not in {"require", "verify-ca", "verify-full"}:
        raise StoreError("GATEWAY_DATABASE_URL должен быть PostgreSQL URL с sslmode=require или строже.")
    return dsn


class GatewayStore:
    def __init__(self, dsn: str, schema: str, connect=None):
        checked_dsn(dsn)
        self.schema = checked_schema(schema)
        if connect is None:
            try:
                import psycopg
            except ImportError:
                raise StoreError("Установите зависимости шлюза: python -m pip install -r medmarshrut_gateway_service/requirements.txt") from None
            connect = psycopg.connect
        try:
            self._connect = connect
            self._dsn = dsn
            self._idle: LifoQueue = LifoQueue()
            self.db = connect(dsn, autocommit=True)
            with self.db.cursor() as cur:
                cur.execute(f'SET search_path TO "{self.schema}", pg_catalog')
                cur.execute("SELECT has_schema_privilege(current_user, %s, 'USAGE')", (self.schema,))
                if not cur.fetchone()[0]:
                    raise StoreError("Серверная роль не имеет доступа к выбранной схеме PostgreSQL.")
        except StoreError:
            raise
        except Exception:
            raise StoreError("Не удалось подключиться к PostgreSQL или проверить схему. Проверьте параметры стенда.") from None

    def _open(self):
        conn = self._connect(self._dsn, autocommit=True)
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{self.schema}", pg_catalog')
        return conn

    @contextmanager
    def transaction(self, *, read_only: bool = False):
        """One transaction on a reused connection: a new TLS connection to a remote database costs seconds.
        read_only: a single SELECT in autocommit, without BEGIN/COMMIT round trips."""
        conn = None
        try:
            while conn is None:
                try:
                    conn = self._idle.get_nowait()
                except Empty:
                    conn = self._open()
                    break
                if conn.closed or getattr(conn, "broken", False):
                    conn = None
            with conn.cursor() as cur:
                if read_only:
                    yield cur
                else:
                    with conn.transaction():
                        yield cur
        except StoreError:
            if conn is not None:
                self._idle.put(conn)  # e.g. StoreConflict: the transaction rolled back, the connection is fine
            raise
        except Exception:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            raise StoreError("Операция PostgreSQL не выполнена. Проверьте доступность базы и повторите действие.") from None
        else:
            self._idle.put(conn)

    def close(self) -> None:
        while True:
            try:
                self._idle.get_nowait().close()
            except Empty:
                break
        self.db.close()

    def verify_schema(self) -> None:
        try:
            with self.db.cursor() as cur:
                cur.execute("SELECT to_regclass('services'), to_regclass('finding_texts'), "
                            "to_regclass('slots'), to_regclass('appointments'), to_regclass('study_registry'), "
                            "to_regclass('referral_links'), to_regclass('assistant_texts')")
                if not all(cur.fetchone()):
                    raise StoreError("Миграция шлюза не применена. Запустите migrate.py apply для выбранной схемы.")
                cur.execute("""SELECT count(*)=11 AND bool_and(
                               has_table_privilege(current_user, quote_ident(%s) || '.' || quote_ident(tablename), 'SELECT')
                               AND has_table_privilege(current_user, quote_ident(%s) || '.' || quote_ident(tablename), 'INSERT')
                               AND has_table_privilege(current_user, quote_ident(%s) || '.' || quote_ident(tablename), 'UPDATE')
                               AND has_table_privilege(current_user, quote_ident(%s) || '.' || quote_ident(tablename), 'DELETE'))
                               FROM pg_tables WHERE schemaname=%s AND tablename IN
                                ('services','service_followups','finding_texts','slots','appointments',
                                'threads','messages','outcome_submissions','study_registry','referral_links',
                                'assistant_texts')""",
                            (self.schema, self.schema, self.schema, self.schema, self.schema))
                if not cur.fetchone()[0]:
                    raise StoreError("Серверной роли нужны права чтения и записи таблиц шлюза.")
        except StoreError:
            raise
        except Exception:
            raise StoreError("Не удалось проверить миграцию шлюза в PostgreSQL.") from None

    def clear_working(self) -> None:
        """Clean data tied to IDs of the freshly recreated core services."""
        with self.transaction() as cur:
            for table in ("messages", "threads", "appointments", "slots", "outcome_submissions", "study_registry",
                          "referral_links", "assistant_texts"):
                cur.execute(f"DELETE FROM {table}")

    def seed_catalog(self, clinic_id: str) -> None:
        with self.transaction() as cur:
            for code, title, kind, specialist, room, aliases in SERVICES:
                cur.execute("""INSERT INTO services
                    (clinic_id, code, title, kind, specialist, room, step_aliases)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (clinic_id, code) DO UPDATE SET
                      title=EXCLUDED.title, kind=EXCLUDED.kind, specialist=EXCLUDED.specialist,
                      room=EXCLUDED.room, step_aliases=EXCLUDED.step_aliases, updated_at=now()""",
                    (clinic_id, code, title, kind, specialist, room, aliases))
            for finding, code, position, days, note, default in FOLLOWUPS:
                cur.execute("""INSERT INTO service_followups
                    (clinic_id, finding_code, service_code, position, due_days, due_note, is_default)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (clinic_id, finding_code, service_code) DO UPDATE SET
                      position=EXCLUDED.position, due_days=EXCLUDED.due_days,
                      due_note=EXCLUDED.due_note, is_default=EXCLUDED.is_default""",
                    (clinic_id, finding, code, position, days, note, default))
            for code, (seen, means, approved) in FINDING_TEXTS.items():
                cur.execute("""INSERT INTO finding_texts
                    (clinic_id, finding_code, seen, means, approved)
                    VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT (clinic_id, finding_code) DO UPDATE SET
                      seen=EXCLUDED.seen, means=EXCLUDED.means,
                      approved=EXCLUDED.approved, updated_at=now()""",
                    (clinic_id, code, seen, means, approved))

    def catalogue(self, clinic_id: str) -> dict:
        with self.transaction() as cur:
            cur.execute("SELECT id, code, title, kind, specialist, room, partner_only, step_aliases "
                        "FROM services WHERE clinic_id=%s AND is_active ORDER BY id", (clinic_id,))
            services = [dict(zip(("id", "code", "title", "kind", "specialist", "room", "partner_only", "step_aliases"), row))
                        for row in cur.fetchall()]
            cur.execute("SELECT finding_code, service_code, position, due_days, due_note, is_default "
                        "FROM service_followups WHERE clinic_id=%s ORDER BY finding_code, position", (clinic_id,))
            followups = [dict(zip(("finding_code", "service_code", "position", "due_days", "due_note", "is_default"), row))
                         for row in cur.fetchall()]
        return {"services": services, "followups": followups,
                "study_names": [{"study_type": typ, "anatomy": anatomy, "title": title}
                                for (typ, anatomy), title in STUDY_NAMES.items()], "demo": True}

    def explanation(self, clinic_id: str, finding_code: str) -> dict | None:
        with self.transaction(read_only=True) as cur:
            cur.execute("SELECT seen, means FROM finding_texts WHERE clinic_id=%s AND finding_code=%s AND approved",
                        (clinic_id, finding_code))
            row = cur.fetchone()
        return {"seen": row[0], "means": row[1]} if row else None

    def generate_slots(self, clinic_id: str, *, now: datetime | None = None) -> None:
        now = now or datetime.now().astimezone()
        days = []
        cursor_day = now.date()
        while len(days) < 3:
            cursor_day += timedelta(days=1)
            if cursor_day.weekday() < 5:
                days.append(cursor_day)
        with self.transaction() as cur:
            cur.execute("SELECT id, code, specialist, room FROM services WHERE clinic_id=%s AND is_active", (clinic_id,))
            for service_id, code, specialist, room in cur.fetchall():
                for day in days:
                    for hour in (10, 15):
                        starts = datetime.combine(day, datetime.min.time(), tzinfo=now.tzinfo).replace(hour=hour)
                        cur.execute("""INSERT INTO slots
                            (clinic_id, service_id, specialist, place, format, starts_at)
                            VALUES (%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (clinic_id, service_id, specialist, starts_at) DO NOTHING""",
                            (clinic_id, service_id, specialist or "Специалист клиники", "Центральный филиал" + (f", кабинет {room}" if room else ""),
                             "Очно", starts))

    def slots(self, clinic_id: str, description: str) -> list[dict]:
        with self.transaction() as cur:
            cur.execute("""SELECT s.id, s.starts_at, s.specialist, s.place, s.format, s.price,
                           v.code, v.title
                           FROM slots s JOIN services v ON v.id=s.service_id
                           WHERE s.clinic_id=%s AND s.starts_at>now()
                             AND (v.title=%s OR %s=ANY(v.step_aliases))
                             AND NOT EXISTS (SELECT 1 FROM appointments a WHERE a.slot_id=s.id
                                             AND a.status IN ('offered','confirmed'))
                           ORDER BY s.starts_at LIMIT 30""", (clinic_id, description, description))
            rows = cur.fetchall()
        return [{"id": str(row[0]), "starts_at": row[1].isoformat(), "specialist": row[2],
                 "place": row[3], "format": row[4], "price": str(row[5]) if row[5] is not None else None,
                 "service_code": row[6], "service_title": row[7], "demo": True} for row in rows]

    def reserve_slot(self, clinic_id: str, patient_ref: str, episode_id: str, step_id: str,
                     description: str, slot_id: str, booked_by: str, booked_by_id: str) -> tuple[dict, int | None]:
        """Reserve before calling the path service. Return the previous offered row for compensation."""
        if not slot_id.isdecimal():
            raise StoreConflict("Выберите время из списка и попробуйте снова.")
        with self.transaction() as cur:
            cur.execute("""SELECT s.starts_at, s.place, s.format FROM slots s
                           JOIN services v ON v.id=s.service_id
                           WHERE s.id=%s AND s.clinic_id=%s AND s.starts_at>now()
                             AND (v.title=%s OR %s=ANY(v.step_aliases))""",
                        (int(slot_id), clinic_id, description, description))
            slot = cur.fetchone()
            if not slot:
                raise StoreConflict("Это время больше недоступно. Обновите список и выберите другое.")
            cur.execute("""SELECT id, slot_id, status FROM appointments
                           WHERE episode_id=%s AND step_id=%s AND status IN ('offered','confirmed')
                           FOR UPDATE""", (episode_id, step_id))
            old = cur.fetchone()
            if old and old[2] == "confirmed":
                raise StoreConflict("Запись уже подтверждена. Координатор поможет изменить план.")
            if old and old[1] == int(slot_id):
                return {"id": old[0], "starts_at": slot[0].isoformat(), "place": slot[1], "format": slot[2],
                        "reused": True}, None
            if old:
                cur.execute("UPDATE appointments SET status='cancelled', cancelled_at=now(), updated_at=now() WHERE id=%s", (old[0],))
            cur.execute("""INSERT INTO appointments
                (episode_id, step_id, patient_ref, slot_id, clinic_id, starts_at, place, format,
                 status, booked_by, booked_by_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'offered',%s,%s)
                ON CONFLICT DO NOTHING RETURNING id""",
                (episode_id, step_id, patient_ref, int(slot_id), clinic_id, slot[0], slot[1], slot[2],
                 booked_by, booked_by_id))
            row = cur.fetchone()
            if not row:
                raise StoreConflict("Это время уже занято. Обновите список и выберите другое.")
            return {"id": row[0], "starts_at": slot[0].isoformat(), "place": slot[1], "format": slot[2],
                    "reused": False}, old[0] if old else None

    def appointment_status(self, appointment_id: int, status: str) -> None:
        with self.transaction() as cur:
            cur.execute("UPDATE appointments SET status=%s, updated_at=now() WHERE id=%s", (status, appointment_id))

    def appointment_for_step(self, episode_id: str, step_id: str) -> dict | None:
        with self.transaction(read_only=True) as cur:
            cur.execute("""SELECT id, starts_at, status FROM appointments
                           WHERE episode_id=%s AND step_id=%s AND status IN ('offered','confirmed')""",
                        (episode_id, step_id))
            row = cur.fetchone()
        return {"id": row[0], "starts_at": row[1].isoformat(), "status": row[2]} if row else None

    def undo_reservation(self, appointment_id: int, old_id: int | None) -> None:
        with self.transaction() as cur:
            cur.execute("DELETE FROM appointments WHERE id=%s AND status='offered'", (appointment_id,))
            if old_id is not None:
                cur.execute("UPDATE appointments SET status='offered', cancelled_at=NULL, updated_at=now() WHERE id=%s", (old_id,))

    def cancel_appointment(self, episode_id: str, step_id: str) -> None:
        with self.transaction() as cur:
            cur.execute("""UPDATE appointments SET status='cancelled', cancelled_at=now(), updated_at=now()
                           WHERE episode_id=%s AND step_id=%s AND status IN ('offered','confirmed')""",
                        (episode_id, step_id))

    def add_patient_message(self, clinic_id: str, patient_ref: str, actor: str, episode_id: str,
                            step_id: str | None, intent: str, body: str) -> None:
        with self.transaction() as cur:
            cur.execute("""INSERT INTO threads (kind, clinic_id, patient_ref, opened_by_role, opened_by)
                           VALUES ('patient',%s,%s,'patient',%s)
                           ON CONFLICT DO NOTHING""", (clinic_id, patient_ref, actor))
            cur.execute("SELECT id FROM threads WHERE kind='patient' AND clinic_id=%s AND patient_ref=%s",
                        (clinic_id, patient_ref))
            thread_id = cur.fetchone()[0]
            cur.execute("""INSERT INTO messages
                           (thread_id, sender_role, sender_id, body, intent, episode_id, step_id, needs_action)
                           VALUES (%s,'patient',%s,%s,%s,%s,%s,true)""",
                        (thread_id, actor, body, intent, episode_id, step_id))

    def pending_patient_messages(self, clinic_id: str) -> list[dict]:
        with self.transaction(read_only=True) as cur:
            cur.execute("""SELECT m.id, t.patient_ref, m.episode_id, m.step_id, m.intent,
                           m.body, m.created_at FROM messages m JOIN threads t ON t.id=m.thread_id
                           WHERE t.clinic_id=%s AND m.needs_action AND m.resolved_at IS NULL
                           ORDER BY m.created_at""", (clinic_id,))
            rows = cur.fetchall()
        return [{"id": str(row[0]), "patient_ref": row[1], "episode_id": row[2], "step_id": row[3],
                 "intent": row[4], "body": row[5], "created_at": row[6].isoformat()} for row in rows]

    STUDY_FIELDS = ("job_id", "clinic_id", "patient_ref", "task", "title", "kit", "uploaded_by_role",
                    "uploaded_by", "consent_at", "created_at")

    def _study_row(self, row) -> dict:
        study = dict(zip(self.STUDY_FIELDS, row))
        for key in ("consent_at", "created_at"):
            study[key] = study[key].isoformat() if study[key] else None
        return study

    def register_study(self, job_id: str, clinic_id: str, patient_ref: str | None, task: str, title: str | None,
                       kit: str | None, uploaded_by_role: str, uploaded_by: str, consent_at: datetime | None) -> dict:
        """Idempotent by job_id: a repeat with the same owner returns the stored row, another owner is a conflict."""
        with self.transaction() as cur:
            cur.execute("""INSERT INTO study_registry
                           (job_id, clinic_id, patient_ref, task, title, kit, uploaded_by_role, uploaded_by, consent_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (job_id) DO NOTHING""",
                        (job_id, clinic_id, patient_ref, task, title, kit, uploaded_by_role, uploaded_by, consent_at))
            cur.execute(f"SELECT {', '.join(self.STUDY_FIELDS)} FROM study_registry WHERE job_id=%s", (job_id,))
            study = self._study_row(cur.fetchone())
        if (study["clinic_id"], study["patient_ref"], study["task"]) != (clinic_id, patient_ref, task):
            raise StoreConflict("Это исследование уже зарегистрировано за другим пациентом. Загрузите его заново.")
        return study

    def studies(self, clinic_id: str, patient_ref: str | None = None) -> list[dict]:
        with self.transaction(read_only=True) as cur:
            if patient_ref is None:
                cur.execute(f"SELECT {', '.join(self.STUDY_FIELDS)} FROM study_registry WHERE clinic_id=%s "
                            "ORDER BY created_at DESC, job_id", (clinic_id,))
            else:
                cur.execute(f"SELECT {', '.join(self.STUDY_FIELDS)} FROM study_registry WHERE clinic_id=%s "
                            "AND patient_ref=%s ORDER BY created_at DESC, job_id", (clinic_id, patient_ref))
            return [self._study_row(row) for row in cur.fetchall()]

    def study(self, clinic_id: str, job_id: str) -> dict | None:
        with self.transaction(read_only=True) as cur:
            cur.execute(f"SELECT {', '.join(self.STUDY_FIELDS)} FROM study_registry WHERE clinic_id=%s AND job_id=%s",
                        (clinic_id, job_id))
            row = cur.fetchone()
        return self._study_row(row) if row else None

    def link_referral(self, referral_id: str, episode_id: str, step_id: str, created_by: str) -> dict:
        """Idempotent: a repeat for the same step returns the stored link, another step is a conflict."""
        with self.transaction() as cur:
            cur.execute("""INSERT INTO referral_links (referral_id, episode_id, step_id, created_by)
                           VALUES (%s,%s,%s,%s) ON CONFLICT (referral_id) DO NOTHING""",
                        (referral_id, episode_id, step_id, created_by))
            cur.execute("SELECT referral_id, episode_id, step_id, created_by, created_at FROM referral_links "
                        "WHERE referral_id=%s", (referral_id,))
            row = cur.fetchone()
        link = {"referral_id": row[0], "episode_id": row[1], "step_id": row[2], "created_by": row[3],
                "created_at": row[4].isoformat()}
        if (link["episode_id"], link["step_id"]) != (episode_id, step_id):
            raise StoreConflict("Это направление уже связано с другим шагом плана. Откройте его во вкладке «Направления».")
        return link

    def referral_links(self, referral_ids: list[str] | None = None) -> dict[str, dict]:
        with self.transaction(read_only=True) as cur:
            if referral_ids is None:
                cur.execute("SELECT referral_id, episode_id, step_id FROM referral_links")
            else:
                cur.execute("SELECT referral_id, episode_id, step_id FROM referral_links WHERE referral_id = ANY(%s)",
                            (list(referral_ids),))
            return {row[0]: {"episode_id": row[1], "step_id": row[2]} for row in cur.fetchall()}

    def assistant_text(self, job_id: str, input_hash: str) -> str | None:
        with self.transaction(read_only=True) as cur:
            cur.execute("SELECT body FROM assistant_texts WHERE job_id=%s AND input_hash=%s", (job_id, input_hash))
            row = cur.fetchone()
        return row[0] if row else None

    def save_assistant_text(self, job_id: str, input_hash: str, model: str, body: str) -> str:
        """Idempotent: two windows asking at once keep the first stored text."""
        with self.transaction() as cur:
            cur.execute("""INSERT INTO assistant_texts (job_id, input_hash, model, body) VALUES (%s,%s,%s,%s)
                           ON CONFLICT (job_id, input_hash) DO NOTHING""", (job_id, input_hash, model, body))
            cur.execute("SELECT body FROM assistant_texts WHERE job_id=%s AND input_hash=%s", (job_id, input_hash))
            return cur.fetchone()[0]

    def outcome_timestamp(self, event_id: str, episode_id: str, step_id: str,
                          physician_id: str, content: dict) -> str:
        """Pin the timestamp and content of an outcome across retries and restarts."""
        digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode("utf-8")).hexdigest()
        with self.transaction() as cur:
            cur.execute("""INSERT INTO outcome_submissions
                           (event_id, episode_id, step_id, physician_id, confirmed_at, body_hash)
                           VALUES (%s,%s,%s,%s,now(),%s) ON CONFLICT (event_id) DO NOTHING""",
                        (event_id, episode_id, step_id, physician_id, digest))
            cur.execute("""SELECT episode_id, step_id, physician_id, confirmed_at, body_hash
                           FROM outcome_submissions WHERE event_id=%s FOR UPDATE""", (event_id,))
            prior = cur.fetchone()
            if prior[:3] != (episode_id, step_id, physician_id) or prior[4] != digest:
                raise StoreConflict("Этот идентификатор итога уже использован для другого содержания. Откройте форму заново.")
            return prior[3].isoformat()
