"""Small additive schema migrations for existing DaviSchool databases.

The application historically used SQLite and Render may already contain a
PostgreSQL database created from an older schema.  CREATE TABLE IF NOT EXISTS
does not add columns to an existing table, so these migrations keep old
databases compatible without deleting existing records.
"""
from __future__ import annotations

import os

def _ensure_live_postgres_schema():
    """Apply additive migrations to Render PostgreSQL when DATABASE_URL is present."""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return
    try:
        import psycopg
    except Exception:
        return

    migrations = {
        "users": {
            "email": "TEXT", "password": "TEXT", "role": "TEXT",
            "full_name": "TEXT", "school_id": "INTEGER",
            "student_id": "INTEGER", "teacher_id": "INTEGER", "credential_secret": "TEXT",
        },
        "schools": {
            "name": "TEXT", "email": "TEXT", "code": "TEXT",
            "location": "TEXT", "phone": "TEXT", "principal": "TEXT",
            "school_type": "TEXT", "status": "TEXT",
            "postal_address": "TEXT", "postal_code": "TEXT", "logo_data": "TEXT",
        },
        "pending_schools": {
            "name": "TEXT", "email": "TEXT", "location": "TEXT",
            "phone": "TEXT", "principal": "TEXT", "school_type": "TEXT",
            "auth_code": "TEXT", "timestamp": "TEXT",
        },
        "system_audit": {
            "school_id": "INTEGER", "user_email": "TEXT", "action": "TEXT",
            "details": "TEXT", "timestamp": "TEXT",
        },        "classes": {"school_id": "INTEGER", "name": "TEXT", "level": "TEXT", "stream": "TEXT"},
        "students": {
            "school_id": "INTEGER", "admission_no": "TEXT", "assessment_no": "TEXT",
            "name": "TEXT", "class_id": "INTEGER", "gender": "TEXT",
            "parent_phone": "TEXT", "stream": "TEXT", "category": "TEXT",
            "guardian_name": "TEXT",
        },
        "subjects": {"school_id": "INTEGER", "name": "TEXT", "code": "TEXT", "initial": "TEXT"},
        "exams": {"school_id": "INTEGER", "name": "TEXT", "term": "TEXT", "year": "TEXT", "exam_type": "TEXT"},
        "terms": {"school_id": "INTEGER", "term_name": "TEXT", "year": "TEXT", "start_date": "TEXT", "end_date": "TEXT"},
        "teachers": {
            "school_id": "INTEGER", "name": "TEXT", "email": "TEXT", "phone": "TEXT",
            "tsc_no": "TEXT", "gender": "TEXT", "id_no": "TEXT", "role": "TEXT",
            "employment_type": "TEXT", "status": "TEXT", "department": "TEXT",
        },
        "teacher_allocations": {"school_id": "INTEGER", "teacher_id": "INTEGER", "subject_id": "INTEGER", "class_id": "INTEGER", "responsibility": "TEXT"},
        "billing": {"school_id": "INTEGER", "amount": "TEXT", "status": "TEXT", "due_date": "TEXT", "created_at": "TEXT"},
        "marks": {
            "school_id": "INTEGER", "student_id": "INTEGER", "subject_id": "INTEGER",
            "exam_id": "INTEGER", "class_id": "INTEGER", "marks": "INTEGER",
            "year": "TEXT", "term": "TEXT",
        },
        "set_marks_config": {
            "school_id": "INTEGER", "subject_id": "INTEGER", "class_name": "TEXT",
            "stream": "TEXT", "year": "TEXT", "term": "TEXT", "exam_id": "INTEGER",
            "out_of": "INTEGER", "created_at": "TEXT",
        },
        "timetable": {"school_id": "INTEGER", "day": "TEXT", "start_time": "TEXT", "end_time": "TEXT", "class_name": "TEXT", "stream": "TEXT", "subject": "TEXT", "teacher": "TEXT", "room": "TEXT"},
        "fees": {"school_id": "INTEGER", "student_id": "INTEGER", "amount": "REAL", "paid": "REAL", "description": "TEXT", "due_date": "TEXT", "status": "TEXT"},
        "announcements": {"school_id": "INTEGER", "title": "TEXT", "message": "TEXT", "audience": "TEXT", "created_at": "TEXT"},
        "sms_logs": {"school_id": "INTEGER", "recipient": "TEXT", "message": "TEXT", "status": "TEXT", "created_at": "TEXT"},
        "roles_permissions": {"school_id": "INTEGER", "role": "TEXT", "permission": "TEXT", "enabled": "INTEGER"},
        "integrations": {"school_id": "INTEGER", "name": "TEXT", "status": "TEXT", "config": "TEXT"},
        "report_comments": {"school_id": "INTEGER", "student_id": "INTEGER", "exam_id": "INTEGER", "comment": "TEXT", "created_at": "TEXT"},
        "attendance": {"school_id": "INTEGER", "student_id": "INTEGER", "date": "TEXT", "status": "TEXT"},
        "expenses": {"school_id": "INTEGER", "category": "TEXT", "description": "TEXT", "amount": "REAL", "paid_to": "TEXT", "voucher_no": "TEXT", "date": "TEXT", "status": "TEXT"},
        "pledges": {"school_id": "INTEGER", "parent_name": "TEXT", "phone": "TEXT", "amount": "REAL", "paid": "REAL", "purpose": "TEXT", "due_date": "TEXT", "status": "TEXT"},
        "payment_vouchers": {"school_id": "INTEGER", "voucher_no": "TEXT", "payee": "TEXT", "description": "TEXT", "amount": "REAL", "date": "TEXT", "status": "TEXT"},
        "lpos": {"school_id": "INTEGER", "lpo_no": "TEXT", "supplier": "TEXT", "description": "TEXT", "amount": "REAL", "date": "TEXT", "status": "TEXT"},
        "cashbook": {"school_id": "INTEGER", "date": "TEXT", "reference": "TEXT", "description": "TEXT", "debit": "REAL", "credit": "REAL", "account": "TEXT"},
        "fee_payments": {"school_id": "INTEGER", "student_id": "INTEGER", "amount": "REAL", "reference": "TEXT", "method": "TEXT", "date": "TEXT", "received_by": "TEXT"},
        "finance_accounts": {"school_id": "INTEGER", "code": "TEXT", "name": "TEXT", "type": "TEXT", "opening_balance": "REAL"},

    }

    with psycopg.connect(database_url) as pg:
        with pg.cursor() as cur:
            for table, columns in migrations.items():
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s",
                    (table,),
                )
                existing = {row[0] for row in cur.fetchall()}
                for column, definition in columns.items():
                    if column not in existing:
                        cur.execute(
                            f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}'
                        )
        pg.commit()



def ensure_schema_compatibility(con):
    cur = con.cursor()

    migrations = {
        "users": {
            "email": "TEXT",
            "password": "TEXT",
            "role": "TEXT",
            "full_name": "TEXT",
            "school_id": "INTEGER",
            "student_id": "INTEGER",
            "teacher_id": "INTEGER",
        },
        "schools": {
            "name": "TEXT",
            "email": "TEXT",
            "code": "TEXT",
            "location": "TEXT",
            "phone": "TEXT",
            "principal": "TEXT",
            "school_type": "TEXT", "status": "TEXT",
            "postal_address": "TEXT", "postal_code": "TEXT", "logo_data": "TEXT",
        },
        "pending_schools": {
            "name": "TEXT",
            "email": "TEXT",
            "location": "TEXT",
            "phone": "TEXT",
            "principal": "TEXT",
            "school_type": "TEXT",
            "auth_code": "TEXT",
            "timestamp": "TEXT",
        },
        "system_audit": {
            "school_id": "INTEGER",
            "user_email": "TEXT",
            "action": "TEXT",
            "details": "TEXT",
            "timestamp": "TEXT",
        },
        "teachers": {"status": "TEXT", "department": "TEXT"},
        "teacher_allocations": {"responsibility": "TEXT"},
    }

    for table, columns in migrations.items():
        for column, definition in columns.items():
            try:
                cur.execute(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"
                )
            except Exception:
                # SQLite does not support IF NOT EXISTS on ADD COLUMN.
                try:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                except Exception:
                    pass

    con.commit()

    # Keep the live Render PostgreSQL schema compatible with older deployments.
    try:
        _ensure_live_postgres_schema()
    except Exception as exc:
        print("DAVISCHOOL POSTGRES SCHEMA MIGRATION ERROR:", repr(exc), flush=True)
