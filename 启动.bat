@echo off
chcp 65001 >nul
title 学习通自动连播
rem 以源码方式启动(需要已安装 Python 与 requirements.txt 里的依赖)
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
  python "%~dp0main.py" %*
) else (
  py -3 "%~dp0main.py" %*
)
pause
