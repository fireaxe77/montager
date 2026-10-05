' Old launcher name (V5.5 desktop shortcuts point here): forwards to Montager.vbs.
Option Explicit
Dim sh, fso
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
sh.Run "wscript """ & fso.GetParentFolderName(WScript.ScriptFullName) & "\Montager.vbs""", 0, False
