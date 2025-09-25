' VBScript to run GitHub monitor completely silently
' No window will appear at all

Dim objShell, strPath, strPython, strScript, strLog

Set objShell = CreateObject("WScript.Shell")

strPath = "C:\Users\Josh\Projects\DuoAPI_Interaction"
strPython = strPath & "\.venv\Scripts\python.exe"
strScript = strPath & "\scripts\github_monitor.py"
strLog = strPath & "\.claude\monitor.log"

' Run command completely hidden (0 = hidden window)
objShell.Run """" & strPython & """ """ & strScript & """ --once >> """ & strLog & """ 2>&1", 0, False

Set objShell = Nothing