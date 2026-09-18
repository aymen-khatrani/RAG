@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Environnement absent. Suivre le README pour creer .venv et installer les dependances.
    pause
    exit /b 1
)
rem Ecoute uniquement sur la boucle locale. Le jeton Jupyter reste active.
rem Pas de verification de mises a jour ni d'actualites de JupyterLab.
".venv\Scripts\python.exe" -m jupyterlab --ServerApp.ip=127.0.0.1 --ServerApp.open_browser=True --LabApp.check_for_updates_class=jupyterlab.NeverCheckForUpdate --LabApp.news_url="" Pipeline_freinage_local.ipynb
endlocal

