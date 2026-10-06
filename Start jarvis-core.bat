@echo off
rem ============================================================================
rem  Start jarvis-core.bat - double-click this to start Jarvis and open its page.
rem
rem  What it does, in this order, and every step can fail loudly:
rem    1. works out the Python command (py -3 if you have it, python otherwise)
rem    2. checks the port is free BEFORE starting anything, so a clash is a
rem       clear sentence instead of a Python traceback
rem    3. starts the server in its own window, which is the window to leave open
rem    4. asks the server whether it is listening yet, then opens the browser
rem
rem  There is deliberately no fixed wait anywhere in this file. A `timeout 5` is
rem  how these scripts break on a slow machine: the browser opens before the
rem  server is listening and the person sees "cannot connect" for no reason.
rem  The loop below asks the server and waits for a real answer.
rem ============================================================================

setlocal
title jarvis-core launcher
rem %~dp0 is the folder this .bat lives in, so it works from wherever it is
rem double-clicked, and settings.json is written beside it rather than in
rem C:\Windows or wherever the shell happened to be.
cd /d "%~dp0"

echo.
echo   Starting jarvis-core...
echo.

rem ---- 1. which Python? -----------------------------------------------------
set "PY=py -3"
%PY% -c "pass" >nul 2>&1
if not errorlevel 1 goto python_ok
set "PY=python"
%PY% -c "pass" >nul 2>&1
if not errorlevel 1 goto python_ok

echo   PROBLEM: Python was not found on this PC.
echo.
echo   Jarvis is written in Python and needs it. Install it from python.org
echo   (tick "Add python.exe to PATH" in the installer), then double-click
echo   this file again.
goto the_end

:python_ok

rem ---- 2. is the port already taken? ----------------------------------------
rem The owner also runs a bigger Jarvis on 4719, so this is the failure most
rem likely to happen. Ask the operating system whether that port answers,
rem before starting a server that could only print a traceback.
%PY% -c "import socket,sys;s=socket.socket();s.settimeout(0.3);sys.exit(1 if s.connect_ex(('127.0.0.1',4719))==0 else 0)"
if errorlevel 1 goto port_busy

rem ---- 3. start the server in its own window -------------------------------
echo   Starting the server in a second window. That is the window to leave open.
rem  The title has no brackets in it on purpose: cmd treats brackets in an
rem  unquoted command as grouping, and that is exactly the kind of thing that
rem  makes a launcher work on one PC and not another.
start "jarvis-core server - leave this open" cmd /k "%PY% -m jarvis_core"

rem ---- 4. wait for it to really answer, then open the page ------------------
echo   Waiting for it to answer...
rem  Keep trying to connect until one works, then exit 0: no fixed wait and no
rem  guessing how long the server needs. The socket's own half-second timeout
rem  is the pause between attempts, and the failure is caught rather than
rem  raised, so a port with nothing on it is a quiet "not yet" instead of a
rem  Python traceback. The ceiling is there only so this cannot spin forever;
rem  at about a second an attempt it is far longer than any real start-up.
%PY% -c "import socket,time,sys
for _ in range(2400):
    s=socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(('127.0.0.1',4719))
        s.close()
        sys.exit(0)
    except OSError:
        pass
sys.exit(1)"
if errorlevel 1 goto never_answered

echo.
echo   It is running. Opening the page in your browser now.
start "" "http://127.0.0.1:4719"
echo.
echo   Type in the window that just opened. You can close THIS window.
echo   The other one, called "jarvis-core server - leave this open", is what
echo   keeps Jarvis running. Closing that one stops it.
goto the_end

rem ---- the port is already in use, before we started anything --------------
:port_busy
echo   PROBLEM: Port 4719 is already in use - something else is running there.
echo.
echo   The likely cause is the bigger Jarvis, which also uses 4719.
echo   Close it, or start this one on a free port with:
echo.
echo       py -3 -m jarvis_core --port 4720
echo.
echo   Type that in PowerShell, in this folder. The page is then at
echo   http://127.0.0.1:4720 instead of 4719.
goto the_end

rem ---- it started but never answered ---------------------------------------
:never_answered
echo   PROBLEM: the server window opened, but it did not start answering.
echo.
echo   Look at the other window, called "jarvis-core server - leave this open".
echo   Whatever went wrong is printed there in plain words - usually a line in
echo   settings.json, or the model name.
goto the_end

:the_end
echo.
echo   This window is staying open so you can read the message above.
echo   Press any key to close it.
pause >nul
endlocal
