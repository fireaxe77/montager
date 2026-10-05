' Creates the desktop shortcut 'Montage builder' (app icon) that starts Montage.vbs. Double-click this file once.
Option Explicit
Dim sh, fso, dir, lnk
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set lnk = sh.CreateShortcut(sh.SpecialFolders("Desktop") & "\Montage builder.lnk")
lnk.TargetPath = sh.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\wscript.exe"
lnk.Arguments = """" & dir & "\Montage.vbs"""
lnk.WorkingDirectory = dir
lnk.IconLocation = dir & "\montage.ico"
lnk.Description = "Montage builder (Valorant / CS2)"
lnk.Save
MsgBox "Desktop shortcut created: Montage builder", 64, "Montage builder"
