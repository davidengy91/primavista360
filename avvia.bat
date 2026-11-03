@echo off
rem ===== PrimaVista 360 AI: doppio clic per avviare =====
cd /d "%~dp0"
title PrimaVista 360 AI

rem Prima volta: crea l'ambiente Python e installa le librerie
if not exist ".venv\Scripts\python.exe" (
  echo Prima installazione: preparo l'ambiente, ci vuole qualche minuto...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt
)
if not exist ".env" copy ".env.example" ".env" >nul

echo.
echo  PrimaVista 360 AI e' in funzione su http://127.0.0.1:8360
echo  Lascia aperta questa finestra mentre lavori. Per chiudere il programma: chiudi la finestra.
echo.
start "" http://127.0.0.1:8360
.venv\Scripts\python -m uvicorn app.server:app --host 127.0.0.1 --port 8360
pause
