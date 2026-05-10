#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ЭДО ЛДПР - Сервер для Render.com
Flask + PostgreSQL + HTML-интерфейс для WebView клиентов
"""

import os
import sys
import json
import uuid
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template_string, request, redirect, url_for, session, flash, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# CORS для WebView клиентов
CORS(app, supports_credentials=True, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Authorization", "Content-Type"]
    }
})

# PostgreSQL на Render
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    # Локальная разработка
    DATABASE_URL = 'postgresql://postgres:postgres@localhost:5432/edo_ldpr'

# ============================================================
# БАЗА ДАННЫХ
# ============================================================
def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            uid TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'executor',
            department_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS departments (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            head_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            priority TEXT DEFAULT 'Нормальный',
            status TEXT DEFAULT 'На утверждении',
            created_by TEXT,
            creator_name TEXT,
            assigned_department_id TEXT,
            assigned_executor_id TEXT,
            deadline TEXT,
            result JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS order_history (
            id SERIAL PRIMARY KEY,
            order_id TEXT REFERENCES orders(id) ON DELETE CASCADE,
            action TEXT,
            user_name TEXT,
            user_role TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    cur.close()
    conn.close()

def seed_database():
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()['count'] > 0:
        cur.close()
        conn.close()
        return
    
    # Отделы
    departments = [
        ('dept-1', 'Центральный аппарат', None),
        ('dept-2', 'Юридический отдел', None),
        ('dept-3', 'Организационный отдел', None),
    ]
    for d in departments:
        cur.execute('''
            INSERT INTO departments (id, name, head_id) VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        ''', d)
    
    # Пользователи
    users = [
        ('u-admin', 'Администратор', 'admin@ldpr.ru', 'admin', generate_password_hash('admin123'), 'admin', None),
        ('u-sec', 'Секретарь', 'sec@ldpr.ru', 'secretary', generate_password_hash('sec123'), 'secretary', None),
        ('u-head-ca', 'Руководитель ЦА', 'headca@ldpr.ru', 'head_central', generate_password_hash('head123'), 'head_central', 'dept-1'),
        ('u-head-dept', 'Начальник отдела', 'head@ldpr.ru', 'head_department', generate_password_hash('head123'), 'head_department', 'dept-2'),
        ('u-ast', 'Помощник', 'ast@ldpr.ru', 'assistant', generate_password_hash('ast123'), 'assistant', None),
        ('u-exec', 'Исполнитель', 'exec@ldpr.ru', 'executor', generate_password_hash('exec123'), 'executor', 'dept-2'),
    ]
    for u in users:
        cur.execute('''
            INSERT INTO users (uid, full_name, email, username, password, role, department_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (username) DO UPDATE SET 
                password = EXCLUDED.password,
                role = EXCLUDED.role,
                full_name = EXCLUDED.full_name
        ''', u)
    
    cur.execute("UPDATE departments SET head_id = 'u-head-ca' WHERE id = 'dept-1'")
    cur.execute("UPDATE departments SET head_id = 'u-head-dept' WHERE id = 'dept-2'")
    
    conn.commit()
    cur.close()
    conn.close()

# ============================================================
# МОДЕЛИ
# ============================================================
class UserModel:
    @staticmethod
    def get_by_id(uid):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE uid = %s", (uid,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        return dict(user) if user else None
    
    @staticmethod
    def get_by_username(username):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        return dict(user) if user else None
    
    @staticmethod
    def get_all():
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users ORDER BY created_at DESC")
        users = [dict(u) for u in cur.fetchall()]
        cur.close()
        conn.close()
        return users
    
    @staticmethod
    def get_by_department(dept_id):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE department_id = %s", (dept_id,))
        users = [dict(u) for u in cur.fetchall()]
        cur.close()
        conn.close()
        return users

class DepartmentModel:
    @staticmethod
    def get_all():
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM departments ORDER BY created_at DESC")
        depts = [dict(d) for d in cur.fetchall()]
        cur.close()
        conn.close()
        return depts
    
    @staticmethod
    def get_by_id(dept_id):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM departments WHERE id = %s", (dept_id,))
        dept = cur.fetchone()
        cur.close()
        conn.close()
        return dict(dept) if dept else None
    
    @staticmethod
    def create(dept_id, name):
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO departments (id, name) VALUES (%s, %s)", (dept_id, name))
            conn.commit()
            cur.close()
            conn.close()
            return True
        except:
            cur.close()
            conn.close()
            return False
    
    @staticmethod
    def delete(dept_id):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM departments WHERE id = %s", (dept_id,))
        conn.commit()
        cur.close()
        conn.close()

class OrderModel:
    STATUSES = ['Черновик', 'На утверждении', 'Утверждено', 'В отделе', 
                'Назначен исполнитель', 'В работе', 'Готово к проверке', 
                'Подтверждено', 'На доработке', 'Закрыто', 'Отклонено']
    PRIORITIES = ['Низкий', 'Нормальный', 'Высокий', 'Срочный']
    
    @staticmethod
    def get_by_id(order_id):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
        order = cur.fetchone()
        cur.close()
        conn.close()
        return dict(order) if order else None
    
    @staticmethod
    def get_by_user(uid, role, department_id=None):
        conn = get_db()
        cur = conn.cursor()
        
        if role == 'admin':
            cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
        elif role == 'assistant':
            cur.execute("SELECT * FROM orders WHERE created_by = %s ORDER BY created_at DESC", (uid,))
        elif role == 'head_department' and department_id:
            cur.execute("SELECT * FROM orders WHERE assigned_department_id = %s ORDER BY created_at DESC", (department_id,))
        elif role == 'executor':
            cur.execute("SELECT * FROM orders WHERE assigned_executor_id = %s ORDER BY created_at DESC", (uid,))
        else:
            cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
        
        orders = [dict(o) for o in cur.fetchall()]
        cur.close()
        conn.close()
        return orders
    
    @staticmethod
    def get_by_department(dept_id):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM orders WHERE assigned_department_id = %s ORDER BY created_at DESC", (dept_id,))
        orders = [dict(o) for o in cur.fetchall()]
        cur.close()
        conn.close()
        return orders
    
    @staticmethod
    def create(order_id, title, content, priority, status, created_by, creator_name, deadline=None):
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO orders (id, title, content, priority, status, created_by, creator_name, deadline)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (order_id, title, content, priority, status, created_by, creator_name, deadline))
        conn.commit()
        cur.close()
        conn.close()
    
    @staticmethod
    def update(order_id, **kwargs):
        conn = get_db()
        cur = conn.cursor()
        
        set_clause = ', '.join([f"{k} = %s" for k in kwargs.keys()])
        values = list(kwargs.values()) + [order_id]
        
        cur.execute(f"UPDATE orders SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = %s", values)
        conn.commit()
        cur.close()
        conn.close()

class OrderHistoryModel:
    @staticmethod
    def add(order_id, action, user_name, user_role, details=''):
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO order_history (order_id, action, user_name, user_role, details)
            VALUES (%s, %s, %s, %s, %s)
        ''', (order_id, action, user_name, user_role, details))
        conn.commit()
        cur.close()
        conn.close()
    
    @staticmethod
    def get_by_order(order_id):
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            SELECT * FROM order_history 
            WHERE order_id = %s 
            ORDER BY created_at DESC
        ''', (order_id,))
        history = [dict(h) for h in cur.fetchall()]
        cur.close()
        conn.close()
        return history

# ============================================================
# HTML ШАБЛОНЫ
# ============================================================
BASE_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}ЭДО ЛДПР{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css">
    <style>
        :root { --ldpr-blue: #003399; --ldpr-gold: #FFD700; }
        body { font-family: 'Segoe UI', system-ui, sans-serif; background: #f8f9fa; }
        .navbar { background: var(--ldpr-blue); }
        .sidebar { background: white; min-height: calc(100vh - 56px); box-shadow: 2px 0 10px rgba(0,0,0,0.05); }
        .sidebar .nav-link { color: #555; border-radius: 10px; margin: 3px 8px; padding: 10px 16px; }
        .sidebar .nav-link:hover { background: #eef; color: var(--ldpr-blue); }
        .sidebar .nav-link.active { background: var(--ldpr-blue); color: white !important; }
        .card { border: none; border-radius: 18px; box-shadow: 0 2px 16px rgba(0,0,0,0.05); }
        .badge-status { font-size: 0.75rem; font-weight: 600; padding: 6px 14px; border-radius: 20px; }
        .btn-primary { background: var(--ldpr-blue); border: none; }
        .btn-primary:hover { background: #002266; }
        .table th { font-size: 0.7rem; font-weight: 700; text-transform: uppercase; color: #888; }
    </style>
</head>
<body>
    {% if current_user %}
    <nav class="navbar navbar-dark">
        <div class="container-fluid">
            <a class="navbar-brand fw-bold" href="/"><i class="bi bi-building me-2"></i>ЭДО ЛДПР</a>
            <div class="d-flex align-items-center gap-3">
                <span class="text-light">{{ current_user.full_name }}</span>
                <a href="/logout" class="btn btn-outline-light btn-sm"><i class="bi bi-box-arrow-right"></i></a>
            </div>
        </div>
    </nav>
    <div class="container-fluid">
        <div class="row">
            <div class="col-md-2 sidebar py-3">
                <div class="text-center mb-4">
                    <div class="bg-primary text-white rounded-circle d-inline-flex align-items-center justify-content-center" style="width:64px;height:64px;font-size:1.5rem;font-weight:700;">{{ current_user.full_name[0] }}</div>
                    <p class="mt-2 mb-0 fw-bold">{{ current_user.full_name }}</p>
                    <small class="text-muted">{{ current_user.role }}</small>
                </div>
                <nav class="nav flex-column">
                    <a class="nav-link {{ 'active' if request.path == '/' }}" href="/"><i class="bi bi-speedometer2 me-2"></i>Рабочий стол</a>
                    <a class="nav-link {{ 'active' if '/orders' in request.path }}" href="/orders"><i class="bi bi-file-text me-2"></i>Распоряжения</a>
                    {% if current_user.role in ['head_department', 'admin'] %}
                    <a class="nav-link {{ 'active' if request.path == '/department' }}" href="/department"><i class="bi bi-people me-2"></i>Отдел</a>
                    {% endif %}
                    {% if current_user.role == 'admin' %}
                    <a class="nav-link {{ 'active' if request.path == '/admin' }}" href="/admin"><i class="bi bi-gear me-2"></i>Админ</a>
                    {% endif %}
                </nav>
            </div>
            <div class="col-md-10 p-4">
                {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                {% for cat, msg in messages %}
                <div class="alert alert-{{ cat }} alert-dismissible fade show">{{ msg }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>
                {% endfor %}
                {% endif %}
                {% endwith %}
                {% block content %}{% endblock %}
            </div>
        </div>
    </div>
    {% else %}
    {% block full_content %}{% endblock %}
    {% endif %}
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>'''

LOGIN_TEMPLATE = '''{% extends "base.html" %}
{% block full_content %}
<style>
    .login-page {
        background: linear-gradient(135deg, #003399 0%, #001a4d 100%);
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .login-card {
        background: white;
        padding: 40px;
        border-radius: 20px;
        box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        width: 100%;
        max-width: 400px;
    }
    .login-logo {
        text-align: center;
        margin-bottom: 30px;
    }
    .login-logo h1 {
        color: #003399;
        font-weight: 900;
        margin: 0;
    }
    .login-logo p {
        color: #666;
        font-size: 14px;
        margin: 5px 0 0 0;
    }
    .form-control { padding: 12px 15px; border-radius: 10px; border: 2px solid #e0e0e0; }
    .form-control:focus { border-color: #003399; box-shadow: none; }
    .btn-login {
        background: #003399;
        color: white;
        padding: 12px;
        border-radius: 10px;
        font-weight: 600;
        width: 100%;
        border: none;
    }
    .btn-login:hover { background: #002266; }
</style>
<div class="login-page">
    <div class="login-card">
        <div class="login-logo">
            <h1>ЛДПР</h1>
            <p>Электронный документооборот</p>
        </div>
        <form method="POST">
            <div class="mb-3">
                <input type="text" name="username" class="form-control" placeholder="Логин" required>
            </div>
            <div class="mb-4">
                <input type="password" name="password" class="form-control" placeholder="Пароль" required>
            </div>
            <button type="submit" class="btn btn-login">Войти</button>
        </form>
        <div class="mt-3 text-center">
            <small class="text-muted">Тестовые данные:<br>admin / admin123 | secretary / sec123 | head_central / head123</small>
        </div>
    </div>
</div>
{% endblock %}'''

# Шаблоны dashboard, orders, order_details, admin, department...
# (сокращенно для примера, полные версии можно взять из edo_ldpr_desktop.py)

DASHBOARD_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Рабочий стол - ЭДО ЛДПР{% endblock %}
{% block content %}
<h2 class="fw-bold mb-4">Рабочий стол</h2>
<div class="row">
    <div class="col-md-12">
        <div class="card p-4">
            <h5 class="fw-bold mb-3">Последние распоряжения</h5>
            <table class="table table-hover">
                <thead><tr><th>Название</th><th>Статус</th><th>Срок</th><th>Автор</th></tr></thead>
                <tbody>
                    {% for o in orders[:5] %}
                    <tr onclick="location.href='/orders/{{ o.id }}'" style="cursor:pointer">
                        <td><strong>{{ o.title }}</strong></td>
                        <td><span class="badge badge-status bg-primary">{{ o.status }}</span></td>
                        <td>{{ o.deadline or '-' }}</td>
                        <td>{{ o.creator_name }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}'''

ORDERS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Распоряжения - ЭДО ЛДПР{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h2 class="fw-bold mb-0">Распоряжения</h2>
    {% if current_user.role == 'assistant' %}
    <button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#createModal">+ Новое</button>
    {% endif %}
</div>
<div class="card">
    <table class="table table-hover mb-0">
        <thead><tr><th>Документ</th><th>Приоритет</th><th>Статус</th><th>Срок</th><th>Автор</th></tr></thead>
        <tbody>
            {% for o in orders %}
            <tr onclick="location.href='/orders/{{ o.id }}'" style="cursor:pointer">
                <td><strong>{{ o.title }}</strong><br><small class="text-muted">#{{ o.id[:8] }}</small></td>
                <td>{{ o.priority }}</td>
                <td><span class="badge badge-status bg-primary">{{ o.status }}</span></td>
                <td>{{ o.deadline or '-' }}</td>
                <td>{{ o.creator_name }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}'''

TEMPLATES = {
    'base.html': BASE_TEMPLATE,
    'login.html': LOGIN_TEMPLATE,
    'dashboard.html': DASHBOARD_TEMPLATE,
    'orders.html': ORDERS_TEMPLATE,
}

from jinja2 import DictLoader
app.jinja_loader = DictLoader(TEMPLATES)

# ============================================================
# ДЕКОРАТОРЫ
# ============================================================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_role' not in session or session['user_role'] not in roles:
                flash('Недостаточно прав', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator

@app.context_processor
def inject_user():
    if 'user_id' in session:
        user = UserModel.get_by_id(session['user_id'])
        if user:
            return {'current_user': user}
    return {'current_user': None}

# ============================================================
# МАРШРУТЫ
# ============================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        user = UserModel.get_by_username(username)
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['uid']
            session['user_role'] = user['role']
            return redirect(url_for('dashboard'))
        
        flash('Неверный логин или пароль', 'danger')
    
    return render_template_string(TEMPLATES['login.html'])

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    orders = OrderModel.get_by_user(
        session['user_id'],
        session['user_role'],
        session.get('department_id')
    )
    return render_template_string(TEMPLATES['dashboard.html'], orders=orders)

@app.route('/orders')
@login_required
def orders():
    orders = OrderModel.get_by_user(
        session['user_id'],
        session['user_role'],
        session.get('department_id')
    )
    return render_template_string(TEMPLATES['orders.html'], orders=orders, statuses=OrderModel.STATUSES)

@app.route('/api/orders')
def api_orders():
    """API для клиентов"""
    user_id = request.args.get('user_id')
    role = request.args.get('role')
    dept_id = request.args.get('department_id')
    
    orders = OrderModel.get_by_user(user_id, role, dept_id)
    return jsonify([dict(o) for o in orders])

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})

# ============================================================
# ТОЧКА ВХОДА
# ============================================================
if __name__ == '__main__':
    init_db()
    seed_database()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
