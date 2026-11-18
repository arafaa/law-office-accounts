@echo off
chcp 65001 >nul
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo شغّل هذا الملف بزر الفأرة الأيمن ثم "تشغيل كمسؤول" ^(Run as administrator^)
  pause
  exit /b
)
netsh advfirewall firewall delete rule name="CaseTracker 8765" >nul 2>&1
netsh advfirewall firewall add rule name="CaseTracker 8765" dir=in action=allow protocol=TCP localport=8765 profile=any remoteip=localsubnet
echo.
echo تمت إتاحة المنفذ 8765 لأجهزة شبكتك المحلية فقط ^(وليس للإنترنت^).
pause
