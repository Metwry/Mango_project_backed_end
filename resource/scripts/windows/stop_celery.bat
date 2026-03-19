@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0stop_celery.ps1" %*
