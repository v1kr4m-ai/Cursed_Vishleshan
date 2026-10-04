@echo off
REM Starts the app without a console window. Errors go to app.log; use Cursed_Vishleshan_debug.bat to see them live.
start "" pythonw "%~dp0app.py"
