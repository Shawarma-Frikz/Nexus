@echo off
title NEXUS Multimodal Digital Twin Launcher
cd /d "%~dp0"

echo ===================================================
echo   NEXUS AI Digital Twin - Automated System Launcher
echo ===================================================

:: Always use the project virtual environment. Create it on first launch.
if not exist "backend\venv\Scripts\python.exe" (
    echo [*] Creating the backend virtual environment...
    python -m venv backend\venv
    if errorlevel 1 (
        echo [ERROR] Could not create backend\venv. Install Python 3.10 or newer and retry.
        pause
        exit /b 1
    )
)
set "PYTHON_EXE=backend\venv\Scripts\python.exe"

:: Reuse an already-running NEXUS backend rather than starting a duplicate.
powershell -NoProfile -Command "try { $h=Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -TimeoutSec 2; $a=Invoke-RestMethod 'http://127.0.0.1:8000/attendance-api/api/health' -TimeoutSec 2; if ($h.system -eq 'NEXUS' -and $a.status -eq 'ok') { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo [OK] NEXUS backend is already responding on port 8000.
) else (
    netstat -ano -p tcp | findstr /R /C:":8000 .*LISTENING" >nul
    if not errorlevel 1 (
    echo [ERROR] Port 8000 is occupied by an older or separate server. Stop that server, then rerun this launcher.
        pause
        exit /b 1
    )

    :: Install backend packages once if this virtual environment is empty/incomplete.
    "%PYTHON_EXE%" -c "import fastapi, uvicorn, pydantic_settings, sqlalchemy, greenlet, aiosqlite, httpx, numpy, cv2, sounddevice, scipy, sklearn, firebase_admin; from sqlalchemy.ext.asyncio import create_async_engine; assert hasattr(cv2, 'FaceRecognizerSF_create')" >nul 2>&1
    if errorlevel 1 (
        echo [*] Installing missing backend packages. This can take a few minutes...
        "%PYTHON_EXE%" -m pip install --upgrade pip
        if errorlevel 1 (
            echo [ERROR] pip could not be prepared in backend\venv.
            pause
            exit /b 1
        )
        "%PYTHON_EXE%" -m pip uninstall -y opencv-python opencv-python-headless opencv-contrib-python
        "%PYTHON_EXE%" -m pip install -r backend\requirements.txt
        if errorlevel 1 (
            echo [ERROR] Backend package installation failed. See the error above.
            pause
            exit /b 1
        )
    )

    echo [*] Verifying the vision models...
    "%PYTHON_EXE%" ai/vision/download_models.py

    echo [*] Checking camera and microphone access...
    "%PYTHON_EXE%" verify_hardware.py

    echo [*] Launching NEXUS Backend and AI Services on port 8000...
    start "" /B "%PYTHON_EXE%" -m backend.app.main
    timeout /t 3 /nobreak >nul
)

:: Reuse the running dashboard, avoiding an EADDRINUSE error on repeat launches.
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing 'http://localhost:3000/attendance' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo [OK] Integrated NEXUS Attendance is already responding on port 3000; reusing it.
) else (
    netstat -ano -p tcp | findstr /R /C:":3000 .*LISTENING" >nul
    if not errorlevel 1 (
        echo [ERROR] Port 3000 is occupied by an older or separate frontend. Stop that frontend, then rerun this launcher.
        pause
        exit /b 1
    )
    echo [*] Launching NEXUS frontend on port 3000...
    start "" /B cmd /c "npm --prefix frontend run dev"
)

echo ===================================================
echo   NEXUS is starting in this terminal.
echo   Dashboard : http://localhost:3000
echo   API Docs  : http://127.0.0.1:8000/docs
echo   Wokwi simulation must be started separately.
echo ===================================================
timeout /t 2 /nobreak >nul
start "" http://localhost:3000
