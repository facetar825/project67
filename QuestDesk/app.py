"""QuestDesk desktop UI. Run with Python 3.12+ or use the packaged exe."""
import logging
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import date
import psycopg
from bootstrap import start_database, DATA
from db import Database
from domain import REWARDS, DIFFICULTIES, STATUSES, RuleError, level
from service import Service

BG='#F4F6FA'; WHITE='#FFFFFF'; NAV='#182339'; TEXT='#202C43'; MUTED='#6C7890'; ACCENT='#4F63E9'


def label(parent, text, size=11, color=TEXT, bold=False, bg=None, **kw):
    return tk.Label(parent,text=text,font=('Segoe UI',size,'bold' if bold else 'normal'),
                    fg=color,bg=bg or parent.cget('bg'),anchor='w',**kw)


def button(parent,text,command,primary=False):
    return tk.Button(parent,text=text,command=command,font=('Segoe UI',10,'bold'),
                     bg=ACCENT if primary else '#E9EDF7',fg=WHITE if primary else TEXT,
                     activebackground='#D6DDF4',activeforeground=TEXT,bd=0,
                     padx=16,pady=9,cursor='hand2',relief='flat')


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('QuestDesk — система квестов')
        self.geometry('1180x780'); self.minsize(980,690); self.configure(bg=BG)
        self.service=None; self.current='dashboard'; self.current_id=None; self.dialog=None
        self.protocol('WM_DELETE_WINDOW',self.destroy)
        style=ttk.Style(self); style.theme_use('clam')
        style.configure('Treeview',background=WHITE,fieldbackground=WHITE,foreground=TEXT,
                        rowheight=40,font=('Segoe UI',10),borderwidth=0)
        style.configure('Treeview.Heading',background='#E9EDF5',foreground=MUTED,
                        font=('Segoe UI',10,'bold'),padding=10,relief='flat')
        style.map('Treeview',background=[('selected','#E0E5FF')],foreground=[('selected',TEXT)])
        style.configure('TProgressbar',background=ACCENT,troughcolor='#E6EAF5',borderwidth=0)
        self.loading=label(self,'QuestDesk\nГотовим ваше пространство…',24,bold=True)
        self.loading.pack(expand=True)
        self.queue=queue.Queue()
        threading.Thread(target=self.connect,daemon=True).start()
        self.after(100,self.poll)

    def connect(self):
        try:
            db=Database(start_database()); db.initialize()
            self.queue.put(Service(db))
        except Exception as e:
            logging.exception('Startup failed'); self.queue.put(e)

    def poll(self):
        try:
            result=self.queue.get_nowait()
        except queue.Empty:
            self.after(100,self.poll); return
        if isinstance(result,Exception):
            self.loading.configure(text='Не удалось подключиться к PostgreSQL',font=('Segoe UI',18,'bold'))
            label(self,str(result),10,wraplength=840,justify='left').pack(pady=20)
            button(self,'Закрыть',self.destroy).pack(pady=20); return
        self.service=result; self.loading.destroy(); self.shell(); self.safe(lambda:self.show('dashboard'))
        self.after(60000,self.tick)

    def safe(self,fn):
        try:
            return fn()
        except RuleError as e:
            messagebox.showwarning('Проверьте действие',str(e),parent=self.dialog or self)
        except psycopg.errors.UniqueViolation:
            messagebox.showwarning('Название уже есть','Выберите другое название.',parent=self.dialog or self)
        except psycopg.Error:
            logging.exception('Database operation failed')
            messagebox.showerror('Ошибка базы данных','Не удалось сохранить или загрузить данные. Изменения операции отменены. Проверьте PostgreSQL и нажмите «Обновить». Подробности в app.log.',parent=self.dialog or self)
        except Exception:
            logging.exception('Unexpected error')
            messagebox.showerror('Ошибка','Операция не выполнена. Подробности в app.log.',parent=self.dialog or self)

    def shell(self):
        nav=tk.Frame(self,bg=NAV,width=218); nav.pack(side='left',fill='y'); nav.pack_propagate(False)
        label(nav,'Q / QuestDesk',17,WHITE,True).pack(anchor='w',padx=22,pady=(32,6))
        label(nav,'Маленькие шаги.\nБольшие результаты.',10,'#9CAAC2',justify='left').pack(anchor='w',padx=24,pady=(0,35))
        self.nav_buttons={}
        for key,title in [('dashboard','Обзор'),('quests','Мои квесты'),('skills','Навыки'),('rewards','Награды'),('history','История')]:
            b=tk.Button(nav,text=title,anchor='w',font=('Segoe UI',12),bg=NAV,fg='#B8C3D9',
                        activebackground='#2B3B59',activeforeground=WHITE,relief='flat',bd=0,padx=24,pady=14,
                        cursor='hand2',command=lambda k=key:self.safe(lambda:self.show(k)))
            b.pack(fill='x',padx=10,pady=3); self.nav_buttons[key]=b
        label(nav,'ПРОЕКТНАЯ РАБОТА № 2\nЛичное пространство',9,'#8394B3',justify='left').pack(side='bottom',anchor='w',padx=24,pady=25)
        right=tk.Frame(self,bg=BG); right.pack(side='left',fill='both',expand=True)
        top=tk.Frame(right,bg=WHITE,height=64); top.pack(fill='x'); top.pack_propagate(False)
        self.profile_label=label(top,'',11,bold=True); self.profile_label.pack(side='left',padx=28)
        button(top,'Обновить',lambda:self.safe(self.refresh)).pack(side='right',padx=20,pady=10)
        button(top,'Имя профиля',self.rename).pack(side='right',pady=10)
        self.notice=label(right,'',10,color='#3A6192'); self.notice.pack(fill='x',padx=28,pady=(12,0))
        # All pages scroll vertically, including long quest details.
        outer=tk.Frame(right,bg=BG); outer.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(outer,bg=BG,highlightthickness=0)
        scrollbar=ttk.Scrollbar(outer,orient='vertical',command=self.canvas.yview)
        scrollbar.pack(side='right',fill='y'); self.canvas.pack(side='left',fill='both',expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.body=tk.Frame(self.canvas,bg=BG)
        window=self.canvas.create_window((0,0),window=self.body,anchor='nw')
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(window,width=e.width))
        self.body.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.bind_all('<MouseWheel>',self.wheel,add='+')

    def wheel(self,e):
        if self.dialog is None and not isinstance(e.widget,(ttk.Treeview,tk.Text,tk.Listbox)):
            self.canvas.yview_scroll(int(-e.delta/120),'units')

    def tick(self):
        if self.dialog is None:
            self.safe(self.refresh)
        self.after(60000,self.tick)

    def refresh(self):
        self.show(self.current,self.current_id)

    def show(self,page,qid=None):
        expired=self.service.expire()
        self.current,self.current_id=page,qid
        p=self.service.profile()
        self.profile_label.configure(text=f'{p["name"]}    •    Уровень {level(p["xp"])}    •    {p["coins"]} монет')
        if expired:
            self.notice.configure(text=f'Обработано просроченных квестов: {expired}. Подробности в истории.')
        for k,b in self.nav_buttons.items():
            active=(page==k or page=='detail' and k=='quests')
            b.configure(bg='#2D3D5B' if active else NAV,fg=WHITE if active else '#B8C3D9')
        for child in self.body.winfo_children(): child.destroy()
        self.canvas.yview_moveto(0)
        if page=='detail': self.detail(qid)
        else: getattr(self,page)()
        self.after_idle(lambda:self.canvas.yview_moveto(0))

    def heading(self,title,subtitle):
        frame=tk.Frame(self.body,bg=BG); frame.pack(fill='x',padx=28,pady=(18,22))
        label(frame,title,27,bold=True).pack(anchor='w')
        label(frame,subtitle,11,MUTED,wraplength=730,justify='left').pack(anchor='w',pady=(8,0))
        return frame

    def card(self,parent=None):
        f=tk.Frame(parent or self.body,bg=WHITE,highlightbackground='#E2E7F0',highlightthickness=1,padx=20,pady=18)
        f.pack(fill='x',padx=28,pady=(0,16)); return f

    def action(self,fn,page=None,qid=None,notice='Готово. Данные сохранены.'):
        def perform():
            fn(); self.notice.configure(text=notice)
            self.show(page or self.current,qid if page else self.current_id)
        self.safe(perform)

    def dashboard(self):
        p=self.service.profile(); quests=self.service.quests()
        self.heading('Каждый шаг имеет значение','Выберите квест, выполните шаги и превратите свои планы в результат.')
        stats=tk.Frame(self.body,bg=BG); stats.pack(fill='x',padx=28,pady=(0,18))
        values=[('УРОВЕНЬ',str(level(p['xp']))),('ОПЫТ',f'{p["xp"]} XP'),('МОНЕТЫ',str(p['coins'])),('В РАБОТЕ',str(sum(q['status']=='active' for q in quests)))]
        for i,(title,value) in enumerate(values):
            stats.columnconfigure(i,weight=1)
            cell=tk.Frame(stats,bg=WHITE,padx=18,pady=18,highlightbackground='#E2E7F0',highlightthickness=1)
            cell.grid(row=0,column=i,sticky='nsew',padx=(0,12 if i<3 else 0))
            label(cell,title,9,MUTED,True).pack(anchor='w')
            label(cell,value,25,bold=True).pack(anchor='w',pady=(8,0))
        f=self.card(); label(f,'До следующего уровня',12,bold=True).pack(anchor='w')
        ttk.Progressbar(f,maximum=200,value=p['xp']%200).pack(fill='x',pady=12)
        label(f,f'{p["xp"]%200} из 200 XP  •  Каждый выбранный навык получает полный опыт квеста',10,MUTED).pack(anchor='w')
        active=[q for q in quests if q['status'] in ('active','draft')]
        f=self.card(); label(f,'Следующий шаг',15,bold=True).pack(anchor='w')
        if active:
            q=active[0]; xp,coins=REWARDS[q['difficulty']]
            label(f,q['title'],17,bold=True,wraplength=700).pack(anchor='w',pady=(14,8))
            label(f,f'{DIFFICULTIES[q["difficulty"]]}  •  +{xp} XP  •  +{coins} монет  •  {q["done_steps"]}/{q["total_steps"]} шагов',11,MUTED).pack(anchor='w')
            button(f,'Открыть квест →',lambda:self.safe(lambda:self.show('detail',q['id'])),True).pack(anchor='w',pady=(18,0))
        else:
            label(f,'Все планы выполнены. Самое время выбрать новую цель.',11,MUTED).pack(anchor='w',pady=12)
            button(f,'Создать квест',self.quest_form,True).pack(anchor='w')
        f=self.card(); label(f,'Последние события',14,bold=True).pack(anchor='w',pady=(0,8))
        for event in self.service.history()[:3]:
            label(f,'•  '+event['message'],10,MUTED,wraplength=720,justify='left').pack(anchor='w',pady=5)

    def make_tree(self,parent,columns,height=8):
        wrapper=tk.Frame(parent,bg=WHITE); wrapper.pack(fill='both',expand=True)
        tree=ttk.Treeview(wrapper,columns=[c[0] for c in columns],show='headings',height=height,selectmode='browse')
        for key,title,width in columns:
            tree.heading(key,text=title); tree.column(key,width=width,minwidth=50,anchor='w')
        scroll=ttk.Scrollbar(wrapper,orient='vertical',command=tree.yview)
        tree.configure(yscrollcommand=scroll.set); scroll.pack(side='right',fill='y'); tree.pack(fill='both',expand=True)
        return tree

    def selected(self,tree):
        values=tree.selection()
        if not values: raise RuleError('Сначала выберите запись в списке.')
        return int(values[0])

    def quests(self):
        self.heading('Мои квесты','От небольшого плана до завершённой цели. Двойной щелчок открывает квест.')
        tools=tk.Frame(self.body,bg=BG); tools.pack(fill='x',padx=28,pady=(0,16))
        search=ttk.Entry(tools,font=('Segoe UI',11),width=25); search.pack(side='left',ipady=7)
        search.insert(0,getattr(self,'search_text',''))
        options=['Все состояния']+list(STATUSES.values())
        status=ttk.Combobox(tools,values=options,state='readonly',width=18,font=('Segoe UI',10))
        status.set(getattr(self,'status_text','Все состояния')); status.pack(side='left',padx=12,ipady=6)
        def filter_rows(*_):
            self.search_text=search.get(); self.status_text=status.get()
            key=next((k for k,v in STATUSES.items() if v==status.get()),None)
            rows=self.service.quests(search.get(),key)
            tree.delete(*tree.get_children())
            for q in rows:
                tree.insert('', 'end', iid=q['id'],values=(q['title'],STATUSES[q['status']],f'{q["done_steps"]}/{q["total_steps"]}',q['due_date'] or 'Без срока'))
            count.configure(text=f'Найдено квестов: {len(rows)}')
        button(tools,'Найти',lambda:self.safe(filter_rows)).pack(side='left')
        button(tools,'+ Новый квест',self.quest_form,True).pack(side='right')
        f=self.card(); tree=self.make_tree(f,[('title','Название',330),('status','Состояние',150),('steps','Шаги',65),('due','Срок',110)])
        count=label(f,'',10,MUTED); count.pack(anchor='w',pady=12)
        button(f,'Открыть выбранный',lambda:self.safe(lambda:self.show('detail',self.selected(tree)))).pack(anchor='w')
        tree.bind('<Double-1>',lambda e:self.safe(lambda:self.show('detail',self.selected(tree))))
        search.bind('<Return>',lambda e:self.safe(filter_rows)); status.bind('<<ComboboxSelected>>',lambda e:self.safe(filter_rows)); filter_rows()

    def detail(self,qid):
        q=self.service.detail(qid); xp,coins=REWARDS[q['difficulty']]
        self.heading(q['title'],f'{STATUSES[q["status"]]}  •  {DIFFICULTIES[q["difficulty"]]}  •  Срок: {q["due_date"] or "не задан"}')
        f=self.card()
        label(f,q['description'] or 'Описание не добавлено.',11,wraplength=710,justify='left').pack(anchor='w')
        label(f,f'Награда: +{xp} XP и +{coins} монет',13,ACCENT,True).pack(anchor='w',pady=(16,8))
        label(f,'Навыки: '+(', '.join(s['name'] for s in q['skills']) or 'не выбраны'),10,MUTED,wraplength=710).pack(anchor='w')
        f=self.card(); label(f,'Шаги квеста',16,bold=True).pack(anchor='w',pady=(0,12))
        for step in q['steps']:
            var=tk.BooleanVar(value=step['done'])
            check=tk.Checkbutton(f,text=step['title'],variable=var,bg=WHITE,fg=TEXT,
                                activebackground=WHITE,font=('Segoe UI',11),anchor='w',wraplength=660,
                                state='normal' if q['status']=='active' else 'disabled',
                                command=lambda sid=step['id'],v=var:self.step_action(qid,sid,v))
            check.pack(fill='x',pady=7)
        row=tk.Frame(f,bg=WHITE); row.pack(fill='x',pady=(20,0))
        if q['status']=='draft':
            button(row,'Начать квест',lambda:self.action(lambda:self.service.start(qid)),True).pack(side='left',padx=(0,10))
            button(row,'Редактировать',lambda:self.quest_form(q)).pack(side='left')
        elif q['status']=='active':
            button(row,'Завершить и получить награду',lambda:self.action(lambda:self.service.complete(qid),notice=f'Квест завершён! +{xp} XP и +{coins} монет.'),True).pack(side='left',padx=(0,10))
            button(row,'Отказаться',lambda:self.confirm('Отказ от квеста','Квест станет невыполненным. Штраф — до 10 монет.',lambda:self.service.fail(qid))).pack(side='left')
        else:
            label(row,'Результат сохранён в истории.',11,MUTED).pack(side='left')
        bottom=tk.Frame(self.body,bg=BG); bottom.pack(fill='x',padx=28,pady=(0,20))
        button(bottom,'← К списку',lambda:self.safe(lambda:self.show('quests'))).pack(side='left')
        if q['status']!='active':
            button(bottom,'Удалить квест',lambda:self.confirm('Удалить квест?','Шаги и связи будут удалены. История, опыт и баланс сохранятся.',lambda:self.service.delete_quest(qid),'quests')).pack(side='right')

    def step_action(self,qid,sid,var):
        intended=var.get()
        try:
            self.service.toggle_step(qid,sid,intended)
        except Exception as e:
            var.set(not intended)
            self.safe(lambda:(_ for _ in ()).throw(e))

    def confirm(self,title,text,fn,page=None):
        if messagebox.askyesno(title,text,parent=self): self.action(fn,page)

    def rename(self):
        value=simpledialog.askstring('Профиль','Как к вам обращаться?',initialvalue=self.service.profile()['name'],parent=self)
        if value is not None: self.action(lambda:self.service.rename(value))

    def new_dialog(self,title,geometry='640x700'):
        d=tk.Toplevel(self); d.title(title); d.geometry(geometry); d.configure(bg=WHITE)
        d.transient(self); d.grab_set(); self.dialog=d
        def close():
            self.dialog=None; d.destroy()
        d.protocol('WM_DELETE_WINDOW',close)
        return d,close

    def field(self,parent,title,value='',width=50):
        label(parent,title,10,MUTED).pack(anchor='w',pady=(12,5))
        e=ttk.Entry(parent,font=('Segoe UI',11),width=width); e.pack(fill='x',ipady=5); e.insert(0,value)
        return e

    def quest_form(self,q=None):
        self.safe(lambda:self._quest_form(q))

    def _quest_form(self,q):
        skills=self.service.skills()
        d,close=self.new_dialog('Редактирование квеста' if q else 'Новый квест','650x790')
        box=tk.Frame(d,bg=WHITE,padx=24,pady=10); box.pack(fill='both',expand=True)
        title=self.field(box,'Название',q['title'] if q else '')
        label(box,'Описание',10,MUTED).pack(anchor='w',pady=(12,5))
        desc=tk.Text(box,height=3,font=('Segoe UI',11),wrap='word',bd=1,relief='solid'); desc.pack(fill='x')
        desc.insert('1.0',q['description'] if q else '')
        label(box,'Сложность (опыт / монеты)',10,MUTED).pack(anchor='w',pady=(12,5))
        difficulty=ttk.Combobox(box,state='readonly',values=[f'{v} — {REWARDS[k][0]} XP / {REWARDS[k][1]}' for k,v in DIFFICULTIES.items()],font=('Segoe UI',11))
        difficulty.pack(fill='x',ipady=5); difficulty.current(list(DIFFICULTIES).index(q['difficulty']) if q else 1)
        due=self.field(box,'Срок: ГГГГ-ММ-ДД (можно оставить пустым)',str(q['due_date']) if q and q['due_date'] else '')
        label(box,'Шаги: по одному на строку (от 1 до 20)',10,MUTED).pack(anchor='w',pady=(12,5))
        steps=tk.Text(box,height=5,font=('Segoe UI',11),wrap='word',bd=1,relief='solid'); steps.pack(fill='x')
        steps.insert('1.0','\n'.join(s['title'] for s in q['steps']) if q else '')
        label(box,'Развиваемые навыки: нажмите, чтобы выбрать несколько',10,MUTED).pack(anchor='w',pady=(12,5))
        skills_list=tk.Listbox(box,selectmode='multiple',exportselection=False,height=4,font=('Segoe UI',11),bd=1,relief='solid')
        skills_list.pack(fill='x')
        chosen={s['id'] for s in q['skills']} if q else set()
        for i,s in enumerate(skills):
            skills_list.insert('end',s['name'])
            if s['id'] in chosen: skills_list.selection_set(i)
        def save():
            try: due_date=date.fromisoformat(due.get().strip()) if due.get().strip() else None
            except ValueError: raise RuleError('Введите реальную дату в формате ГГГГ-ММ-ДД.')
            qid=self.service.save_quest(title.get(),desc.get('1.0','end-1c'),list(DIFFICULTIES)[difficulty.current()],due_date,
                steps.get('1.0','end-1c').splitlines(),[skills[i]['id'] for i in skills_list.curselection()],q['id'] if q else None)
            close(); self.notice.configure(text='Квест сохранён. Можно приступать!'); self.show('detail',qid)
        buttons=tk.Frame(box,bg=WHITE); buttons.pack(fill='x',pady=18)
        button(buttons,'Сохранить квест',lambda:self.safe(save),True).pack(side='left')
        button(buttons,'Отмена',close).pack(side='right'); title.focus_set()

    def skills(self): self.catalog('skills')
    def rewards(self): self.catalog('rewards')

    def catalog(self,kind):
        is_skill=kind=='skills'
        self.heading('Навыки' if is_skill else 'Награды',
                     'Опыт растёт вместе с выполненными квестами. Новый уровень — каждые 200 XP.' if is_skill else 'Обменивайте заработанные монеты на приятный отдых и полезные покупки.')
        tools=tk.Frame(self.body,bg=BG); tools.pack(fill='x',padx=28,pady=(0,16))
        button(tools,'+ Добавить',lambda:self.catalog_form(kind),True).pack(side='left')
        rows=self.service.skills() if is_skill else self.service.rewards()
        for r in rows:
            f=self.card()
            label(f,r['name'] if is_skill else r['title'],16,bold=True,wraplength=700).pack(anchor='w')
            label(f,r['description'] or 'Без описания',11,MUTED,wraplength=700,justify='left').pack(anchor='w',pady=8)
            if is_skill:
                label(f,f'Уровень {level(r["xp"])}  •  {r["xp"]} XP',11,ACCENT,True).pack(anchor='w')
                ttk.Progressbar(f,maximum=200,value=r['xp']%200).pack(fill='x',pady=10)
            else: label(f,f'{r["cost"]} монет',13,ACCENT,True).pack(anchor='w')
            row=tk.Frame(f,bg=WHITE); row.pack(fill='x',pady=(12,0))
            if not is_skill:
                button(row,'Получить награду',lambda x=r:self.confirm('Получить награду?',f'«{x["title"]}» стоит {x["cost"]} монет. Списать монеты?',lambda:self.service.redeem(x['id'])),True).pack(side='left',padx=(0,10))
            button(row,'Изменить',lambda x=r:self.catalog_form(kind,x)).pack(side='left',padx=(0,10))
            button(row,'Удалить',lambda x=r:self.confirm('Удалить запись?','Запись будет удалена. История операций сохранится.',lambda:self.service.delete_catalog(kind,x['id']))).pack(side='left')
        if not rows:
            label(self.card(),'Пока пусто. Добавьте первую запись.',12,MUTED).pack(anchor='w')

    def catalog_form(self,kind,item=None):
        d,close=self.new_dialog('Навык' if kind=='skills' else 'Награда','560x430')
        box=tk.Frame(d,bg=WHITE,padx=24,pady=12); box.pack(fill='both',expand=True)
        title=self.field(box,'Название',(item.get('name') or item.get('title')) if item else '')
        label(box,'Описание',10,MUTED).pack(anchor='w',pady=(12,5))
        desc=tk.Text(box,height=5,font=('Segoe UI',11),wrap='word',bd=1,relief='solid'); desc.pack(fill='x')
        desc.insert('1.0',item['description'] if item else '')
        cost=self.field(box,'Стоимость в монетах',str(item['cost']) if item else '30') if kind=='rewards' else None
        def save():
            try: price=int(cost.get()) if cost else 1
            except ValueError: raise RuleError('Стоимость должна быть целым числом.')
            self.service.save_catalog(kind,title.get(),desc.get('1.0','end-1c'),price,item['id'] if item else None)
            close(); self.show(kind)
        row=tk.Frame(box,bg=WHITE); row.pack(fill='x',pady=20)
        button(row,'Сохранить',lambda:self.safe(save),True).pack(side='left')
        button(row,'Отмена',close).pack(side='right'); title.focus_set()

    def history(self):
        self.heading('История действий','Последние 200 событий. Начисления и списания записываются вместе с изменением баланса.')
        f=self.card(); tree=self.make_tree(f,[('time','Дата и время',145),('message','Событие',590)],height=11)
        events=self.service.history()
        for e in events:
            tree.insert('','end',iid=e['id'],values=(e['created_at'].astimezone().strftime('%d.%m.%Y %H:%M'),e['message']))
        label(f,'Двойной щелчок — полный текст события',10,MUTED).pack(anchor='w',pady=(12,0))
        def event_detail(_):
            item=next(e for e in events if e['id']==self.selected(tree))
            messagebox.showinfo('Событие',item['message'],parent=self)
        tree.bind('<Double-1>',lambda e:self.safe(lambda:event_detail(e)))
        f=self.card(); label(f,'Полученные награды',14,bold=True).pack(anchor='w',pady=(0,10))
        purchases=self.service.purchases()
        for r in purchases[:10]:
            label(f,f'{r["created_at"].astimezone():%d.%m.%Y}  •  {r["reward_title"]}  •  {r["cost"]} монет',11,wraplength=700).pack(anchor='w',pady=5)
        if not purchases: label(f,'Здесь появится первая полученная награда.',11,MUTED).pack(anchor='w')


if __name__=='__main__':
    DATA.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=DATA/'app.log',level=logging.INFO,encoding='utf-8',format='%(asctime)s %(levelname)s %(message)s')
    App().mainloop()
