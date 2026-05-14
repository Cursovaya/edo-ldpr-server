#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ЭДО ЛДПР - Десктопное приложение с облачной БД (Render)
PyQt6 + Flask + PostgreSQL (Render) + PyInstaller
"""

import os
import sys
import json
import uuid
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

# Flask
from flask import (
    Flask, render_template_string, request, redirect, url_for,
    session, flash, jsonify, g
)
from werkzeug.security import generate_password_hash, check_password_hash
from jinja2 import DictLoader

# PostgreSQL
import psycopg2
import psycopg2.extras

# ⚠️ НЕ импортируем PyQt6 здесь! Только локально нужен!
# from PyQt6.QtWidgets import (  ← УДАЛИТЕ ЭТИ СТРОКИ

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

app_flask = Flask(__name__)
app_flask.secret_key = os.environ.get('FLASK_SECRET', 'edo-ldpr-local-secret-key-2024')
app_flask.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

# 🔑 ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ для Render
DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://user:password@localhost:5432/edo_ldpr'
)

# Попытка подключения с повторами
MAX_RETRIES = 5
RETRY_DELAY = 2

# ============================================================
# БАЗА ДАННЫХ (PostgreSQL)
# ============================================================

def get_db():
    if 'db' not in g:
        try:
            g.db = psycopg2.connect(
                DATABASE_URL, 
                cursor_factory=psycopg2.extras.RealDictCursor,
                connect_timeout=10
            )
            g.db.autocommit = False
        except psycopg2.OperationalError as e:
            raise Exception(f"Ошибка подключения к БД: {str(e)}")
    return g.db

@app_flask.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass

def db_q(sql, params=None, one=False, many=False, commit=False):
    sql = sql.replace('?', '%s')
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(sql, params or [])
        result = None
        if one:
            result = cur.fetchone()
        elif many:
            result = cur.fetchall()
        if commit:
            db.commit()
        cur.close()
        return result
    except Exception as e:
        db.rollback()
        raise e

def init_db():
    """Инициализация базы данных"""
    db = get_db()
    cur = db.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            uid TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'executor',
            department_id TEXT,
            avatar_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            head_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT,
            priority TEXT DEFAULT 'Нормальный',
            status TEXT DEFAULT 'Черновик',
            created_by TEXT NOT NULL,
            creator_name TEXT,
            assigned_department_id TEXT,
            assigned_executor_id TEXT,
            deadline TEXT,
            result TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_history (
            id SERIAL PRIMARY KEY,
            order_id TEXT NOT NULL,
            action TEXT NOT NULL,
            user_name TEXT,
            user_role TEXT,
            details TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    db.commit()
    cur.close()
    print("✓ База данных инициализирована")

def seed_database():
    """Заполнение начальных данных"""
    row = db_q("SELECT COUNT(*) as cnt FROM users", one=True)
    if row and row['cnt'] > 0:
        print("✓ База данных уже содержит пользователей")
        return
    
    print("📝 Заполнение начальных данных...")
    
    depts = [
        ('dept-1', 'Центральный аппарат', None),
        ('dept-2', 'Юридический отдел', None),
        ('dept-3', 'Организационный отдел', None),
        ('dept-4', 'Информационный отдел', None),
        ('dept-5', 'Отдел регионального развития', None),
    ]
    for d in depts:
        db_q("INSERT INTO departments (id, name, head_id) VALUES (%s,%s,%s)", d, commit=False)
    get_db().commit()
    
    users_data = [
        ('u-admin', 'Администратор Системы', 'admin@ldpr.ru', 'admin', 'admin123', 'admin', None),
        ('u-sec', 'Главный Секретарь', 'sec@ldpr.ru', 'secretary', 'sec123', 'secretary', None),
        ('u-head-c', 'Руководитель ЦА', 'headca@ldpr.ru', 'head_central', 'head123', 'head_central', 'dept-1'),
        ('u-head-d', 'Начальник Юридического Отдела', 'headlaw@ldpr.ru', 'head_department', 'head123', 'head_department', 'dept-2'),
        ('u-ast', 'Помощник Депутата', 'ast@ldpr.ru', 'assistant', 'ast123', 'assistant', None),
        ('u-exec', 'Рядовой Исполнитель', 'exec@ldpr.ru', 'executor', 'exec123', 'executor', 'dept-2'),
        ('u-exec2', 'Специалист ИТ', 'it@ldpr.ru', 'executor2', 'exec123', 'executor', 'dept-4'),
    ]
    for uid, full_name, email, username, plain_pwd, role, dept_id in users_data:
        hashed = generate_password_hash(plain_pwd)
        db_q("""INSERT INTO users (uid,full_name,email,username,password,role,department_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
             (uid, full_name, email, username, hashed, role, dept_id), commit=False)
    get_db().commit()
    
    db_q("UPDATE departments SET head_id=%s WHERE id=%s", ('u-head-c', 'dept-1'), commit=False)
    db_q("UPDATE departments SET head_id=%s WHERE id=%s", ('u-head-d', 'dept-2'), commit=True)
    
    print("✓ Начальные данные загружены")

# ============================================================
# МОДЕЛИ
# ============================================================

class UserModel:
    @staticmethod
    def get_by_id(uid):
        row = db_q("SELECT * FROM users WHERE uid=%s", (uid,), one=True)
        return dict(row) if row else None
    
    @staticmethod
    def get_by_username(username):
        row = db_q("SELECT * FROM users WHERE username=%s", (username,), one=True)
        return dict(row) if row else None
    
    @staticmethod
    def get_all():
        rows = db_q("SELECT * FROM users ORDER BY full_name", many=True)
        return [dict(r) for r in rows] if rows else []
    
    @staticmethod
    def get_by_department(dept_id):
        rows = db_q("SELECT * FROM users WHERE department_id=%s", (dept_id,), many=True)
        return [dict(r) for r in rows] if rows else []
    
    @staticmethod
    def create(uid, full_name, email, username, password, role='executor', department_id=None):
        try:
            db_q("""INSERT INTO users (uid,full_name,email,username,password,role,department_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                 (uid, full_name, email, username, password, role, department_id), commit=True)
            return True, None
        except psycopg2.IntegrityError as e:
            get_db().rollback()
            if 'username' in str(e):
                return False, 'Пользователь с таким логином уже существует'
            elif 'email' in str(e):
                return False, 'Пользователь с таким email уже существует'
            return False, 'Ошибка при создании'
    
    @staticmethod
    def update(uid, **kwargs):
        allowed = ['full_name', 'email', 'username', 'role', 'department_id', 'avatar_url']
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        sets = ', '.join(f"{k}=%s" for k in updates)
        vals = list(updates.values()) + [uid]
        db_q(f"UPDATE users SET {sets} WHERE uid=%s", vals, commit=True)
    
    @staticmethod
    def delete(uid):
        db_q("DELETE FROM users WHERE uid=%s", (uid,), commit=True)

class DepartmentModel:
    @staticmethod
    def get_all():
        rows = db_q("SELECT * FROM departments ORDER BY name", many=True)
        return [dict(r) for r in rows] if rows else []
    
    @staticmethod
    def get_by_id(dept_id):
        row = db_q("SELECT * FROM departments WHERE id=%s", (dept_id,), one=True)
        return dict(row) if row else None
    
    @staticmethod
    def create(dept_id, name, head_id=None):
        try:
            db_q("INSERT INTO departments (id,name,head_id) VALUES (%s,%s,%s)",
                 (dept_id, name, head_id), commit=True)
            return True
        except psycopg2.IntegrityError:
            get_db().rollback()
            return False
    
    @staticmethod
    def delete(dept_id):
        db_q("DELETE FROM departments WHERE id=%s", (dept_id,), commit=True)

class OrderModel:
    STATUSES = ['Черновик', 'На утверждении', 'Утверждено', 'В отделе',
                'Назначен исполнитель', 'В работе', 'Готово к проверке',
                'Подтверждено', 'На доработке', 'Закрыто', 'Отклонено']
    PRIORITIES = ['Низкий', 'Нормальный', 'Высокий', 'Срочный']
    
    @staticmethod
    def get_all():
        rows = db_q("SELECT * FROM orders ORDER BY created_at DESC", many=True)
        return [dict(r) for r in rows] if rows else []
    
    @staticmethod
    def get_by_id(order_id):
        row = db_q("SELECT * FROM orders WHERE id=%s", (order_id,), one=True)
        if row:
            row = dict(row)
            if row.get('result'):
                try:
                    row['result'] = json.loads(row['result'])
                except Exception:
                    pass
        return row
    
    @staticmethod
    def get_by_department(dept_id):
        rows = db_q("SELECT * FROM orders WHERE assigned_department_id=%s ORDER BY created_at DESC",
                    (dept_id,), many=True)
        return [dict(r) for r in rows] if rows else []
    
    @staticmethod
    def create(order_id, title, content, priority, status, created_by, creator_name, deadline=None, assigned_department_id=None):
        db_q("""INSERT INTO orders (id,title,content,priority,status,created_by,creator_name,deadline,assigned_department_id,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
             (order_id, title, content, priority, status, created_by, creator_name, deadline, assigned_department_id, datetime.now().isoformat()),
             commit=True)
    
    @staticmethod
    def update(order_id, **kwargs):
        if 'result' in kwargs and kwargs['result'] and isinstance(kwargs['result'], dict):
            kwargs['result'] = json.dumps(kwargs['result'], ensure_ascii=False)
        allowed = ['title', 'content', 'priority', 'status', 'assigned_department_id',
                   'assigned_executor_id', 'deadline', 'result']
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return
        updates['updated_at'] = datetime.now().isoformat()
        sets = ', '.join(f"{k}=%s" for k in updates)
        vals = list(updates.values()) + [order_id]
        db_q(f"UPDATE orders SET {sets} WHERE id=%s", vals, commit=True)
    
    @staticmethod
    def get_by_user(uid, role, department_id=None):
        if role == 'admin':
            return OrderModel.get_all()
        elif role == 'assistant':
            rows = db_q("SELECT * FROM orders WHERE created_by=%s ORDER BY created_at DESC", (uid,), many=True)
            return [dict(r) for r in rows] if rows else []
        elif role == 'head_central':
            return OrderModel.get_all()
        elif role == 'head_department' and department_id:
            rows = db_q("SELECT * FROM orders WHERE assigned_department_id=%s ORDER BY created_at DESC", (department_id,), many=True)
            return [dict(r) for r in rows] if rows else []
        elif role == 'executor':
            rows = db_q("SELECT * FROM orders WHERE assigned_executor_id=%s ORDER BY created_at DESC", (uid,), many=True)
            return [dict(r) for r in rows] if rows else []
        elif role == 'secretary':
            rows = db_q("""SELECT * FROM orders WHERE status IN (%s,%s,%s,%s,%s,%s,%s,%s)
                ORDER BY created_at DESC""", 
                ('Утверждено','В отделе','Назначен исполнитель','В работе','Готово к проверке','На доработке','Подтверждено','Закрыто'),
                many=True)
            return [dict(r) for r in rows] if rows else []
        return OrderModel.get_all()
    
    @staticmethod
    def get_stats(uid=None, role=None, department_id=None):
        orders = OrderModel.get_by_user(uid, role, department_id) if uid else OrderModel.get_all()
        return {
            'total': len(orders),
            'pending': sum(1 for o in orders if o['status'] == 'На утверждении'),
            'approved': sum(1 for o in orders if o['status'] in ['Утверждено', 'Закрыто', 'Подтверждено']),
            'in_work': sum(1 for o in orders if o['status'] == 'В работе'),
        }

class OrderHistoryModel:
    @staticmethod
    def get_by_order(order_id):
        rows = db_q("SELECT * FROM order_history WHERE order_id=%s ORDER BY created_at DESC",
                    (order_id,), many=True)
        return [dict(r) for r in rows] if rows else []
    
    @staticmethod
    def add(order_id, action, user_name, user_role, details=None):
        db_q("INSERT INTO order_history (order_id,action,user_name,user_role,details) VALUES (%s,%s,%s,%s,%s)",
             (order_id, action, user_name, user_role, details), commit=True)

# ============================================================
# ДЕКОРАТОРЫ
# ============================================================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Войдите в систему', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('user_role') not in roles:
                flash('Недостаточно прав', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator

@app_flask.context_processor
def inject_user():
    if 'user_id' in session:
        user = UserModel.get_by_id(session['user_id'])
        if user:
            return {'current_user': user}
    return {'current_user': None}

# ============================================================
# ШАБЛОНЫ (сокращено для размера, используем те же как раньше)
# ============================================================

BASE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{% block title %}ЭДО ЛДПР{% endblock %}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">
<style>
:root {
  --blue: #003399;
  --blue-dark: #001f66;
  --blue-mid: #0044cc;
  --gold: #FFD700;
  --sidebar-w: 240px;
}
* { box-sizing: border-box; }
body { margin: 0; background: #eef1f7; font-family: 'Segoe UI', system-ui, sans-serif; color: #1a1a2e; }
.top-nav {
  position: fixed; top: 0; left: 0; right: 0; z-index: 1000;
  height: 56px;
  background: linear-gradient(90deg, var(--blue-dark) 0%, var(--blue) 60%, var(--blue-mid) 100%);
  display: flex; align-items: center; padding: 0 20px;
  box-shadow: 0 2px 16px rgba(0,0,0,.35);
  gap: 16px;
}
.top-nav .brand { display: flex; align-items: center; gap: 10px; color: var(--gold); font-weight: 900; font-size: 1.1rem; letter-spacing: 1px; text-decoration: none; }
.top-nav .brand .bar { width: 3px; height: 22px; background: var(--gold); border-radius: 2px; }
.top-nav .spacer { flex: 1; }
.top-nav .user-pill { display: flex; align-items: center; gap: 10px; background: rgba(255,255,255,.1); border-radius: 30px; padding: 5px 14px 5px 5px; color: #fff; }
.top-nav .user-avatar { width: 32px; height: 32px; border-radius: 50%; background: var(--gold); color: var(--blue); font-weight: 800; display: flex; align-items: center; justify-content: center; font-size: .85rem; flex-shrink: 0; }
.top-nav .user-name { font-size: .85rem; font-weight: 600; max-width: 160px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.top-nav .user-role-badge { font-size: .65rem; background: rgba(255,215,0,.2); color: var(--gold); border-radius: 20px; padding: 2px 8px; }
.top-nav .logout-btn { color: rgba(255,255,255,.7); border: none; background: none; cursor: pointer; font-size: 1rem; padding: 4px 8px; border-radius: 6px; transition: .2s; }
.top-nav .logout-btn:hover { color: #fff; background: rgba(255,255,255,.15); }
.sidebar {
  position: fixed; top: 56px; left: 0; bottom: 0; width: var(--sidebar-w);
  background: #fff;
  border-right: 1px solid #e5e8f0;
  overflow-y: auto; z-index: 900;
  display: flex; flex-direction: column;
  padding: 16px 0;
}
.sidebar .nav-section-label { font-size: .6rem; font-weight: 800; text-transform: uppercase; letter-spacing: .1em; color: #aab; padding: 12px 20px 4px; }
.sidebar .nav-item { padding: 0 10px; margin-bottom: 2px; }
.sidebar .nav-link {
  display: flex; align-items: center; gap: 10px;
  color: #555; border-radius: 10px; padding: 9px 14px;
  font-weight: 500; font-size: .88rem; text-decoration: none; transition: .15s;
}
.sidebar .nav-link:hover { background: #eef2ff; color: var(--blue); }
.sidebar .nav-link.active { background: var(--blue); color: #fff !important; }
.sidebar-footer { margin-top: auto; padding: 16px 20px; font-size: .72rem; color: #aab; border-top: 1px solid #f0f0f0; }
.main-content { margin-left: var(--sidebar-w); margin-top: 56px; padding: 28px 32px; min-height: calc(100vh - 56px); }
.page-header { margin-bottom: 24px; }
.page-header h2 { font-weight: 800; font-size: 1.5rem; color: #111; margin: 0; }
.page-header p { color: #888; font-size: .85rem; margin: 4px 0 0; }
.card { border: none; border-radius: 16px; box-shadow: 0 2px 12px rgba(0,0,0,.06); background: #fff; }
.card-body { padding: 24px; }
.stat-card { border-radius: 16px; padding: 20px 24px; position: relative; overflow: hidden; }
.stat-card.blue { background: linear-gradient(135deg,#e8eeff,#dbe4ff); border-left: 4px solid var(--blue); }
.stat-card.amber { background: linear-gradient(135deg,#fffbeb,#fef3c7); border-left: 4px solid #f59e0b; }
.stat-card.green { background: linear-gradient(135deg,#f0fdf4,#dcfce7); border-left: 4px solid #22c55e; }
.stat-card.purple { background: linear-gradient(135deg,#faf5ff,#ede9fe); border-left: 4px solid #8b5cf6; }
.stat-card .stat-label { font-size: .68rem; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: #888; }
.stat-card .stat-value { font-size: 2rem; font-weight: 900; line-height: 1; margin: 6px 0 4px; color: #111; }
.table { font-size: .86rem; }
.table thead th { font-size: .65rem; font-weight: 800; text-transform: uppercase; letter-spacing: .07em; color: #999; border-top: none; padding: 12px 16px; border-bottom: 2px solid #f0f0f0; }
.table tbody td { padding: 13px 16px; vertical-align: middle; border-color: #f5f5f5; }
.table tbody tr { cursor: pointer; transition: .12s; }
.table tbody tr:hover { background: #f8f9ff; }
.status-badge { font-size: .7rem; font-weight: 700; padding: 4px 12px; border-radius: 20px; display: inline-block; white-space: nowrap; }
.s-draft { background:#f1f5f9; color:#64748b; }
.s-pending { background:#fef9c3; color:#854d0e; }
.s-approved { background:#dcfce7; color:#166534; }
.s-dept { background:#dbeafe; color:#1d4ed8; }
.s-assigned { background:#ede9fe; color:#6d28d9; }
.s-working { background:#ffedd5; color:#c2410c; }
.s-review { background:#fce7f3; color:#be185d; }
.s-confirmed { background:#d1fae5; color:#065f46; }
.s-rework { background:#fef3c7; color:#92400e; }
.s-closed { background:#e0f2fe; color:#0369a1; }
.s-rejected { background:#fee2e2; color:#991b1b; }
.priority-badge { font-size: .7rem; font-weight: 700; }
.p-low { color: #64748b; }
.p-normal { color: var(--blue); }
.p-high { color: #f59e0b; }
.p-urgent { color: #ef4444; }
.btn-primary { background: var(--blue); border: none; border-radius: 10px; font-weight: 600; }
.btn-primary:hover { background: var(--blue-dark); }
.form-control, .form-select { border-radius: 10px; border: 1.5px solid #e0e3ef; font-size: .88rem; padding: 9px 14px; transition: .15s; }
.form-control:focus, .form-select:focus { border-color: var(--blue); box-shadow: 0 0 0 3px rgba(0,51,153,.1); }
.form-label { font-size: .75rem; font-weight: 700; text-transform: uppercase; letter-spacing: .07em; color: #666; margin-bottom: 6px; }
.modal-content { border-radius: 18px; border: none; box-shadow: 0 20px 60px rgba(0,0,0,.2); }
.modal-header { border-bottom: 1px solid #f0f0f0; padding: 20px 24px; }
.modal-footer { border-top: 1px solid #f0f0f0; padding: 16px 24px; }
.modal-title { font-weight: 800; font-size: 1rem; }
.alert { border-radius: 12px; font-size: .85rem; }
.chip { display: inline-flex; align-items: center; gap: 5px; background: #eef2ff; color: var(--blue); border-radius: 20px; font-size: .72rem; font-weight: 700; padding: 4px 12px; }
.empty-state { text-align: center; padding: 48px 20px; color: #aaa; }
.empty-state i { font-size: 3rem; display: block; margin-bottom: 12px; opacity: .4; }
.user-card-sm { display: flex; align-items: center; gap: 10px; }
.user-avatar-sm { width: 36px; height: 36px; border-radius: 50%; background: linear-gradient(135deg, var(--blue), var(--blue-mid)); color: #fff; font-weight: 800; font-size: .85rem; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
</style>
</head>
<body>
{% if current_user %}
<nav class="top-nav">
  <a class="brand" href="/"><div class="bar"></div><span>ЛДПР · ЭДО</span></a>
  <div class="spacer"></div>
  <div class="user-pill">
    <div class="user-avatar">{{ current_user.full_name[0] }}</div>
    <div>
      <div class="user-name">{{ current_user.full_name }}</div>
      <div class="user-role-badge">{{ role_labels.get(current_user.role, current_user.role) }}</div>
    </div>
  </div>
  <form action="/logout" method="get" style="margin:0">
    <button type="submit" class="logout-btn" title="Выход"><i class="bi bi-box-arrow-right"></i></button>
  </form>
</nav>
<div class="sidebar">
  <span class="nav-section-label">Навигация</span>
  <div class="nav-item">
    <a class="nav-link {{ 'active' if request.path == '/' }}" href="/"><i class="bi bi-speedometer2"></i> Рабочий стол</a>
  </div>
  <div class="nav-item">
    <a class="nav-link {{ 'active' if '/orders' in request.path }}" href="/orders"><i class="bi bi-file-earmark-text"></i> Распоряжения</a>
  </div>
  {% if current_user.role in ['head_department','admin'] %}
  <div class="nav-item">
    <a class="nav-link {{ 'active' if request.path == '/department' }}" href="/department"><i class="bi bi-building"></i> Отдел</a>
  </div>
  {% endif %}
  {% if current_user.role == 'admin' %}
  <span class="nav-section-label" style="margin-top:8px">Администрирование</span>
  <div class="nav-item">
    <a class="nav-link {{ 'active' if request.path == '/admin' }}" href="/admin"><i class="bi bi-shield-lock"></i> Управление</a>
  </div>
  {% endif %}
  <div class="sidebar-footer">
    <i class="bi bi-cloud me-1"></i> PostgreSQL · Render Cloud
  </div>
</div>
<div class="main-content">
  {% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}{% for cat, msg in messages %}
  <div class="alert alert-{{ cat }} alert-dismissible fade show" role="alert">
    <i class="bi bi-{{ 'check-circle' if cat=='success' else 'exclamation-triangle' if cat=='warning' else 'x-circle' if cat=='danger' else 'info-circle' }} me-2"></i>{{ msg }}
    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
  </div>
  {% endfor %}{% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>
{% else %}
{% block full_content %}{% endblock %}
{% endif %}
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>"""

LOGIN_TEMPLATE = """{% extends "base.html" %}{% block title %}Вход — ЭДО ЛДПР{% endblock %}
{% block full_content %}
<style>
.lp { min-height:100vh; background: linear-gradient(160deg,#001a4d 0%,#003399 50%,#001a4d 100%); display:flex; align-items:center; justify-content:center; }
.lc { background: rgba(0,0,50,.5); border: 2px solid rgba(255,215,0,.35); backdrop-filter:blur(12px); border-radius:24px; padding:48px 52px; width:100%; max-width:420px; box-shadow: 0 24px 64px rgba(0,0,0,.5); }
.l-logo { text-align:center; margin-bottom:8px; }
.l-ldpr { font-size:3.2rem; font-weight:900; color:#FFD700; letter-spacing:6px; text-shadow:0 2px 12px rgba(255,215,0,.4); }
.l-line { height:2px; background:linear-gradient(90deg,transparent,#FFD700,transparent); margin:10px 0; }
.l-sub { text-align:center; color:rgba(255,215,0,.75); font-size:.72rem; letter-spacing:2px; text-transform:uppercase; margin-bottom:36px; line-height:1.6; }
.l-label { color:rgba(255,215,0,.9); font-size:.72rem; font-weight:700; text-transform:uppercase; letter-spacing:.1em; display:block; margin-bottom:8px; }
.l-input { width:100%; background:rgba(255,255,255,.06); border:1.5px solid rgba(255,215,0,.45); border-radius:10px; color:#FFD700; padding:12px 16px 12px 44px; font-size:.95rem; outline:none; transition:.2s; }
.l-input::placeholder { color:rgba(255,215,0,.35); }
.l-input:focus { border-color:#FFD700; background:rgba(255,215,0,.08); box-shadow:0 0 0 3px rgba(255,215,0,.15); }
.l-wrap { position:relative; }
.l-icon { position:absolute; left:14px; top:50%; transform:translateY(-50%); color:rgba(255,215,0,.6); font-size:1rem; }
.l-btn { width:100%; margin-top:24px; padding:14px; background:linear-gradient(180deg,#FFD700,#c8a900); border:none; border-radius:10px; color:#003399; font-weight:800; font-size:1rem; letter-spacing:2px; text-transform:uppercase; cursor:pointer; transition:.2s; }
.l-btn:hover { background:linear-gradient(180deg,#ffe033,#FFD700); box-shadow:0 6px 24px rgba(255,215,0,.35); }
.l-err { background:rgba(239,68,68,.15); border:1px solid rgba(239,68,68,.4); color:#fca5a5; border-radius:10px; padding:10px 14px; font-size:.83rem; margin-bottom:20px; }
.l-accounts { margin-top:28px; padding:16px; background:rgba(255,255,255,.05); border-radius:12px; border:1px solid rgba(255,215,0,.15); }
.l-accounts p { color:rgba(255,215,0,.6); font-size:.68rem; text-transform:uppercase; letter-spacing:.1em; margin:0 0 10px; }
.acc-row { display:flex; justify-content:space-between; font-size:.75rem; color:rgba(255,255,255,.7); padding:3px 0; border-bottom:1px solid rgba(255,255,255,.05); }
.acc-role { color:rgba(255,215,0,.7); font-size:.68rem; }
</style>
<div class="lp">
  <div class="lc">
    <div class="l-logo"><div class="l-ldpr">ЛДПР</div></div>
    <div class="l-line"></div>
    <div class="l-sub">Либерально-демократическая<br>партия России<br><small style="opacity:0.7">Система электронного документооборота</small></div>
    {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}{% for cat,msg in messages %}<div class="l-err"><i class="bi bi-exclamation-circle me-2"></i>{{ msg }}</div>{% endfor %}{% endif %}
    {% endwith %}
    <form method="POST">
      <div class="mb-3">
        <label class="l-label">Логин</label>
        <div class="l-wrap"><i class="bi bi-person l-icon"></i><input type="text" name="username" class="l-input" placeholder="Введите логин" required autocomplete="username"></div>
      </div>
      <div class="mb-2">
        <label class="l-label">Пароль</label>
        <div class="l-wrap"><i class="bi bi-lock l-icon"></i><input type="password" name="password" class="l-input" placeholder="Введите пароль" required autocomplete="current-password"></div>
      </div>
      <button type="submit" class="l-btn">Войти в систему</button>
    </form>
    <div class="l-accounts">
      <p>Тестовые аккаунты</p>
      <div class="acc-row"><span>admin / admin123</span><span class="acc-role">Администратор</span></div>
      <div class="acc-row"><span>head_central / head123</span><span class="acc-role">Рук. ЦА</span></div>
      <div class="acc-row"><span>secretary / sec123</span><span class="acc-role">Секретарь</span></div>
      <div class="acc-row"><span>head_department / head123</span><span class="acc-role">Нач. отдела</span></div>
      <div class="acc-row"><span>assistant / ast123</span><span class="acc-role">Помощник</span></div>
      <div class="acc-row"><span>executor / exec123</span><span class="acc-role">Исполнитель</span></div>
    </div>
  </div>
</div>
{% endblock %}"""

DASHBOARD_TEMPLATE = """{% extends "base.html" %}{% block title %}Рабочий стол — ЭДО ЛДПР{% endblock %}
{% block content %}
<div class="page-header">
  <h2><i class="bi bi-speedometer2 me-2" style="color:var(--blue)"></i>Рабочий стол</h2>
  <p>Добро пожаловать, {{ current_user.full_name }} · {{ role_labels.get(current_user.role,'') }}</p>
</div>
<div class="row g-3 mb-4">
  <div class="col-6 col-md-3">
    <div class="stat-card blue">
      <div class="stat-label">Всего</div>
      <div class="stat-value">{{ stats.total }}</div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="stat-card amber">
      <div class="stat-label">Ожидают</div>
      <div class="stat-value">{{ stats.pending }}</div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="stat-card green">
      <div class="stat-label">Утверждено</div>
      <div class="stat-value">{{ stats.approved }}</div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="stat-card purple">
      <div class="stat-label">В работе</div>
      <div class="stat-value">{{ stats.in_work }}</div>
    </div>
  </div>
</div>
<div class="card">
  <div class="card-body">
    <div class="d-flex justify-content-between align-items-center mb-3">
      <h5 class="fw-bold mb-0" style="font-size:.95rem"><i class="bi bi-clock-history me-2" style="color:var(--blue)"></i>Последние распоряжения</h5>
      <a href="/orders" class="btn btn-primary btn-sm">Все <i class="bi bi-arrow-right ms-1"></i></a>
    </div>
    {% if orders %}
    <div class="table-responsive">
      <table class="table">
        <thead><tr><th>Документ</th><th>Статус</th><th>Приоритет</th><th>Дата</th></tr></thead>
        <tbody>
          {% for o in orders %}
          <tr onclick="location.href='/orders/{{ o.id }}'">
            <td><div class="fw-bold" style="font-size:.88rem">{{ o.title }}</div><div style="font-size:.72rem;color:#aaa">#{{ o.id[:8] }}</div></td>
            <td><span class="status-badge {{ status_class(o.status) }}">{{ o.status }}</span></td>
            <td><span class="priority-badge {{ priority_class(o.priority) }}">{{ o.priority }}</span></td>
            <td style="font-size:.78rem;color:#aaa">{{ o.created_at[:10] }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
    <div class="empty-state"><i class="bi bi-file-earmark-x"></i>Нет распоряжений</div>
    {% endif %}
  </div>
</div>
{% endblock %}"""

ORDERS_TEMPLATE = """{% extends "base.html" %}{% block title %}Распоряжения — ЭДО ЛДПР{% endblock %}
{% block content %}
<div class="page-header d-flex justify-content-between align-items-start">
  <div><h2><i class="bi bi-file-earmark-text me-2" style="color:var(--blue)"></i>Реестр распоряжений</h2><p>{{ orders|length }} документов</p></div>
  {% if current_user.role == 'assistant' %}<button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#createModal"><i class="bi bi-plus-lg me-1"></i>Создать</button>{% endif %}
</div>
<div class="card">
  {% if orders %}
  <div class="table-responsive">
    <table class="table mb-0">
      <thead><tr><th>Документ</th><th>Статус</th><th>Приоритет</th><th>Срок</th><th>Автор</th><th>Создан</th></tr></thead>
      <tbody>
        {% for o in orders %}
        <tr onclick="location.href='/orders/{{ o.id }}'">
          <td><div class="fw-bold">{{ o.title }}</div><div style="font-size:.72rem;color:#bbb">#{{ o.id[:8] }}</div></td>
          <td><span class="status-badge {{ status_class(o.status) }}">{{ o.status }}</span></td>
          <td><span class="priority-badge {{ priority_class(o.priority) }}">{{ o.priority }}</span></td>
          <td style="font-size:.8rem">{{ o.deadline or '—' }}</td>
          <td><div class="user-card-sm"><div class="user-avatar-sm" style="width:28px;height:28px;font-size:.72rem">{{ (o.creator_name or '?')[0] }}</div><span style="font-size:.82rem">{{ o.creator_name }}</span></div></td>
          <td style="font-size:.78rem;color:#aaa">{{ o.created_at[:10] }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <div class="empty-state"><i class="bi bi-file-earmark-x"></i><br>Нет распоряжений</div>
  {% endif %}
</div>
{% if current_user.role == 'assistant' %}
<div class="modal fade" id="createModal" tabindex="-1">
  <div class="modal-dialog modal-lg">
    <div class="modal-content">
      <div class="modal-header"><h5 class="modal-title"><i class="bi bi-file-earmark-plus me-2" style="color:var(--blue)"></i>Новое распоряжение</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
      <form method="POST" action="/orders/create">
        <div class="modal-body">
          <div class="mb-3"><label class="form-label">Заголовок *</label><input type="text" name="title" class="form-control" required></div>
          <div class="row mb-3">
            <div class="col-md-6"><label class="form-label">Приоритет</label><select name="priority" class="form-select"><option>Низкий</option><option selected>Нормальный</option><option>Высокий</option><option>Срочный</option></select></div>
            <div class="col-md-6"><label class="form-label">Срок исполнения</label><input type="date" name="deadline" class="form-control"></div>
          </div>
          <div class="mb-3"><label class="form-label">Текст распоряжения *</label><textarea name="content" class="form-control" rows="7" required></textarea></div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Отмена</button>
          <button type="submit" name="is_draft" value="1" class="btn btn-outline-primary"><i class="bi bi-save me-1"></i>Черновик</button>
          <button type="submit" class="btn btn-primary"><i class="bi bi-send me-1"></i>На утверждение</button>
        </div>
      </form>
    </div>
  </div>
</div>
{% endif %}
{% endblock %}"""

ORDER_DETAILS_TEMPLATE = """{% extends "base.html" %}{% block title %}{{ order.title }} — ЭДО ЛДПР{% endblock %}
{% block content %}
<a href="/orders" class="btn btn-outline-secondary btn-sm mb-3"><i class="bi bi-arrow-left me-1"></i>Назад</a>
<div class="row g-3">
  <div class="col-lg-8">
    <div class="card mb-3">
      <div class="card-body">
        <div class="d-flex justify-content-between align-items-start mb-3">
          <div>
            <h4 class="fw-bold mb-1">{{ order.title }}</h4>
            <span class="status-badge {{ status_class(order.status) }}">{{ order.status }}</span>
            <span class="priority-badge {{ priority_class(order.priority) }} ms-2">{{ order.priority }}</span>
          </div>
        </div>
        <div style="background:#f8f9ff;border-radius:12px;padding:18px;white-space:pre-wrap;font-size:.88rem;line-height:1.7">{{ order.content }}</div>
        {% if order.result and order.result is mapping %}
        <div class="mt-3 p-3 rounded" style="background:#f0fdf4;border:1.5px solid #86efac">
          <div style="font-size:.72rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;color:#15803d;margin-bottom:8px"><i class="bi bi-check-circle-fill me-2"></i>Результат</div>
          <div style="white-space:pre-wrap;font-size:.88rem">{{ order.result.content }}</div>
        </div>
        {% endif %}
      </div>
    </div>
    <div class="card">
      <div class="card-body">
        <h5 class="fw-bold mb-4"><i class="bi bi-clock-history me-2" style="color:var(--blue)"></i>История</h5>
        {% if history %}
        {% for h in history %}
        <div class="d-flex gap-3 mb-3">
          <div style="width:30px;height:30px;border-radius:50%;background:var(--blue);color:#fff;display:flex;align-items:center;justify-content:center;font-size:.75rem;flex-shrink:0"><i class="bi bi-arrow-repeat"></i></div>
          <div class="flex-fill">
            <div class="fw-bold">{{ h.action }}</div>
            {% if h.details %}<div style="color:#666;font-size:.82rem">{{ h.details }}</div>{% endif %}
            <div style="color:#aaa;font-size:.72rem;margin-top:2px">{{ h.user_name }} · {{ h.created_at[:16] }}</div>
          </div>
        </div>
        {% endfor %}
        {% else %}
        <div class="empty-state"><i class="bi bi-clock"></i>Нет записей</div>
        {% endif %}
      </div>
    </div>
  </div>
  <div class="col-lg-4">
    <div class="card">
      <div class="card-body">
        <h5 class="fw-bold mb-3"><i class="bi bi-lightning-charge me-2" style="color:var(--blue)"></i>Действия</h5>
        {% if current_user.role == 'head_central' and order.status == 'На утверждении' %}
        <form method="POST" action="/orders/{{ order.id }}/status" class="mb-2">
          <input type="hidden" name="status" value="Утверждено">
          <button class="btn btn-success w-100 mb-2"><i class="bi bi-check-circle me-2"></i>Утвердить</button>
        </form>
        <form method="POST" action="/orders/{{ order.id }}/status">
          <input type="hidden" name="status" value="Отклонено">
          <input type="text" name="comment" class="form-control form-control-sm mb-2" placeholder="Причина...">
          <button class="btn btn-danger w-100"><i class="bi bi-x-circle me-2"></i>Отклонить</button>
        </form>
        {% endif %}
        {% if current_user.role == 'secretary' and order.status == 'Утверждено' %}
        <form method="POST" action="/orders/{{ order.id }}/status">
          <input type="hidden" name="status" value="В отделе">
          <select name="department_id" class="form-select form-select-sm mb-2" required>
            <option value="">Выберите отдел...</option>
            {% for d in departments %}<option value="{{ d.id }}">{{ d.name }}</option>{% endfor %}
          </select>
          <button class="btn btn-primary w-100"><i class="bi bi-send me-2"></i>Назначить</button>
        </form>
        {% endif %}
        {% if current_user.role == 'head_department' and order.status == 'В отделе' %}
        <form method="POST" action="/orders/{{ order.id }}/status">
          <input type="hidden" name="status" value="Назначен исполнитель">
          <select name="executor_id" class="form-select form-select-sm mb-2" required>
            <option value="">Выберите исполнителя...</option>
            {% for u in dept_users %}<option value="{{ u.uid }}">{{ u.full_name }}</option>{% endfor %}
          </select>
          <button class="btn btn-primary w-100"><i class="bi bi-person-check me-2"></i>Назначить</button>
        </form>
        {% endif %}
        {% if current_user.role == 'executor' and order.status == 'Назначен исполнитель' and order.assigned_executor_id == current_user.uid %}
        <form method="POST" action="/orders/{{ order.id }}/status">
          <input type="hidden" name="status" value="В работе">
          <button class="btn btn-primary w-100"><i class="bi bi-play-fill me-2"></i>Взять в работу</button>
        </form>
        {% endif %}
        {% if current_user.role == 'executor' and order.status == 'В работе' and order.assigned_executor_id == current_user.uid %}
        <form method="POST" action="/orders/{{ order.id }}/submit">
          <textarea name="result_content" class="form-control form-control-sm mb-2" rows="5" placeholder="Результат..." required></textarea>
          <button class="btn btn-success w-100"><i class="bi bi-check-lg me-2"></i>Сдать</button>
        </form>
        {% endif %}
        {% if current_user.role == 'head_department' and order.status == 'Готово к проверке' %}
        <form method="POST" action="/orders/{{ order.id }}/status" class="mb-2">
          <input type="hidden" name="status" value="Подтверждено">
          <button class="btn btn-success w-100 mb-2"><i class="bi bi-check-circle me-2"></i>Подтвердить</button>
        </form>
        {% endif %}
        {% if current_user.role == 'head_central' and order.status == 'Подтверждено' %}
        <form method="POST" action="/orders/{{ order.id }}/status">
          <input type="hidden" name="status" value="Закрыто">
          <button class="btn btn-success w-100"><i class="bi bi-lock-fill me-2"></i>Закрыть</button>
        </form>
        {% endif %}
      </div>
    </div>
  </div>
</div>
{% endblock %}"""

DEPARTMENT_TEMPLATE = """{% extends "base.html" %}{% block title %}Отдел — ЭДО ЛДПР{% endblock %}
{% block content %}
<div class="page-header">
  <h2><i class="bi bi-building me-2" style="color:var(--blue)"></i>{{ department.name }}</h2>
</div>
<div class="row g-3">
  <div class="col-lg-5">
    <div class="card">
      <div class="card-body">
        <h5 class="fw-bold mb-3"><i class="bi bi-people me-2" style="color:var(--blue)"></i>Сотрудники</h5>
        {% if users %}
        {% for u in users %}
        <div class="d-flex align-items-center gap-3 py-3 border-bottom">
          <div class="user-avatar-sm">{{ u.full_name[0] }}</div>
          <div class="flex-fill">
            <div class="fw-bold">{{ u.full_name }}</div>
            <div style="font-size:.75rem;color:#aaa">{{ role_labels.get(u.role, u.role) }}</div>
          </div>
        </div>
        {% endfor %}
        {% else %}
        <div class="empty-state"><i class="bi bi-person-x"></i>Нет сотрудников</div>
        {% endif %}
      </div>
    </div>
  </div>
  <div class="col-lg-7">
    <div class="card">
      <div class="card-body">
        <h5 class="fw-bold mb-3"><i class="bi bi-file-earmark-text me-2" style="color:var(--blue)"></i>Распоряжения</h5>
        {% if orders %}
        <div class="table-responsive">
          <table class="table">
            <thead><tr><th>Документ</th><th>Статус</th><th>Дата</th></tr></thead>
            <tbody>
              {% for o in orders %}
              <tr onclick="location.href='/orders/{{ o.id }}'">
                <td><div class="fw-bold">{{ o.title }}</div></td>
                <td><span class="status-badge {{ status_class(o.status) }}">{{ o.status }}</span></td>
                <td style="font-size:.78rem;color:#aaa">{{ o.created_at[:10] }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
        {% else %}
        <div class="empty-state"><i class="bi bi-file-earmark-x"></i>Нет распоряжений</div>
        {% endif %}
      </div>
    </div>
  </div>
</div>
{% endblock %}"""

ADMIN_TEMPLATE = """{% extends "base.html" %}{% block title %}Администрирование — ЭДО ЛДПР{% endblock %}
{% block content %}
<div class="page-header">
  <h2><i class="bi bi-shield-lock me-2" style="color:var(--blue)"></i>Администрирование</h2>
</div>
<div class="card">
  <div class="card-body">
    <div class="d-flex justify-content-between align-items-center mb-3">
      <h5 class="fw-bold mb-0"><i class="bi bi-people me-2" style="color:var(--blue)"></i>Пользователи</h5>
      <button class="btn btn-primary btn-sm" data-bs-toggle="modal" data-bs-target="#addUserModal"><i class="bi bi-plus-lg me-1"></i>Добавить</button>
    </div>
    <div class="table-responsive">
      <table class="table mb-0">
        <thead><tr><th>ФИО</th><th>Роль</th><th>Email</th><th>Действия</th></tr></thead>
        <tbody>
          {% for u in users %}
          <tr>
            <td><div class="user-card-sm"><div class="user-avatar-sm">{{ u.full_name[0] }}</div><span class="fw-bold">{{ u.full_name }}</span></div></td>
            <td><span class="status-badge s-draft">{{ role_labels.get(u.role, u.role) }}</span></td>
            <td style="font-size:.82rem">{{ u.email }}</td>
            <td>
              <button class="btn btn-sm btn-outline-primary me-1" data-bs-toggle="modal" data-bs-target="#editUser{{ u.uid }}"><i class="bi bi-pencil"></i></button>
              {% if u.uid != current_user.uid %}<form method="POST" action="/admin/users/{{ u.uid }}/delete" class="d-inline" onsubmit="return confirm('Удалить?')"><button type="submit" class="btn btn-sm btn-outline-danger"><i class="bi bi-trash"></i></button></form>{% endif %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>
<div class="modal fade" id="addUserModal" tabindex="-1">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title">Добавить пользователя</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
    <form method="POST" action="/admin/users/create">
      <div class="modal-body">
        <div class="mb-3"><label class="form-label">ФИО</label><input type="text" name="full_name" class="form-control" required></div>
        <div class="mb-3"><label class="form-label">Email</label><input type="email" name="email" class="form-control" required></div>
        <div class="mb-3"><label class="form-label">Логин</label><input type="text" name="username" class="form-control" required></div>
        <div class="mb-3"><label class="form-label">Пароль</label><input type="password" name="password" class="form-control" required></div>
        <div class="mb-3"><label class="form-label">Роль</label><select name="role" class="form-select"><option value="executor">Исполнитель</option><option value="head_department">Начальник отдела</option><option value="assistant">Помощник</option><option value="secretary">Секретарь</option><option value="admin">Администратор</option></select></div>
      </div>
      <div class="modal-footer"><button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Отмена</button><button type="submit" class="btn btn-primary">Создать</button></div>
    </form>
  </div></div>
</div>
{% for u in users %}
<div class="modal fade" id="editUser{{ u.uid }}" tabindex="-1">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title">Редактировать: {{ u.full_name }}</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
    <form method="POST" action="/admin/users/{{ u.uid }}/edit">
      <div class="modal-body">
        <div class="mb-3"><label class="form-label">ФИО</label><input type="text" name="full_name" class="form-control" value="{{ u.full_name }}" required></div>
        <div class="mb-3"><label class="form-label">Email</label><input type="email" name="email" class="form-control" value="{{ u.email }}" required></div>
        <div class="mb-3"><label class="form-label">Роль</label><select name="role" class="form-select"><option value="executor" {% if u.role=='executor' %}selected{% endif %}>Исполнитель</option><option value="head_department" {% if u.role=='head_department' %}selected{% endif %}>Начальник отдела</option><option value="assistant" {% if u.role=='assistant' %}selected{% endif %}>Помощник</option><option value="secretary" {% if u.role=='secretary' %}selected{% endif %}>Секретарь</option><option value="admin" {% if u.role=='admin' %}selected{% endif %}>Администратор</option></select></div>
      </div>
      <div class="modal-footer"><button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Отмена</button><button type="submit" class="btn btn-primary">Сохранить</button></div>
    </form>
  </div></div>
</div>
{% endfor %}
{% endblock %}"""

TEMPLATES = {
    'base.html': BASE_TEMPLATE,
    'login.html': LOGIN_TEMPLATE,
    'dashboard.html': DASHBOARD_TEMPLATE,
    'orders.html': ORDERS_TEMPLATE,
    'order_details.html': ORDER_DETAILS_TEMPLATE,
    'department.html': DEPARTMENT_TEMPLATE,
    'admin.html': ADMIN_TEMPLATE,
}
app_flask.jinja_loader = DictLoader(TEMPLATES)

def status_class(status):
    m = {
        'Черновик': 's-draft', 'На утверждении': 's-pending',
        'Утверждено': 's-approved', 'В отделе': 's-dept',
        'Назначен исполнитель': 's-assigned', 'В работе': 's-working',
        'Готово к проверке': 's-review', 'Подтверждено': 's-confirmed',
        'На доработке': 's-rework', 'Закрыто': 's-closed', 'Отклонено': 's-rejected',
    }
    return m.get(status, 's-draft')

def priority_class(p):
    return {'Низкий':'p-low','Нормальный':'p-normal','Высокий':'p-high','Срочный':'p-urgent'}.get(p,'p-normal')

ROLE_LABELS = {
    'admin':'Администратор','secretary':'Секретарь','head_central':'Руководитель ЦА',
    'head_department':'Начальник отдела','assistant':'Помощник','executor':'Исполнитель',
}

@app_flask.context_processor
def template_globals():
    return {
        'role_labels': ROLE_LABELS,
        'status_class': status_class,
        'priority_class': priority_class,
    }

# ============================================================
# МАРШРУТЫ (основные)
# ============================================================

@app_flask.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = UserModel.get_by_username(username)
        if user and check_password_hash(user['password'], password):
            session.permanent = True
            session['user_id'] = user['uid']
            session['user_name'] = user['full_name']
            session['user_role'] = user['role']
            session['department_id'] = user['department_id']
            flash(f'Добро пожаловать, {user["full_name"]}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Неверный логин или пароль', 'danger')
    return render_template_string(TEMPLATES['login.html'])

@app_flask.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app_flask.route('/')
@login_required
def dashboard():
    stats = OrderModel.get_stats(uid=session['user_id'], role=session['user_role'], department_id=session.get('department_id'))
    orders = OrderModel.get_by_user(uid=session['user_id'], role=session['user_role'], department_id=session.get('department_id'))[:8]
    return render_template_string(TEMPLATES['dashboard.html'], stats=stats, orders=orders)

@app_flask.route('/orders')
@login_required
def orders():
    all_orders = OrderModel.get_by_user(uid=session['user_id'], role=session['user_role'], department_id=session.get('department_id'))
    now = datetime.now().strftime('%Y-%m-%d')
    return render_template_string(TEMPLATES['orders.html'], orders=all_orders,
                                  statuses=OrderModel.STATUSES, priorities=OrderModel.PRIORITIES, now=now)

@app_flask.route('/orders/create', methods=['POST'])
@login_required
@role_required('assistant')
def create_order():
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    if not title or not content:
        flash('Заголовок и содержание обязательны', 'danger')
        return redirect(url_for('orders'))
    
    order_id = 'order-' + str(uuid.uuid4())[:8]
    is_draft = request.form.get('is_draft') == '1'
    status = 'Черновик' if is_draft else 'На утверждении'
    user = UserModel.get_by_id(session['user_id'])
    
    OrderModel.create(order_id, title, content, request.form.get('priority', 'Нормальный'),
                      status, session['user_id'], user['full_name'], request.form.get('deadline') or None)
    OrderHistoryModel.add(order_id, 'Создание распоряжения', user['full_name'], session['user_role'], f'Статус: {status}')
    flash('Распоряжение создано', 'success')
    return redirect(url_for('orders'))

@app_flask.route('/orders/<order_id>')
@login_required
def order_details(order_id):
    order = OrderModel.get_by_id(order_id)
    if not order:
        flash('Распоряжение не найдено', 'danger')
        return redirect(url_for('orders'))
    
    history = OrderHistoryModel.get_by_order(order_id)
    departments = DepartmentModel.get_all()
    dept_users = UserModel.get_by_department(order.get('assigned_department_id')) if order.get('assigned_department_id') else []
    
    now = datetime.now().strftime('%Y-%m-%d')
    return render_template_string(TEMPLATES['order_details.html'],
                                  order=order, history=history, departments=departments, dept_users=dept_users, now=now)

@app_flask.route('/orders/<order_id>/status', methods=['POST'])
@login_required
def update_order_status(order_id):
    order = OrderModel.get_by_id(order_id)
    if not order:
        flash('Распоряжение не найдено', 'danger')
        return redirect(url_for('orders'))
    
    new_status = request.form.get('status')
    comment = request.form.get('comment', '')
    user = UserModel.get_by_id(session['user_id'])
    current_role = session['user_role']
    current_status = order['status']
    
    allowed = False
    details = f'Статус: {new_status}'
    extra = {}
    
    if current_role == 'head_central' and current_status == 'На утверждении' and new_status in ['Утверждено', 'Отклонено']:
        allowed = True
        if comment: details += f' · {comment}'
    
    elif current_role == 'secretary' and current_status == 'Утверждено':
        dept_id = request.form.get('department_id')
        if dept_id:
            allowed = True
            new_status = 'В отделе'
            extra['assigned_department_id'] = dept_id
            dept = DepartmentModel.get_by_id(dept_id)
            details = f'Назначен отдел: {dept["name"] if dept else dept_id}'
    
    elif current_role == 'head_department' and current_status == 'В отделе':
        exec_id = request.form.get('executor_id')
        if exec_id:
            allowed = True
            new_status = 'Назначен исполнитель'
            extra['assigned_executor_id'] = exec_id
            executor = UserModel.get_by_id(exec_id)
            details = f'Назначен исполнитель: {executor["full_name"] if executor else exec_id}'
    
    elif current_role == 'executor' and current_status == 'Назначен исполнитель' and order.get('assigned_executor_id') == session['user_id']:
        allowed = True
        new_status = 'В работе'
        details = 'Исполнитель взял в работу'
    
    elif current_role == 'head_department' and current_status == 'Готово к проверке' and new_status == 'Подтверждено':
        allowed = True
        details = 'Результат подтверждён'
    
    elif current_role == 'head_central' and current_status == 'Подтверждено' and new_status == 'Закрыто':
        allowed = True
        details = 'Распоряжение закрыто'
    
    if allowed:
        OrderModel.update(order_id, status=new_status, **extra)
        OrderHistoryModel.add(order_id, 'Изменение статуса', user['full_name'], current_role, details)
        flash('Статус обновлён', 'success')
    else:
        flash('Действие не разрешено', 'danger')
    
    return redirect(url_for('order_details', order_id=order_id))

@app_flask.route('/orders/<order_id>/submit', methods=['POST'])
@login_required
def submit_order_result(order_id):
    order = OrderModel.get_by_id(order_id)
    if not order or session['user_role'] != 'executor' or order['status'] != 'В работе' or order.get('assigned_executor_id') != session['user_id']:
        flash('Действие не разрешено', 'danger')
        return redirect(url_for('order_details', order_id=order_id))
    
    result_content = request.form.get('result_content', '').strip()
    if not result_content:
        flash('Опишите результат', 'warning')
        return redirect(url_for('order_details', order_id=order_id))
    
    result = {'content': result_content, 'submittedAt': datetime.now().isoformat()}
    OrderModel.update(order_id, status='Готово к проверке', result=result)
    user = UserModel.get_by_id(session['user_id'])
    OrderHistoryModel.add(order_id, 'Сдача работы', user['full_name'], session['user_role'], 'Работа сдана на проверку')
    flash('Работа сдана', 'success')
    return redirect(url_for('order_details', order_id=order_id))

@app_flask.route('/department')
@login_required
def department():
    dept_id = session.get('department_id')
    if not dept_id:
        flash('У вас нет отдела', 'warning')
        return redirect(url_for('dashboard'))
    
    dept = DepartmentModel.get_by_id(dept_id)
    if not dept:
        flash('Отдел не найден', 'danger')
        return redirect(url_for('dashboard'))
    
    users = UserModel.get_by_department(dept_id)
    orders = OrderModel.get_by_department(dept_id)
    return render_template_string(TEMPLATES['department.html'], department=dept, users=users, orders=orders)

@app_flask.route('/admin')
@login_required
@role_required('admin')
def admin_panel():
    users = UserModel.get_all()
    departments = DepartmentModel.get_all()
    return render_template_string(TEMPLATES['admin.html'], users=users, departments=departments)

@app_flask.route('/admin/users/create', methods=['POST'])
@login_required
@role_required('admin')
def admin_create_user():
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'executor')
    
    if not all([full_name, email, username, password]):
        flash('Все поля обязательны', 'danger')
        return redirect(url_for('admin_panel'))
    
    uid = 'u-' + str(uuid.uuid4())[:8]
    success, error = UserModel.create(uid, full_name, email, username, generate_password_hash(password), role)
    flash('Пользователь создан' if success else (error or 'Ошибка'), 'success' if success else 'danger')
    return redirect(url_for('admin_panel'))

@app_flask.route('/admin/users/<uid>/edit', methods=['POST'])
@login_required
@role_required('admin')
def admin_edit_user(uid):
    updates = {
        'full_name': request.form.get('full_name', '').strip(),
        'email': request.form.get('email', '').strip(),
        'role': request.form.get('role'),
    }
    UserModel.update(uid, **{k: v for k, v in updates.items() if v is not None})
    flash('Пользователь обновлён', 'success')
    return redirect(url_for('admin_panel'))

@app_flask.route('/admin/users/<uid>/delete', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_user(uid):
    if uid == session['user_id']:
        flash('Нельзя удалить себя', 'danger')
        return redirect(url_for('admin_panel'))
    UserModel.delete(uid)
    flash('Пользователь удалён', 'success')
    return redirect(url_for('admin_panel'))

# ============================================================
# PyQt6 ПРИЛОЖЕНИЕ
# ============================================================

class ConnectionDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Подключение к серверу")
        self.setMinimumSize(400, 150)
        self.setStyleSheet("""
            QDialog { background: #fff; }
            QLabel { color: #333; font-size: 14px; }
        """)
        
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        self.label = QLabel("⏳ Подключение к облачному серверу...")
        layout.addWidget(self.label)
        
        self.progress = QProgressBar()
        self.progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ddd;
                border-radius: 5px;
                background: #f5f5f5;
            }
            QProgressBar::chunk {
                background: #003399;
            }
        """)
        layout.addWidget(self.progress)
        
        self.setLayout(layout)
        self.setModal(True)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ЭДО ЛДПР - Облачная версия")
        self.setMinimumSize(1400, 900)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.web_view = QWebEngineView()
        self.web_view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        self.web_view.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        layout.addWidget(self.web_view)
        
        self._create_menu()
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("🔄 Инициализация приложения...")
        
        # Диалог подключения
        self.conn_dialog = ConnectionDialog()
        self.conn_dialog.show()
        
        # Запуск проверки подключения
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self._check_connection)
        self.check_timer.start(500)
        self.retry_count = 0
    
    def _create_menu(self):
        mb = self.menuBar()
        
        fm = mb.addMenu('Файл')
        r = QAction('Обновить (F5)', self)
        r.setShortcut('F5')
        r.triggered.connect(self.web_view.reload)
        fm.addAction(r)
        fm.addSeparator()
        ex = QAction('Выход', self)
        ex.triggered.connect(self.close)
        fm.addAction(ex)
        
        vm = mb.addMenu('Вид')
        zi = QAction('Увеличить (Ctrl++)', self)
        zi.triggered.connect(lambda: self.web_view.setZoomFactor(self.web_view.zoomFactor() + 0.1))
        vm.addAction(zi)
        zo = QAction('Уменьшить (Ctrl+-)', self)
        zo.triggered.connect(lambda: self.web_view.setZoomFactor(self.web_view.zoomFactor() - 0.1))
        vm.addAction(zo)
        
        hm = mb.addMenu('Помощь')
        ab = QAction('О программе', self)
        ab.triggered.connect(self._about)
        hm.addAction(ab)
    
    def _check_connection(self):
        """Проверка доступности сервера Render"""
        try:
            import socket
            import urllib.request
            
            # Попытка подключиться к серверу
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            
            # Получаем хост из DATABASE_URL
            try:
                # Попробуем подключиться через простой DNS check
                urllib.request.urlopen('http://render.com', timeout=5)
            except:
                pass
            
            # Попробуем подключиться через простой HTTP запрос к приложению
            try:
                import http.client
                conn = http.client.HTTPConnection("localhost", 5000, timeout=5)
                conn.request("GET", "/login")
                response = conn.getresponse()
                
                if response.status == 200:
                    self.check_timer.stop()
                    self._on_connected()
                    return
            except:
                pass
            
            self.retry_count += 1
            progress = min(self.retry_count * 10, 90)
            self.conn_dialog.progress.setValue(progress)
            
            if self.retry_count > 30:  # 15 секунд
                self._on_connection_failed()
            
        except Exception as e:
            print(f"Ошибка проверки: {e}")
    
    def _on_connected(self):
        """Приложение готово"""
        self.conn_dialog.close()
        self.status_bar.showMessage('✓ Приложение готово | PostgreSQL (Render) | Облако')
        self.web_view.load(QUrl('http://localhost:5000/login'))
    
    def _on_connection_failed(self):
        """Ошибка подключения"""
        self.check_timer.stop()
        self.conn_dialog.close()
        
        QMessageBox.critical(self, 'Ошибка подключения',
            'Не удалось подключиться к серверу.\n\n'
            'Убедитесь, что:\n'
            '1. Установлены переменные окружения:\n'
            '   - DATABASE_URL=postgresql://...\n'
            '   - FLASK_SECRET=...\n\n'
            '2. Интернет соединение активно\n\n'
            '3. Render сервер доступен')
        
        self.close()
    
    def _about(self):
        QMessageBox.about(self, 'О программе',
            '<h3>ЭДО ЛДПР v2.0 (Облачная)</h3>'
            '<p>Система электронного документооборота</p>'
            '<p><b>БД:</b> PostgreSQL на Render (облако)</p>'
            '<p><b>Сервер:</b> Встроенный Flask</p>'
            '<p>PyQt6 + Flask + Bootstrap</p>')
    
    def closeEvent(self, event):
        reply = QMessageBox.question(self, 'Подтверждение', 
                                     'Закрыть приложение?',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            event.accept()
        else:
            event.ignore()

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ЭДО ЛДПР (Облачная версия)")
    app.setApplicationVersion("2.0")
    app.setStyle('Fusion')
    app.setFont(QFont("Segoe UI", 10))
    
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()

# ============================================================
# Для локального использования с PyQt6
# ============================================================

def run_local():
    """Запуск локальной версии с PyQt6"""
    
    class ConnectionDialog(QDialog):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Подключение к серверу")
            self.setMinimumSize(400, 150)
            self.setStyleSheet("""
                QDialog { background: #fff; }
                QLabel { color: #333; font-size: 14px; }
            """)
            
            layout = QVBoxLayout()
            layout.setSpacing(15)
            layout.setContentsMargins(30, 30, 30, 30)
            
            self.label = QLabel("⏳ Подключение к облачному серверу...")
            layout.addWidget(self.label)
            
            self.progress = QProgressBar()
            self.progress.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #ddd;
                    border-radius: 5px;
                    background: #f5f5f5;
                }
                QProgressBar::chunk {
                    background: #003399;
                }
            """)
            layout.addWidget(self.progress)
            
            self.setLayout(layout)
            self.setModal(True)

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("ЭДО ЛДПР - Облачная версия")
            self.setMinimumSize(1400, 900)
            
            central = QWidget()
            self.setCentralWidget(central)
            layout = QVBoxLayout(central)
            layout.setContentsMargins(0, 0, 0, 0)
            
            self.web_view = QWebEngineView()
            self.web_view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
            self.web_view.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            layout.addWidget(self.web_view)
            
            self._create_menu()
            
            self.status_bar = QStatusBar()
            self.setStatusBar(self.status_bar)
            self.status_bar.showMessage("🔄 Инициализация приложения...")
            
            # Диалог подключения
            self.conn_dialog = ConnectionDialog()
            self.conn_dialog.show()
            
            # Запуск проверки подключения
            self.check_timer = QTimer()
            self.check_timer.timeout.connect(self._check_connection)
            self.check_timer.start(500)
            self.retry_count = 0
        
        def _create_menu(self):
            mb = self.menuBar()
            
            fm = mb.addMenu('Файл')
            r = QAction('Обновить (F5)', self)
            r.setShortcut('F5')
            r.triggered.connect(self.web_view.reload)
            fm.addAction(r)
            fm.addSeparator()
            ex = QAction('Выход', self)
            ex.triggered.connect(self.close)
            fm.addAction(ex)
            
            vm = mb.addMenu('Вид')
            zi = QAction('Увеличить (Ctrl++)', self)
            zi.triggered.connect(lambda: self.web_view.setZoomFactor(self.web_view.zoomFactor() + 0.1))
            vm.addAction(zi)
            zo = QAction('Уменьшить (Ctrl+-)', self)
            zo.triggered.connect(lambda: self.web_view.setZoomFactor(self.web_view.zoomFactor() - 0.1))
            vm.addAction(zo)
            
            hm = mb.addMenu('Помощь')
            ab = QAction('О программе', self)
            ab.triggered.connect(self._about)
            hm.addAction(ab)
        
        def _check_connection(self):
            """Проверка доступности сервера"""
            try:
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                
                try:
                    import http.client
                    conn = http.client.HTTPConnection("localhost", 5000, timeout=5)
                    conn.request("GET", "/login")
                    response = conn.getresponse()
                    
                    if response.status == 200:
                        self.check_timer.stop()
                        self._on_connected()
                        return
                except:
                    pass
                
                self.retry_count += 1
                progress = min(self.retry_count * 10, 90)
                self.conn_dialog.progress.setValue(progress)
                
                if self.retry_count > 30:
                    self._on_connection_failed()
                
            except Exception as e:
                print(f"Ошибка проверки: {e}")
        
        def _on_connected(self):
            """Приложение готово"""
            self.conn_dialog.close()
            self.status_bar.showMessage('✓ Приложение готово | PostgreSQL (Render) | Облако')
            self.web_view.load(QUrl('http://localhost:5000/login'))
        
        def _on_connection_failed(self):
            """Ошибка подключения"""
            self.check_timer.stop()
            self.conn_dialog.close()
            
            QMessageBox.critical(self, 'Ошибка подключения',
                'Не удалось подключиться к серверу.\n\n'
                'Убедитесь, что:\n'
                '1. Установлены переменные окружения\n'
                '2. Интернет соединение активно\n'
                '3. Render сервер доступен')
            
            self.close()
        
        def _about(self):
            QMessageBox.about(self, 'О программе',
                '<h3>ЭДО ЛДПР v2.0 (Облачная)</h3>'
                '<p>Система электронного документооборота</p>'
                '<p><b>БД:</b> PostgreSQL на Render</p>'
                '<p>PyQt6 + Flask + Bootstrap</p>')
        
        def closeEvent(self, event):
            reply = QMessageBox.question(self, 'Подтверждение', 
                                         'Закрыть приложение?',
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                event.accept()
            else:
                event.ignore()

    def main():
        app = QApplication(sys.argv)
        app.setApplicationName("ЭДО ЛДПР (Облачная версия)")
        app.setApplicationVersion("2.0")
        app.setStyle('Fusion')
        app.setFont(QFont("Segoe UI", 10))
        
        window = MainWindow()
        window.showMaximized()
        sys.exit(app.exec())

    main()

if __name__ == '__main__':
    # Это не запустится на Render
    # На Render запускает app.py
    pass
