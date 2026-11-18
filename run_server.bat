@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem وضع الخادم خلف نفق HTTPS (للجوال والإشعارات): لا يفتح المتصفح ويفعّل الكوكيز الآمنة
set CT_HTTPS=1
set CT_NO_BROWSER=1
rem الخادم يستمع على هذا الجهاز فقط، والنفق (Tailscale/Cloudflare) هو من يوصّله للإنترنت
rem بريد التواصل لخدمة الإشعارات (يُنصح بوضع بريدك الحقيقي)
set CT_CONTACT=mailto:admin@example.com
where python >nul 2>nul
if %errorlevel%==0 (python web_app.py) else (py web_app.py)
pause
