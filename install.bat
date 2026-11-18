@echo off
chcp 65001 >nul
echo تثبيت المكتبات المطلوبة (مرة واحدة فقط)...
python -m pip install flask openpyxl pywebpush waitress
echo.
echo تم. الآن شغّل run_web.bat
pause
