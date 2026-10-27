// Customer-facing single icon. The audited ZIP payload is appended at build time.
// The normal system PowerShell/.NET ZIP reader preserves UTF-8 names; no downloads or policy changes.
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shlobj.h>
#include <bcrypt.h>
#include <string>
#include <vector>
#include <cstdio>
#ifndef KIO_PAYLOAD_SHA256
#error Build with the SHA-256 of the audited payload
#endif
#ifndef KIO_RELEASE
#error Build with the matching release version
#endif
static void fail() {
    const wchar_t* text=L"Bogo Tools could not start. Check free disk space and extract the ZIP again. Windows 10 (1803) or later is required.";
    LANGID language=GetUserDefaultUILanguage();
    switch(PRIMARYLANGID(language)) {
    case LANG_KOREAN:text=L"Bogo Tools를 시작하지 못했습니다. 디스크 여유 공간을 확인하고 ZIP 압축을 다시 풀어 주세요. Windows 10 (1803) 이상이 필요합니다.";break;
    case LANG_VIETNAMESE:text=L"Không thể mở Bogo Tools. Kiểm tra dung lượng trống và giải nén lại ZIP. Cần Windows 10 (1803) trở lên.";break;
    case LANG_JAPANESE:text=L"Bogo Toolsを起動できませんでした。空き容量を確認し、ZIPをもう一度展開してください。Windows 10 (1803)以降が必要です。";break;
    case LANG_CHINESE:text=(SUBLANGID(language)==SUBLANG_CHINESE_TRADITIONAL||SUBLANGID(language)==SUBLANG_CHINESE_HONGKONG||SUBLANGID(language)==SUBLANG_CHINESE_MACAU)
        ? L"無法啟動 Bogo Tools。請確認磁碟可用空間並重新解壓縮 ZIP。需要 Windows 10 (1803) 或更新版本。"
        : L"无法启动 Bogo Tools。请检查磁盘可用空间并重新解压 ZIP。需要 Windows 10 (1803) 或更高版本。";break;
    }
    MessageBoxW(nullptr,text,L"Bogo Tools",MB_OK|MB_ICONERROR);
}
static bool plainDirectory(const std::wstring& path) {
    DWORD a=GetFileAttributesW(path.c_str());
    if(a==INVALID_FILE_ATTRIBUTES) return CreateDirectoryW(path.c_str(),nullptr)!=0;
    return (a&FILE_ATTRIBUTE_DIRECTORY) && !(a&FILE_ATTRIBUTE_REPARSE_POINT);
}
static std::wstring quote(const std::wstring& s) { return L"\""+s+L"\""; }
static bool run(const std::wstring& executable,std::wstring args,DWORD* exitCode=nullptr) {
    std::wstring command=quote(executable)+L" "+args;
    STARTUPINFOW si{};si.cb=sizeof(si);PROCESS_INFORMATION pi{};
    if(!CreateProcessW(executable.c_str(),command.data(),nullptr,nullptr,FALSE,CREATE_NO_WINDOW,nullptr,nullptr,&si,&pi)) return false;
    CloseHandle(pi.hThread);
    if(!exitCode) { CloseHandle(pi.hProcess);return true; }
    WaitForSingleObject(pi.hProcess,INFINITE);GetExitCodeProcess(pi.hProcess,exitCode);CloseHandle(pi.hProcess);return *exitCode==0;
}
static std::wstring utf16Base64(const std::wstring& text) {
    static const wchar_t alphabet[]=L"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    const auto* bytes=reinterpret_cast<const unsigned char*>(text.data());
    size_t length=text.size()*sizeof(wchar_t);std::wstring out;out.reserve((length+2)/3*4);
    for(size_t i=0;i<length;i+=3){
        unsigned int value=static_cast<unsigned int>(bytes[i])<<16;
        if(i+1<length)value|=static_cast<unsigned int>(bytes[i+1])<<8;
        if(i+2<length)value|=bytes[i+2];
        out+=alphabet[(value>>18)&63];out+=alphabet[(value>>12)&63];
        out+=i+1<length?alphabet[(value>>6)&63]:L'=';out+=i+2<length?alphabet[value&63]:L'=';
    }
    return out;
}
static bool extract(const std::wstring& archive,const std::wstring& root) {
    // Base64 values are data, not PowerShell syntax. No profile, policy, locale or machine changes.
    std::wstring expected;for(char c:std::string(KIO_PAYLOAD_SHA256))expected+=static_cast<wchar_t>(c);
    std::wstring script=L"$zip=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('"+utf16Base64(archive)+L"'));"
        L"$root=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('"+utf16Base64(root)+L"'));"
        L"$expected='"+expected+L"';\n";
    script+=LR"BOGO_EXTRACT(
# Embedded verbatim in the proposed PortableLauncher.cpp. Inputs are prepended
# as Base64-decoded UTF-16 strings, never interpolated into PowerShell syntax.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version 2
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function AttributesOrNull([string]$path) {
    try { return [IO.File]::GetAttributes($path) }
    catch [IO.FileNotFoundException] { return $null }
    catch [IO.DirectoryNotFoundException] { return $null }
}
function PlainDirectory([string]$path) {
    if (-not ($path.Equals($root, [StringComparison]::OrdinalIgnoreCase) -or
              $path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase))) { throw 'Directory escaped cache' }
    $current = $root
    $parts = @('') + @($path.Substring($root.Length).Split('\') | Where-Object { $_ -ne '' })
    foreach ($part in $parts) {
        if ($part -ne '') { $current = [IO.Path]::Combine($current, $part) }
        $attributes = AttributesOrNull $current
        if ($null -eq $attributes) {
            [void][IO.Directory]::CreateDirectory($current)
            $attributes = [IO.File]::GetAttributes($current)
        }
        if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            ($attributes -band [IO.FileAttributes]::Directory) -eq 0) { throw 'Unsafe cache directory' }
    }
}
function PlainFileOrAbsent([string]$path) {
    $attributes = AttributesOrNull $path
    if ($null -eq $attributes) { return $false }
    if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        ($attributes -band [IO.FileAttributes]::Directory) -ne 0) { throw 'Unsafe managed file' }
    return $true
}
function Digest([string]$path) {
    $stream = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $hash.Dispose(); $stream.Dispose() }
}

$archiveStream = $null
$archive = $null
try {
    if ($expected -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid compiled payload digest' }
    $root = [IO.Path]::GetFullPath($root).TrimEnd('\')
    # Hold the authenticated archive open without write/delete sharing throughout extraction.
    if (-not (PlainFileOrAbsent $zip)) { throw 'Missing authenticated archive' }
    $archiveStream = [IO.File]::Open($zip, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $digest = [BitConverter]::ToString($hasher.ComputeHash($archiveStream)).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose() }
    if ($digest -cne $expected) { throw 'Payload digest mismatch' }
    $archiveStream.Position = 0
    $archive = [IO.Compression.ZipArchive]::new($archiveStream, [IO.Compression.ZipArchiveMode]::Read, $true)
    if ($archive.Entries.Count -lt 1 -or $archive.Entries.Count -gt 5000) { throw 'Invalid entry count' }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $entries = [Collections.Generic.List[object]]::new()
    [long]$total = 0
    # Validate the entire archive before changing even a single installed file.
    foreach ($entry in $archive.Entries) {
        $name = $entry.FullName
        if ($name.Contains('\')) { throw 'Noncanonical archive path' }
        $parts = $name.Split('/')
        if ($parts.Count -lt 2 -or $parts[0] -cne 'KIO-Control-Windows') { throw 'Foreign archive root' }
        foreach ($part in $parts) {
            if ($part -eq '' -or $part -eq '.' -or $part -eq '..' -or
                $part -match '[\x00-\x1f:\*?<>|]' -or $part.EndsWith('.') -or $part.EndsWith(' ') -or
                $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$') { throw 'Unsafe archive component' }
        }
        $attributes = [uint32]([long]$entry.ExternalAttributes -band 4294967295)
        $kind = ($attributes -shr 16) -band 61440
        if ($kind -ne 0 -and $kind -ne 32768) { throw 'Nonregular archive entry' }
        if (($attributes -band 1024) -ne 0 -or $entry.Length -lt 0 -or $entry.Length -gt 1073741824) { throw 'Invalid entry metadata' }
        $total += $entry.Length
        if ($total -gt 8589934592) { throw 'Oversized archive' }
        $target = [IO.Path]::GetFullPath([IO.Path]::Combine($root, $name.Replace('/', '\')))
        if (-not $target.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) -or -not $seen.Add($target)) { throw 'Escaping or duplicate target' }
        $entries.Add([PSCustomObject]@{ Entry = $entry; Target = $target; Relative = $name.Replace('/', '\') })
    }
    PlainDirectory $root
    $stage = [IO.Path]::Combine($root, '.bogo-extract-' + [Guid]::NewGuid().ToString('N'))
    if ($null -ne (AttributesOrNull $stage)) { throw 'Extraction staging collision' }
    PlainDirectory $stage
    $new = [IO.Path]::Combine($stage, 'new')
    $previous = [IO.Path]::Combine($stage, 'previous')
    PlainDirectory $new
    [int]$index = 0
    foreach ($item in $entries) {
        $temporary = [IO.Path]::Combine($new, $index.ToString() + '.tmp')
        $index += 1
        # CreateNew never overwrites an existing file; all temporary files belong to this invocation.
        [IO.Compression.ZipFileExtensions]::ExtractToFile($item.Entry, $temporary, $false)
        if (([IO.FileInfo]::new($temporary)).Length -ne $item.Entry.Length) { throw 'Incomplete extracted entry' }
        $targetParent = [IO.Path]::GetDirectoryName($item.Target)
        PlainDirectory $targetParent
        $exists = PlainFileOrAbsent $item.Target
        if ($exists -and (([IO.FileInfo]::new($item.Target)).Length -eq $item.Entry.Length) -and
            (Digest $item.Target) -ceq (Digest $temporary)) {
            # A failed old tar extraction leaves 3,902 exact files: keep their bytes and file IDs.
            [IO.File]::Delete($temporary)
        } elseif ($exists) {
            # Atomic replacement changes only this directory entry (never writes through a hard link).
            # Retain every replaced old file outside the application tree for recovery.
            $backup = [IO.Path]::Combine($previous, $item.Relative)
            PlainDirectory ([IO.Path]::GetDirectoryName($backup))
            if ($null -ne (AttributesOrNull $backup)) { throw 'Recovery backup collision' }
            [void](PlainFileOrAbsent $item.Target)
            [IO.File]::Replace($temporary, $item.Target, $backup, $false)
        } else {
            [IO.File]::Move($temporary, $item.Target)
        }
    }
    [IO.Directory]::Delete($new, $false)
    if ($null -eq (AttributesOrNull $previous)) { [IO.Directory]::Delete($stage, $false) }
} catch {
    # No ready marker, no application launch, no deletion of unknown files or recovery backups.
    exit 1
} finally {
    if ($null -ne $archive) { $archive.Dispose() }
    if ($null -ne $archiveStream) { $archiveStream.Dispose() }
}
exit 0
)BOGO_EXTRACT";
    if(script.find(L'"')!=std::wstring::npos)return false;
    std::wstring command=L"-NoProfile -NonInteractive -Command "+quote(script);
    // The Windows command-line limit includes the absolute executable name and its quotes.
    wchar_t system[32768];UINT count=GetSystemDirectoryW(system,32768);
    if(!count||count>=32768)return false;
    std::wstring executable=std::wstring(system)+L"\\WindowsPowerShell\\v1.0\\powershell.exe";
    if(command.size()+executable.size()+4>=32767)return false;
    DWORD result=1;return run(executable,command,&result);
}
static bool payload(const std::wstring& self,const std::wstring& output) {
    FILE* in=_wfopen(self.c_str(),L"rb");if(!in)return false;
    unsigned long long length=0;char magic[8];
    if(_fseeki64(in,-16,SEEK_END)!=0||fread(&length,8,1,in)!=1||fread(magic,1,8,in)!=8||memcmp(magic,"KIOTOOLS",8)||length<1000||length>2ULL*1024*1024*1024) { fclose(in);return false; }
    auto end=_ftelli64(in);if(length>static_cast<unsigned long long>(end-16)||_fseeki64(in,end-16-length,SEEK_SET)!=0){fclose(in);return false;}
    BCRYPT_ALG_HANDLE algorithm=nullptr;BCRYPT_HASH_HANDLE hash=nullptr;
    if(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0)<0){fclose(in);return false;}
    if(BCryptCreateHash(algorithm,&hash,nullptr,0,nullptr,0,0)<0){BCryptCloseAlgorithmProvider(algorithm,0);fclose(in);return false;}
    FILE* out=_wfopen(output.c_str(),L"wb");bool ok=out!=nullptr;std::vector<unsigned char> buffer(1024*1024);
    while(ok&&length){size_t n=static_cast<size_t>(length<buffer.size()?length:buffer.size());ok=fread(buffer.data(),1,n,in)==n&&fwrite(buffer.data(),1,n,out)==n&&BCryptHashData(hash,buffer.data(),static_cast<ULONG>(n),0)>=0;length-=n;}
    unsigned char digest[32]{};ok=ok&&BCryptFinishHash(hash,digest,32,0)>=0;
    if(out&&fclose(out)!=0)ok=false;fclose(in);BCryptDestroyHash(hash);BCryptCloseAlgorithmProvider(algorithm,0);
    char hex[65];for(int i=0;i<32;i++)sprintf(hex+2*i,"%02x",digest[i]);hex[64]=0;
    return ok&&!strcmp(hex,KIO_PAYLOAD_SHA256);
}
int WINAPI wWinMain(HINSTANCE,HINSTANCE,PWSTR,int) {
    wchar_t path[32768];DWORD n=GetModuleFileNameW(nullptr,path,32768);if(!n||n>=32768)return 1;std::wstring self(path,n);
    PWSTR local=nullptr;if(FAILED(SHGetKnownFolderPath(FOLDERID_LocalAppData,KF_FLAG_CREATE,nullptr,&local)))return 1;
    std::wstring parent=std::wstring(local)+L"\\KIO Tools";CoTaskMemFree(local);
    std::wstring root=parent+L"\\" KIO_RELEASE, app=root+L"\\KIO-Control-Windows", marker=root+L"\\ready";
    HANDLE mutex=CreateMutexW(nullptr,FALSE,L"Local\\KIOToolsSingleIconExtract");if(!mutex)return 1;
    DWORD waited=WaitForSingleObject(mutex,INFINITE);if(waited!=WAIT_OBJECT_0&&waited!=WAIT_ABANDONED){CloseHandle(mutex);return 1;}
    bool ok=plainDirectory(parent)&&plainDirectory(root);
    DWORD marked=GetFileAttributesW(marker.c_str());
    if(ok&&marked==INVALID_FILE_ATTRIBUTES){
        std::wstring archive=root+L"\\payload.zip";ok=payload(self,archive);
        if(ok)ok=extract(archive,root);
        DeleteFileW(archive.c_str());
        if(ok){HANDLE ready=CreateFileW(marker.c_str(),GENERIC_WRITE,0,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);ok=ready!=INVALID_HANDLE_VALUE;if(ok){FlushFileBuffers(ready);CloseHandle(ready);}}
    }
    if(ok)ok=plainDirectory(app)&&GetFileAttributesW((app+L"\\KIOControl.exe").c_str())!=INVALID_FILE_ATTRIBUTES;
    if(!ok)DeleteFileW(marker.c_str());
    ReleaseMutex(mutex);CloseHandle(mutex);
    if(ok)ok=run(app+L"\\KIOControl.exe",L"");
    if(!ok){
        // English fallback is available on all supported systems, before the UI starts.
        fail();return 1;
    }
    return 0;
}
