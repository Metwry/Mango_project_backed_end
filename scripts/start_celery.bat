@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0start_celery.ps1" -EnvName Back_end_project -Targets all -WithBeat -FollowLogs %*
