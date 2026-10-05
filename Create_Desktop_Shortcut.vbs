' Creates the shortcut "Montager" (app icon + its own taskbar identity, AppUserModelID fireaxe.montager) on the Desktop and in the
' Start menu; both start Montager.vbs. Double-click this file once (again after updating from V5.55: it replaces "Montage builder").
Option Explicit
Const APP_ID = "fireaxe.montager"
Dim sh, fso, dir, paths, p, lnk, old
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
paths = Array(sh.SpecialFolders("Desktop") & "\Montager.lnk", sh.SpecialFolders("Programs") & "\Montager.lnk")
For Each p In paths
  Set lnk = sh.CreateShortcut(p)
  lnk.TargetPath = sh.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\wscript.exe"
  lnk.Arguments = """" & dir & "\Montager.vbs"""
  lnk.WorkingDirectory = dir
  lnk.IconLocation = dir & "\montage.ico"
  lnk.Description = "Montager (Valorant / CS2 kill montages)"
  lnk.Save
  ' same AppUserModelID as the app sets at startup, so the taskbar shows Montager's name and icon (not pythonw's)
  sh.Run "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & dir & "\Set_Shortcut_AppId.ps1"" -Lnk """ & p & """ -Id " & APP_ID, 0, True
Next
old = sh.SpecialFolders("Desktop") & "\Montage builder.lnk"
If fso.FileExists(old) Then fso.DeleteFile old
old = sh.SpecialFolders("Programs") & "\Montage builder.lnk"
If fso.FileExists(old) Then fso.DeleteFile old
MsgBox "Shortcut created: Montager (Desktop + Start menu)", 64, "Montager"
