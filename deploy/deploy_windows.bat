@echo off
REM market_brief/deploy/deploy_windows.bat — market_brief_v1.0.0
REM Windows -> EC2 deploy. The icacls permission fix on the .pem is the FIRST
REM step (per convention) or ssh/scp will reject the key as too-open.
REM
REM Edit the four vars below, then double-click or run from cmd.

setlocal

REM ----- EDIT THESE ----------------------------------------------------------
set PEM=C:\options_trader\tx-9.pem
set HOST=ubuntu@3.142.95.131
set TARBALL=market_brief_v1.tar.gz
set REMOTE_DIR=/home/ubuntu
REM ---------------------------------------------------------------------------

echo === Step 1: fix .pem permissions (icacls) ===
icacls "%PEM%" /inheritance:r
icacls "%PEM%" /grant:r "%USERNAME%:R"
if errorlevel 1 (
    echo icacls failed - aborting.
    exit /b 1
)

echo === Step 2: copy tarball to host ===
scp -i "%PEM%" "%TARBALL%" "%HOST%:%REMOTE_DIR%/"
if errorlevel 1 (
    echo scp failed - aborting.
    exit /b 1
)

echo === Step 3: untar + run on-box installer over ssh ===
ssh -i "%PEM%" "%HOST%" "cd %REMOTE_DIR% && tar xzf %TARBALL% && cd market_brief && chmod +x install.sh && ./install.sh --local"

echo === Done. Edit ~/market-brief/.env on the host with your keys. ===
endlocal
