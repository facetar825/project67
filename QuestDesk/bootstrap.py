"""Start an isolated, loopback-only PostgreSQL cluster without a Windows service."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import psycopg
from psycopg.conninfo import make_conninfo

ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
DATA = Path(os.environ.get('QUESTDESK_HOME', str(Path(os.environ.get('LOCALAPPDATA', str(ROOT))) / 'QuestDesk')))


def run(args):
    # A detached postgres child inherits pipe handles on Windows; communicate()
    # would wait until the server stops. Real files avoid that startup deadlock.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run([str(a) for a in args],stdout=output,stderr=output,
                                timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:
            output.seek(0)
            raise RuntimeError('PostgreSQL: ' + output.read().decode('utf-8',errors='replace')[-2000:])
        return result


def local_config():
    DATA.mkdir(parents=True, exist_ok=True)
    config = DATA / 'connection.json'
    if config.exists():
        return json.loads(config.read_text(encoding='utf-8'))
    value = {'host':'127.0.0.1','port':55439,'user':'questdesk',
             'password':secrets.token_urlsafe(32),'dbname':'questdesk'}
    config.write_text(json.dumps(value), encoding='utf-8')
    return value


def start_database():
    external = os.environ.get('QUESTDESK_DSN')
    if external:
        return external
    cfg = local_config()
    source = ROOT / 'vendor' / 'pgsql'
    runtime = DATA / 'runtime' / 'pgsql'
    if not (source / 'bin' / 'pg_ctl.exe').exists():
        raise RuntimeError('Не найдена PostgreSQL. Запустите scripts/setup-postgres.ps1 или задайте QUESTDESK_DSN. Подробности в README.md.')
    # initdb on Windows can misdecode a Cyrillic executable path. Keep its
    # runtime in the local application-data directory, separate from source.
    if not (runtime / '.ready').exists():
        shutil.copytree(source,runtime,dirs_exist_ok=True)
        (runtime / '.ready').touch()
    binaries = runtime / 'bin'
    cluster = DATA / 'pgdata'
    if not (cluster / 'PG_VERSION').exists():
        password_file = DATA / 'init-password.tmp'
        password_file.write_text(cfg['password'], encoding='utf-8')
        try:
            run([binaries / 'initdb.exe','-D',cluster,'-U',cfg['user'],
                 '-A','scram-sha-256','--pwfile',password_file,'--encoding=UTF8','--locale=C'])
        finally:
            password_file.unlink(missing_ok=True)
    state = subprocess.run([str(binaries/'pg_ctl.exe'),'-D',str(cluster),'status'],
                           capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if state.returncode:
        run([binaries/'pg_ctl.exe','-D',cluster,'-l',DATA/'postgres.log',
             '-o',f'-h 127.0.0.1 -p {cfg["port"]}', '-w','-t','30','start'])
    admin = dict(cfg, dbname='postgres')
    with psycopg.connect(make_conninfo(**admin),autocommit=True,connect_timeout=5) as c:
        # Serialize first launch across processes while creating the database.
        c.execute('SELECT pg_advisory_lock(74623820)')
        try:
            if not c.execute('SELECT 1 FROM pg_database WHERE datname=%s',(cfg['dbname'],)).fetchone():
                from psycopg import sql
                c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cfg['dbname'])))
        finally:
            c.execute('SELECT pg_advisory_unlock(74623820)')
    return make_conninfo(**cfg)


if __name__ == '__main__':
    from db import Database
    Database(start_database()).initialize()
    print('PostgreSQL ready; schema and seed installed.')
