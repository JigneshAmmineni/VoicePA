@echo off
rem VoicePA dashboard stopper. Double-click to stop the server on DASH_PORT.
rem Acts only if whatever answers on the port identifies itself as this dashboard
rem (/api/ping says "app":"voicepa"); anything else on the port is left alone.
rem Asks it to shut down gracefully, waits up to 10 s, then kills the process tree
rem (the Claude Code child included) if it is still there.
setlocal
if "%DASH_PORT%"=="" set DASH_PORT=7789
set URL=http://127.0.0.1:%DASH_PORT%

set PID=
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%DASH_PORT% .*LISTENING"') do set PID=%%p
if "%PID%"=="" (
  echo nothing is listening on port %DASH_PORT%: the dashboard is not running.
  goto :done
)

curl -s -m 3 %URL%/api/ping | findstr /c:"\"app\":\"voicepa\"" >nul
if errorlevel 1 (
  echo port %DASH_PORT% is in use by PID %PID%, but it is not the VoicePA dashboard. left alone.
  goto :done
)

echo asking the dashboard ^(PID %PID%^) to shut down...
curl -s -m 5 -X POST %URL%/api/shutdown >nul

for /l %%i in (1,1,10) do (
  tasklist /fi "PID eq %PID%" /nh | findstr /c:"%PID%" >nul || goto :stopped
  ping -n 2 127.0.0.1 >nul
)
echo still running after 10 s: killing PID %PID% and its children.
taskkill /pid %PID% /t /f >nul
goto :done

:stopped
echo dashboard stopped.

:done
ping -n 4 127.0.0.1 >nul
endlocal
