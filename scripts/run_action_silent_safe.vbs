' VBScript to run autonomous action completely silently with error handling
' No window will appear at all, even on errors

On Error Resume Next

Dim objShell, objFSO, strPath, strPython, strScript, strLog
Dim strCommand

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

strPath = "C:\Users\Josh\Projects\DuoAPI_Interaction"
strPython = strPath & "\.venv\Scripts\python.exe"
strScript = strPath & "\scripts\autonomous_action.py"
strLog = strPath & "\.claude\action_log.txt"

' Check if Python venv exists, otherwise try uv run
If objFSO.FileExists(strPython) Then
    ' Use venv Python
    strCommand = """" & strPython & """ """ & strScript & """ >> """ & strLog & """ 2>&1"
Else
    ' Fallback to uv run
    strCommand = "cmd /c cd /d """ & strPath & """ && uv run python scripts/autonomous_action.py >> .claude\action_log.txt 2>&1"
End If

' Run command completely hidden (0 = hidden window)
objShell.Run strCommand, 0, False

Set objShell = Nothing
Set objFSO = Nothing