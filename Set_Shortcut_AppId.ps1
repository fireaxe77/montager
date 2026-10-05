# Sets the AppUserModelID of a .lnk shortcut (used by Create_Desktop_Shortcut.vbs).
param([Parameter(Mandatory = $true)][string]$Lnk, [string]$Id = "fireaxe.montager")
$src = @"
using System;
using System.Runtime.InteropServices;
public static class ShortcutAppId {
  [StructLayout(LayoutKind.Sequential, Pack = 4)]
  struct PROPERTYKEY { public Guid fmtid; public uint pid; }
  [StructLayout(LayoutKind.Explicit, Size = 16)]
  struct PROPVARIANT { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; }
  [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
  interface IPropertyStore {
    void GetCount(out uint c);
    void GetAt(uint i, out PROPERTYKEY k);
    void GetValue(ref PROPERTYKEY k, out PROPVARIANT v);
    void SetValue(ref PROPERTYKEY k, ref PROPVARIANT v);
    void Commit();
  }
  [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("0000010b-0000-0000-C000-000000000046")]
  interface IPersistFile {
    void GetClassID(out Guid g);
    [PreserveSig] int IsDirty();
    void Load([MarshalAs(UnmanagedType.LPWStr)] string f, uint mode);
    void Save([MarshalAs(UnmanagedType.LPWStr)] string f, [MarshalAs(UnmanagedType.Bool)] bool remember);
    void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string f);
    void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string f);
  }
  [ComImport, Guid("00021401-0000-0000-C000-000000000046")] class CShellLink { }
  public static void Set(string path, string id) {
    object o = new CShellLink();
    ((IPersistFile)o).Load(path, 2);
    IPropertyStore ps = (IPropertyStore)o;
    PROPERTYKEY key = new PROPERTYKEY(); key.fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"); key.pid = 5;
    PROPVARIANT v = new PROPVARIANT(); v.vt = 31; v.p = Marshal.StringToCoTaskMemUni(id);
    ps.SetValue(ref key, ref v);
    ps.Commit();
    ((IPersistFile)o).Save(path, true);
  }
}
"@
Add-Type -TypeDefinition $src
[ShortcutAppId]::Set($Lnk, $Id)
