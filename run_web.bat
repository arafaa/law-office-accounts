@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem يعمل البرنامج على هذا الجهاز وعلى باقي أجهزة الشبكة (يلزم تسجيل الدخول). لحصره على هذا الجهاز احذف السطر التالي:
set CT_HOST=0.0.0.0
where python >nul 2>nul
if %errorlevel%==0 (python web_app.py) else (py web_app.py)
pause
