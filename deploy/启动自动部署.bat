@echo off
chcp 936 >nul
title 百灵医生 - 自动部署守护
cd /d "%~dp0.."
echo ============================================
echo   百灵医生 - 自动部署守护
echo   改完代码保存后，静默 8 秒自动部署到虚拟机
echo   关闭本窗口即停止监听
echo ============================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0auto_watch.ps1" %*
echo.
echo 守护进程已结束。
pause
