@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem تشغيل البرنامج وإتاحته لباقي أجهزة الشبكة (http://عنوان-هذا-الجهاز:8765)
set CT_HOST=0.0.0.0
set CT_NO_BROWSER=1
echo عنوان هذا الجهاز على الشبكة (IPv4):
ipconfig | findstr /i "IPv4"
echo.
where python >nul 2>nul
if %errorlevel%==0 (python web_app.py) else (py web_app.py)
pause
