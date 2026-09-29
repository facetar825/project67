"""PostgreSQL repository. Every connection is short lived and transactional."""
from pathlib import Path
import psycopg
from psycopg.rows import dict_row


class Database:
    def __init__(self, dsn):
        self.dsn = dsn

    def connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5,
                               options='-c statement_timeout=10000 -c lock_timeout=5000')

    def initialize(self):
        with self.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(74623819)')
            if conn.execute("SELECT to_regclass('public.users') AS t").fetchone()['t'] is None:
                base = Path(__file__).resolve().parent / 'database'
                conn.execute((base / 'schema.sql').read_text(encoding='utf-8'))
                conn.execute((base / 'seed.sql').read_text(encoding='utf-8'))

    def all(self, sql, args=()):
        with self.connect() as conn:
            return conn.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        with self.connect() as conn:
            return conn.execute(sql, args).fetchone()
