@echo off
rem Local preview. Do not open site\index.html by double-click: its links start with "/",
rem which a browser reads as the C: drive when there is no web server.
cd /d "%~dp0site"
start "" http://localhost:8765/
python -m http.server 8765 --bind 127.0.0.1
