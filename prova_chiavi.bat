@echo off
rem Doppio clic: controlla che le chiavi API nel file .env funzionino (gratis).
cd /d "%~dp0"
.venv\Scripts\python test\test_chiavi.py
pause
