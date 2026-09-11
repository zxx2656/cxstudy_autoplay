@echo off
chcp 65001 >nul
title Build CxAuto
rem ============================================================
rem  学习通自动连播 —— 一键打包脚本
rem  方式: PyInstaller onedir(高效: 启动快、体积可控、不额外解压)
rem  产物: dist\CxAuto\CxAuto.exe
rem  注意: 不要排除 email —— urllib.request 依赖它, 排除后程序无法启动
rem ============================================================
set HERE=%~dp0
set OUT=%HERE%dist\CxAuto

echo ==== 清理旧产物 ====
if exist "%HERE%dist" rmdir /s /q "%HERE%dist"
if exist "%HERE%build" rmdir /s /q "%HERE%build"

echo ==== 开始打包 ====
python -m PyInstaller --noconfirm --clean ^
  --name CxAuto ^
  --onedir ^
  --noconsole ^
  --icon "%HERE%cxauto.ico" ^
  --hidden-import pystray._win32 ^
  --exclude-module tkinter ^
  --exclude-module playwright ^
  --exclude-module numpy ^
  --exclude-module unittest ^
  --exclude-module pydoc ^
  --exclude-module doctest ^
  --exclude-module sqlite3 ^
  --exclude-module bz2 ^
  --exclude-module lzma ^
  --exclude-module xmlrpc ^
  --exclude-module ssl ^
  --exclude-module _ssl ^
  --exclude-module _hashlib ^
  --distpath "%HERE%dist" ^
  --workpath "%HERE%build" ^
  --specpath "%HERE%" ^
  "%HERE%main.py"

echo ==== 裁剪用不到的 PIL 二进制(只保留托盘图标所需) ====
del /q "%OUT%\_internal\PIL\_avif*.pyd" 2>nul
del /q "%OUT%\_internal\PIL\_imagingft*.pyd" 2>nul
del /q "%OUT%\_internal\PIL\_webp*.pyd" 2>nul
del /q "%OUT%\_internal\PIL\_imagingcms*.pyd" 2>nul
del /q "%OUT%\_internal\PIL\_imagingmath*.pyd" 2>nul
del /q "%OUT%\_internal\PIL\_imagingtk*.pyd" 2>nul

echo ==== 完成, 产物在 %OUT% ====
pause
