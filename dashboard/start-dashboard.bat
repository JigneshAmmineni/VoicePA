@echo off
rem VoicePA dashboard launcher.
rem Starts the server if it isn't already running (a second instance exits
rem silently when the port is taken), waits until it answers, then opens the
rem dashboard in the browser. Uses the project venv so FastAPI and the Agent
rem SDK are on the path. The server logs to logs\server.log.
if "%DASH_PORT%"=="" set DASH_PORT=7789
start "" /min "%~dp0..\.venv\Scripts\pythonw.exe" "%~dp0server.py"
for /l %%i in (1,1,40) do (
  curl -s -m 1 -o nul http://127.0.0.1:%DASH_PORT%/api/ping && goto :open
  ping -n 2 127.0.0.1 >nul
)
echo the dashboard did not come up within 40 s. see logs\server.log
pause
exit /b 1
:open
start "" http://127.0.0.1:%DASH_PORT%
