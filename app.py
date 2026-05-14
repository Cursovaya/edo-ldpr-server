#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ЭДО ЛДПР - Flask приложение для Render
"""

from edo_ldpr_cloud import app_flask

# Главная переменная для Render/Gunicorn
app = app_flask

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)