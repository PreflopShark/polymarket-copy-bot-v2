@echo off
echo ========================================
echo Polymarket Copy Bot - Config Switcher
echo ========================================
echo.
echo Current mode:
if exist .env.current (
    type .env.current
) else (
    echo Unknown - no .env.current file
)
echo.
echo 1. AGGRESSIVE (no filters, 3%% slippage, paper trade)
echo 2. SAFE (filters on, 5%% slippage, live trade)
echo 3. Exit
echo.
set /p choice="Select mode (1/2/3): "

if "%choice%"=="1" (
    copy /Y .env.aggressive .env >nul
    echo AGGRESSIVE > .env.current
    echo.
    echo [SWITCHED TO AGGRESSIVE MODE]
    echo - Copy ALL trades (no filters)
    echo - 3%% slippage
    echo - PAPER TRADING (dry run)
    echo.
)
if "%choice%"=="2" (
    copy /Y .env.safe .env >nul
    echo SAFE > .env.current
    echo.
    echo [SWITCHED TO SAFE MODE]
    echo - Min trade filter: $50
    echo - Price filter: 15%%-85%%
    echo - Skip opposite side: ON
    echo - 5%% slippage
    echo - LIVE TRADING
    echo.
)
if "%choice%"=="3" (
    exit /b
)

echo Done! Restart the bot to apply changes.
pause
