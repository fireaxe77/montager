' Montage builder launcher (V5.5): starts the CURRENT montage.py with pythonw - no console window, always the latest code.
' Nothing stays running: it starts the app once and exits. 'python montage.py' keeps working exactly as before.
Option Explicit
Dim sh, fso, dir
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
On Error Resume Next
sh.Run "pythonw """ & dir & "\montage.py""", 0, False
If Err.Number <> 0 Then
  Err.Clear
  sh.Run "pyw -3 """ & dir & "\montage.py""", 0, False
  If Err.Number <> 0 Then MsgBox "pythonw / pyw not found. Install Python 3.12 from python.org (tick Add to PATH), then try again.", 16, "Montage builder"
End If
