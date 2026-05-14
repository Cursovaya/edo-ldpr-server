#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ЭДО ЛДПР - Flask приложение для Render
"""

from edo_ldpr_cloud import app_flask, init_db, seed_database

# Инициализируем БД при старте
print("🔧 Инициализация базы данных...")
with app_flask.app_context():
    try:
        init_db()
        seed_database()
        print("✓ База данных готова")
    except Exception as e:
        print(f"⚠️ Ошибка БД: {e}")

# Главная переменная для Render/Gunicorn
app = app_flask

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
