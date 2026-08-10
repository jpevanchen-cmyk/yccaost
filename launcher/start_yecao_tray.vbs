' Yecao tray launcher (no command window). ASCII only for Windows Script Host.

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
launcherDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectRoot = fso.GetParentFolderName(launcherDir)
pythonw = projectRoot & "\.venv\Scripts\pythonw.exe"

If Not fso.FileExists(pythonw) Then
    MsgBox "Missing pythonw:" & vbCrLf & pythonw & vbCrLf & vbCrLf & "Create .venv in the project folder first.", vbCritical, "Yecao Tray"
    WScript.Quit 1
End If

shell.CurrentDirectory = projectRoot
cmd = """" & pythonw & """ -m launcher.yecao_tray"
shell.Run cmd, 0, False
