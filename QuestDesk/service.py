"""Application service: all mutations lock the profile before dependent rows.

This common lock order prevents duplicate rewards and overspending when two
windows operate on the same profile. History and balances commit together.
"""
from datetime import date
from psycopg.types.json import Jsonb
from domain import REWARDS, RuleError, validate_text, require_state


class Service:
    def __init__(self, db, user_id=1):
        self.db, self.uid = db, user_id

    def _lock(self, conn):
        user = conn.execute('SELECT * FROM users WHERE id=%s FOR UPDATE', (self.uid,)).fetchone()
        if user is None:
            raise RuleError('Профиль не найден.')
        return user

    def _quest(self, conn, qid):
        q = conn.execute('SELECT * FROM quests WHERE id=%s AND user_id=%s FOR UPDATE', (qid,self.uid)).fetchone()
        if q is None:
            raise RuleError('Квест не найден. Обновите список.')
        return q

    def _event(self, conn, kind, message, qid=None, **payload):
        conn.execute('INSERT INTO events(user_id,quest_id,kind,message,payload) VALUES (%s,%s,%s,%s,%s)',
                     (self.uid,qid,kind,message,Jsonb(payload)))

    def profile(self):
        return self.db.one('SELECT * FROM users WHERE id=%s', (self.uid,))

    def quests(self, search='', status=None):
        return self.db.all('''SELECT q.*,count(s.id)::int AS total_steps,
            count(s.id) FILTER (WHERE s.done)::int AS done_steps FROM quests q
            LEFT JOIN quest_steps s ON s.quest_id=q.id
            WHERE q.user_id=%s AND q.title ILIKE %s AND (%s::text IS NULL OR q.status::text=%s)
            GROUP BY q.id ORDER BY CASE q.status WHEN 'active' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END,
            q.due_date NULLS LAST,q.id''', (self.uid,'%'+search+'%',status,status))

    def detail(self, qid):
        q = self.db.one('SELECT * FROM quests WHERE id=%s AND user_id=%s',(qid,self.uid))
        if not q:
            raise RuleError('Квест не найден.')
        q['steps'] = self.db.all('SELECT * FROM quest_steps WHERE quest_id=%s ORDER BY position',(qid,))
        q['skills'] = self.db.all('SELECT s.* FROM skills s JOIN quest_skills qs ON qs.skill_id=s.id WHERE qs.quest_id=%s ORDER BY s.id',(qid,))
        return q

    def skills(self):
        return self.db.all('SELECT * FROM skills WHERE user_id=%s ORDER BY id',(self.uid,))

    def rewards(self):
        return self.db.all('SELECT * FROM rewards WHERE user_id=%s ORDER BY cost,id',(self.uid,))

    def history(self):
        return self.db.all('SELECT * FROM events WHERE user_id=%s ORDER BY created_at DESC,id DESC LIMIT 200',(self.uid,))

    def purchases(self):
        return self.db.all('SELECT * FROM redemptions WHERE user_id=%s ORDER BY created_at DESC LIMIT 100',(self.uid,))

    def rename(self, name):
        name=validate_text(name,'Имя',80)
        with self.db.connect() as c:
            self._lock(c)
            c.execute('UPDATE users SET name=%s WHERE id=%s',(name,self.uid))
            self._event(c,'profile','Обновлено имя профиля')

    def save_quest(self, title, description, difficulty, due, steps, skill_ids, qid=None):
        title=validate_text(title,'Название',120)
        if difficulty not in REWARDS:
            raise RuleError('Выберите сложность.')
        if due and due < date.today():
            raise RuleError('Срок не может быть в прошлом.')
        steps=[validate_text(s,'Шаг',200) for s in steps if s.strip()]
        if not 1 <= len(steps) <= 20:
            raise RuleError('Добавьте от 1 до 20 шагов, каждый с новой строки.')
        if len(description) > 4000:
            raise RuleError('Описание: не более 4000 символов.')
        skill_ids=list(set(skill_ids))
        with self.db.connect() as c:
            self._lock(c)
            valid={r['id'] for r in c.execute('SELECT id FROM skills WHERE user_id=%s',(self.uid,))}
            if not set(skill_ids) <= valid:
                raise RuleError('Один из навыков больше не существует.')
            if qid is not None:
                q=self._quest(c,qid)
                require_state(q,'draft')
                c.execute('UPDATE quests SET title=%s,description=%s,difficulty=%s,due_date=%s WHERE id=%s',
                          (title,description.strip(),difficulty,due,qid))
                c.execute('DELETE FROM quest_steps WHERE quest_id=%s',(qid,))
                c.execute('DELETE FROM quest_skills WHERE quest_id=%s',(qid,))
            else:
                qid=c.execute('INSERT INTO quests(user_id,title,description,difficulty,due_date) VALUES (%s,%s,%s,%s,%s) RETURNING id',
                              (self.uid,title,description.strip(),difficulty,due)).fetchone()['id']
                q=None
            for pos, step in enumerate(steps):
                c.execute('INSERT INTO quest_steps(quest_id,title,position) VALUES (%s,%s,%s)',(qid,step,pos))
            for sid in skill_ids:
                c.execute('INSERT INTO quest_skills VALUES (%s,%s)',(qid,sid))
            self._event(c,'updated' if q else 'created',f'Квест: {title}',qid)
        return qid

    def start(self,qid):
        with self.db.connect() as c:
            self._lock(c)
            q=self._quest(c,qid)
            require_state(q,'draft')
            if q['due_date'] and q['due_date'] < date.today():
                raise RuleError('Срок прошёл. Измените дату перед началом.')
            c.execute("UPDATE quests SET status='active' WHERE id=%s",(qid,))
            self._event(c,'started',f'Начат квест «{q["title"]}»',qid)

    def toggle_step(self,qid,step_id,done):
        with self.db.connect() as c:
            self._lock(c)
            q=self._quest(c,qid)
            require_state(q,'active')
            if q['due_date'] and q['due_date'] < date.today():
                raise RuleError('Срок прошёл. Обновите данные для обработки просрочки.')
            row=c.execute('UPDATE quest_steps SET done=%s WHERE id=%s AND quest_id=%s RETURNING title',(done,step_id,qid)).fetchone()
            if not row:
                raise RuleError('Шаг не найден.')
            self._event(c,'step',f'{"Выполнен" if done else "Возвращён"} шаг: {row["title"]}',qid,done=done)

    def complete(self,qid):
        with self.db.connect() as c:
            self._lock(c)
            q=self._quest(c,qid)
            require_state(q,'active')
            if q['due_date'] and q['due_date'] < date.today():
                raise RuleError('Квест просрочен. Нажмите «Обновить».')
            steps=c.execute('SELECT done FROM quest_steps WHERE quest_id=%s',(qid,)).fetchall()
            if not steps or not all(s['done'] for s in steps):
                raise RuleError('Сначала выполните все шаги квеста.')
            xp,coins=REWARDS[q['difficulty']]
            c.execute("UPDATE quests SET status='completed',finished_at=now() WHERE id=%s",(qid,))
            c.execute('UPDATE users SET xp=xp+%s,coins=coins+%s WHERE id=%s',(xp,coins,self.uid))
            c.execute('UPDATE skills SET xp=xp+%s WHERE user_id=%s AND id IN (SELECT skill_id FROM quest_skills WHERE quest_id=%s)',(xp,self.uid,qid))
            self._event(c,'completed',f'Завершён «{q["title"]}»: +{xp} XP, +{coins} монет',qid,xp=xp,coins=coins,title=q['title'])
        return xp,coins

    def _fail(self,c,q,reason):
        row=c.execute('SELECT coins FROM users WHERE id=%s',(self.uid,)).fetchone()
        penalty=min(10,row['coins'])
        c.execute('UPDATE users SET coins=coins-%s WHERE id=%s',(penalty,self.uid))
        c.execute("UPDATE quests SET status='failed',finished_at=now() WHERE id=%s",(q['id'],))
        self._event(c,'failed',f'Не выполнен «{q["title"]}»: −{penalty} монет ({reason})',q['id'],coins=-penalty,reason=reason)

    def fail(self,qid):
        with self.db.connect() as c:
            self._lock(c)
            q=self._quest(c,qid)
            require_state(q,'active')
            self._fail(c,q,'отказ от квеста')

    def expire(self):
        with self.db.connect() as c:
            self._lock(c)
            expired=c.execute("SELECT * FROM quests WHERE user_id=%s AND status='active' AND due_date < %s ORDER BY id FOR UPDATE",(self.uid,date.today())).fetchall()
            for q in expired:
                self._fail(c,q,'истёк срок')
        return len(expired)

    def delete_quest(self,qid):
        with self.db.connect() as c:
            self._lock(c)
            q=self._quest(c,qid)
            require_state(q,'draft','completed','failed')
            self._event(c,'deleted',f'Удалён квест «{q["title"]}». История и баланс сохранены.',qid,title=q['title'])
            c.execute('DELETE FROM quests WHERE id=%s',(qid,))

    def save_catalog(self, kind, title, description, cost=1, item_id=None):
        if kind not in ('skills','rewards'):
            raise RuleError('Неизвестный справочник.')
        title=validate_text(title,'Название',80 if kind=='skills' else 120)
        if len(description)>4000:
            raise RuleError('Описание: не более 4000 символов.')
        if kind=='rewards' and (not isinstance(cost,int) or not 1<=cost<=100000):
            raise RuleError('Стоимость: целое число от 1 до 100000.')
        # Identifiers are chosen only from these fixed statements, never user input.
        with self.db.connect() as c:
            self._lock(c)
            if kind=='skills':
                if item_id:
                    row=c.execute('UPDATE skills SET name=%s,description=%s WHERE id=%s AND user_id=%s RETURNING id',(title,description,item_id,self.uid)).fetchone()
                else:
                    row=c.execute('INSERT INTO skills(user_id,name,description) VALUES (%s,%s,%s) RETURNING id',(self.uid,title,description)).fetchone()
            else:
                if item_id:
                    row=c.execute('UPDATE rewards SET title=%s,description=%s,cost=%s WHERE id=%s AND user_id=%s RETURNING id',(title,description,cost,item_id,self.uid)).fetchone()
                else:
                    row=c.execute('INSERT INTO rewards(user_id,title,description,cost) VALUES (%s,%s,%s,%s) RETURNING id',(self.uid,title,description,cost)).fetchone()
            if not row:
                raise RuleError('Запись больше не существует.')
            self._event(c,'catalog',f'{"Изменён" if item_id else "Добавлен"} {"навык" if kind=="skills" else "приз"}: {title}')
            return row['id']

    def delete_catalog(self,kind,item_id):
        with self.db.connect() as c:
            self._lock(c)
            if kind=='skills':
                if c.execute('SELECT 1 FROM quest_skills WHERE skill_id=%s',(item_id,)).fetchone():
                    raise RuleError('Навык связан с квестами. Сначала удалите эти связи или квесты.')
                row=c.execute('DELETE FROM skills WHERE id=%s AND user_id=%s RETURNING name AS title',(item_id,self.uid)).fetchone()
            elif kind=='rewards':
                row=c.execute('DELETE FROM rewards WHERE id=%s AND user_id=%s RETURNING title',(item_id,self.uid)).fetchone()
            else:
                raise RuleError('Неизвестный справочник.')
            if not row:
                raise RuleError('Запись не найдена.')
            self._event(c,'catalog',f'Удалена запись: {row["title"]}')

    def redeem(self,rid):
        with self.db.connect() as c:
            user=self._lock(c)
            r=c.execute('SELECT * FROM rewards WHERE id=%s AND user_id=%s FOR UPDATE',(rid,self.uid)).fetchone()
            if not r:
                raise RuleError('Награда не найдена.')
            if user['coins'] < r['cost']:
                raise RuleError(f'Не хватает {r["cost"]-user["coins"]} монет. Выполните ещё один квест.')
            c.execute('UPDATE users SET coins=coins-%s WHERE id=%s',(r['cost'],self.uid))
            c.execute('INSERT INTO redemptions(user_id,reward_id,reward_title,cost) VALUES (%s,%s,%s,%s)',(self.uid,rid,r['title'],r['cost']))
            self._event(c,'redeemed',f'Получена награда «{r["title"]}»: −{r["cost"]} монет',cost=r['cost'],title=r['title'])
