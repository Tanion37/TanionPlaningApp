# Creates Desktop + Start Menu shortcuts for TanionPlaning with calendar .ico
# and AppUserModelID so the pinned taskbar icon matches the running window.

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$appId = 'Tanion37.TanionPlaning'
$ico = Join-Path $root 'assets\app_icon.ico'

Push-Location $root
try {
    py -3 -c "from app.icons import ensure_app_icon_ico; print(ensure_app_icon_ico())" | Out-Null
} finally {
    Pop-Location
}

if (-not (Test-Path $ico)) {
    throw "Icon not found: $ico"
}

# Prefer real pythonw.exe — AppUserModelID / pin work better than the pyw launcher.
$pyw = $null
foreach ($candidate in @(
        (Get-Command pythonw -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\pythonw.exe'),
        'C:\Python314\pythonw.exe',
        (Get-Command pyw -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
    )) {
    if ($candidate -and (Test-Path $candidate)) {
        $pyw = $candidate
        break
    }
}
if (-not $pyw) {
    throw 'pythonw/pyw not found. Install Python with pythonw.exe.'
}

$launchArgs = if ($pyw -match '[\\/]pyw\.exe$') { '-3 -m app' } else { '-m app' }

if (-not ('LnkAppId' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class LnkAppId
{
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    public struct PropertyKey
    {
        public Guid fmtid;
        public uint pid;
        public PropertyKey(Guid f, uint p) { fmtid = f; pid = p; }
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct PropVariant
    {
        public ushort vt;
        public ushort wReserved1;
        public ushort wReserved2;
        public ushort wReserved3;
        public IntPtr pointerValue;
    }

    const ushort VT_LPWSTR = 31;
    const int GPS_READWRITE = 2;

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore
    {
        uint GetCount(out uint cProps);
        uint GetAt(uint iProp, out PropertyKey pkey);
        uint GetValue(ref PropertyKey key, out PropVariant pv);
        uint SetValue(ref PropertyKey key, ref PropVariant pv);
        uint Commit();
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    static extern void SHGetPropertyStoreFromParsingName(
        string pszPath,
        IntPtr zero,
        int flags,
        [In] ref Guid riid,
        out IPropertyStore propertyStore);

    [DllImport("ole32.dll")]
    static extern int PropVariantClear(ref PropVariant pvar);

    public static void Apply(string lnkPath, string appId, string relaunchCmd, string displayName, string iconResource)
    {
        var iid = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99");
        IPropertyStore store;
        SHGetPropertyStoreFromParsingName(lnkPath, IntPtr.Zero, GPS_READWRITE, ref iid, out store);

        var fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");
        SetString(store, new PropertyKey(fmtid, 5), appId);        // System.AppUserModel.ID
        SetString(store, new PropertyKey(fmtid, 2), relaunchCmd);  // RelaunchCommand
        SetString(store, new PropertyKey(fmtid, 4), displayName);  // RelaunchDisplayNameResource
        SetString(store, new PropertyKey(fmtid, 3), iconResource); // RelaunchIconResource
        store.Commit();
        Marshal.ReleaseComObject(store);
    }

    static void SetString(IPropertyStore store, PropertyKey key, string value)
    {
        var pv = new PropVariant();
        pv.vt = VT_LPWSTR;
        pv.pointerValue = Marshal.StringToCoTaskMemUni(value);
        try
        {
            var hr = store.SetValue(ref key, ref pv);
            if (hr != 0)
            {
                Marshal.ThrowExceptionForHR(unchecked((int)hr));
            }
        }
        finally
        {
            PropVariantClear(ref pv);
        }
    }
}
'@ -Language CSharp
}

function New-AppShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$IconPath,
        [Parameter(Mandatory = $true)][string]$AppUserModelId
    )

    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($Path)
    $lnk.TargetPath = $Target
    $lnk.Arguments = $Arguments
    $lnk.WorkingDirectory = $WorkingDirectory
    $lnk.WindowStyle = 1
    $lnk.Description = 'TanionPlaning — планировщик задач'
    $lnk.IconLocation = "$IconPath,0"
    $lnk.Save()
    [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($lnk)
    [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)

    # Release file handles before property store write.
    Start-Sleep -Milliseconds 150
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()

    $relaunch = '"' + $Target + '" ' + $Arguments
    $iconResource = $IconPath + ',0'
    try {
        [LnkAppId]::Apply($Path, $AppUserModelId, $relaunch, 'TanionPlaning', $iconResource)
        Write-Host "Shortcut created (with AppUserModelID): $Path"
    } catch {
        Write-Host "Shortcut created (basic, AppUserModelID skipped): $Path"
        Write-Host "  Reason: $($_.Exception.Message)"
    }
}

$desktop = [Environment]::GetFolderPath('Desktop')
$programs = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$projectLnk = Join-Path $root 'TanionPlaning.lnk'

$targets = @(
    (Join-Path $desktop 'TanionPlaning.lnk'),
    (Join-Path $programs 'TanionPlaning.lnk'),
    $projectLnk
)

foreach ($lnkPath in $targets) {
    New-AppShortcut -Path $lnkPath -Target $pyw -Arguments $launchArgs `
        -WorkingDirectory $root -IconPath $ico -AppUserModelId $appId
}

# Try to pin (often blocked on Windows 11; failure is non-fatal).
$pinned = $false
try {
    $shellApp = New-Object -ComObject Shell.Application
    $folder = $shellApp.Namespace($programs)
    $item = $folder.ParseName('TanionPlaning.lnk')
    if ($item) {
        foreach ($v in @($item.Verbs())) {
            $name = ($v.Name -replace '&', '')
            if ($name -match '(?i)taskbar|панел') {
                $v.DoIt()
                $pinned = $true
                Write-Host "Pin verb used: $($v.Name)"
                break
            }
        }
        if (-not $pinned) {
            $verbs = @($item.Verbs() | ForEach-Object { $_.Name })
            Write-Host ("Available verbs: " + ($verbs -join ' | '))
        }
    }
} catch {
    Write-Host "Pin attempt skipped: $($_.Exception.Message)"
}

if ($pinned) {
    Write-Host 'Pinned to taskbar.'
} else {
    Write-Host 'Auto-pin is blocked on this Windows build (Windows 11).'
    Write-Host 'Pin manually: right-click Desktop\TanionPlaning.lnk -> Pin to taskbar'
    Write-Host 'Or: Start -> TanionPlaning -> Pin to taskbar'
}
