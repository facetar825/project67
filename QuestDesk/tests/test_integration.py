"""Real PostgreSQL tests. A fresh UUID database is created and dropped per test.
Never truncate or reset the user's application database.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
import os
import uuid
import pytest
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from db import Database
from service import Service
from domain import RuleError
from bootstrap import start_database


@pytest.fixture
def svc():
    cfg=conninfo_to_dict(os.environ.get('QUESTDESK_TEST_DSN') or start_database())
    name='questdesk_test_'+uuid.uuid4().hex
    admin=make_conninfo(**dict(cfg,dbname='postgres'))
    with psycopg.connect(admin,autocommit=True) as c:
        c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        db=Database(make_conninfo(**dict(cfg,dbname=name))); db.initialize()
        yield Service(db)
    finally:
        with psycopg.connect(admin,autocommit=True) as c:
            c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def ready(svc,difficulty='normal'):
    qid=svc.save_quest('Подготовить доклад','Собрать материал',difficulty,date.today(),['Найти источники','Проверить выводы'],[1])
    svc.start(qid)
    for step in svc.detail(qid)['steps']: svc.toggle_step(qid,step['id'],True)
    return qid


def test_schema_and_repeatable_initialization(svc):
    svc.db.initialize()
    assert len(svc.db.all("SELECT tablename FROM pg_tables WHERE schemaname='public'"))==8
    assert len(svc.quests())==4
    assert svc.profile()['xp']==0


def test_crud_search_relations(svc):
    qid=svc.save_quest('Изучить PostgreSQL','Ограничения и индексы','easy',None,['Открыть документацию'],[1,3])
    assert len(svc.detail(qid)['skills'])==2
    svc.save_quest('Повторить PostgreSQL','Практика','hard',date.today(),['Написать запрос','Проверить результат'],[1],qid)
    assert svc.quests('Повторить')[0]['id']==qid
    assert len(svc.detail(qid)['steps'])==2
    svc.delete_quest(qid)
    assert svc.quests('Повторить')==[]
    assert svc.db.one('SELECT count(*) AS n FROM quest_steps WHERE quest_id=%s',(qid,))['n']==0


def test_completion_updates_all_balances_atomically(svc):
    qid=ready(svc)
    assert svc.complete(qid)==(80,30)
    assert svc.profile()['xp']==80 and svc.profile()['coins']==30
    assert svc.skills()[0]['xp']==80
    event=next(e for e in svc.history() if e['kind']=='completed')
    assert event['payload']['xp']==80
    with pytest.raises(RuleError): svc.complete(qid)
    assert svc.profile()['xp']==80


def test_incomplete_completion_rolls_back(svc):
    with pytest.raises(RuleError): svc.complete(1)
    assert svc.profile()['xp']==0
    assert svc.detail(1)['status']=='active'
    assert not any(e['kind']=='completed' for e in svc.history())


def test_two_concurrent_completions_award_once(svc):
    qid=ready(svc)
    def complete():
        try: svc.complete(qid); return True
        except RuleError: return False
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:complete(),range(2)))
    assert sum(results)==1
    assert svc.profile()['coins']==30 and svc.profile()['xp']==80


def test_two_concurrent_purchases_cannot_overdraw(svc):
    svc.complete(ready(svc))
    def buy():
        try: svc.redeem(1); return True
        except RuleError: return False
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:buy(),range(2)))
    assert sum(results)==1
    assert svc.profile()['coins']==0 and len(svc.purchases())==1


def test_expiration_once_and_no_negative_balance(svc):
    svc.complete(ready(svc))
    with svc.db.connect() as c:
        c.execute('UPDATE quests SET due_date=%s WHERE id=1',(date.today()-timedelta(days=1),))
    assert svc.expire()==1
    assert svc.profile()['coins']==20
    assert svc.expire()==0
    assert svc.profile()['coins']==20
    qid=ready(svc); svc.fail(qid)
    assert svc.profile()['coins']==10


def test_failure_with_empty_wallet(svc):
    svc.fail(1)
    assert svc.profile()['coins']==0
    with pytest.raises(RuleError): svc.fail(1)


def test_active_quest_cannot_be_edited_or_deleted(svc):
    with pytest.raises(RuleError): svc.delete_quest(1)
    with pytest.raises(RuleError): svc.save_quest('Другая награда','','hard',None,['Шаг'],[],1)


def test_catalog_and_historical_snapshot(svc):
    sid=svc.save_catalog('skills','Чтение','Осмысленное чтение')
    svc.save_catalog('skills','Скорочтение','Практика',item_id=sid)
    svc.delete_catalog('skills',sid)
    with pytest.raises(RuleError): svc.delete_catalog('skills',1)
    rid=svc.save_catalog('rewards','Перерыв','Отдых',10)
    svc.complete(ready(svc)); svc.redeem(rid)
    svc.save_catalog('rewards','Длинный перерыв','Отдых',20,rid)
    svc.delete_catalog('rewards',rid)
    assert svc.purchases()[0]['reward_title']=='Перерыв'
    assert svc.purchases()[0]['cost']==10


def test_validation_and_parameterized_queries(svc):
    with pytest.raises(RuleError): svc.save_quest('  ','','easy',None,['Шаг'],[])
    with pytest.raises(RuleError): svc.save_quest('Учёба','','easy',None,[],[])
    with pytest.raises(RuleError): svc.save_quest('Учёба','','easy',date.today()-timedelta(days=1),['Шаг'],[])
    qid=svc.save_quest("Учёба '; DROP TABLE users; --",'','easy',None,['Прочитать'],[])
    assert svc.detail(qid)['title'].startswith('Учёба')
    assert svc.profile()['name']=='Александр'


def test_constraints(svc):
    with pytest.raises(psycopg.errors.CheckViolation):
        with svc.db.connect() as c: c.execute('UPDATE users SET coins=-1 WHERE id=1')
    with pytest.raises(psycopg.errors.UniqueViolation): svc.save_catalog('skills','Здоровье','Дубликат')
    assert svc.profile()['coins']==0


def test_completed_delete_keeps_earned_state(svc):
    qid=ready(svc); svc.complete(qid); svc.delete_quest(qid)
    assert svc.profile()['xp']==80
    e=next(e for e in svc.history() if e['kind']=='completed')
    assert e['quest_id'] is None and e['payload']['title']=='Подготовить доклад'


def test_inadequate_funds_does_not_create_purchase(svc):
    with pytest.raises(RuleError): svc.redeem(1)
    assert svc.purchases()==[] and svc.profile()['coins']==0
