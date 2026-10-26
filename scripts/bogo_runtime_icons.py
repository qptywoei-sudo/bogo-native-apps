"""Read only a known Windows app's icon handles, then compare approved pixels.

This checks the icon sources Windows uses for window/taskbar/Alt+Tab rendering;
it does not capture the desktop or claim a compositor screenshot. Every native
call is bound to the caller's known HWND/PID. Borrowed HICONs are never destroyed.

API contracts: https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-geticon
https://learn.microsoft.com/en-us/dotnet/api/system.drawing.icon.fromhandle
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tomllib
import zlib

ROLES = (("small2", 2, (-34, -14)), ("small", 0, (-34, -14)), ("big", 1, (-14, -34)))
TOLERANCE = {
    "description": "At most one pixel around a measured RGBA edge; premultiplied RGBA error <=32, interior <=2, mean <=0.75, alpha mean <=0.35, pixels over8 <=1%. No geometry or whole-image color tolerance.",
    "edgeMax": 32, "interiorMax": 2, "meanMax": 0.75,
    "alphaMeanMax": 0.35, "over8FractionMax": 0.01,
}


def require_owned(hwnd, pid, api):
    valid, actual = api.owner(hwnd)
    if not valid or actual != pid:
        raise ValueError("runtime icon HWND is absent or no longer belongs to the expected PID")


def collect_icon_handles(hwnd, pid, api):
    if not isinstance(hwnd, int) or not 0 < hwnd < 1 << 63 or not isinstance(pid, int) or pid <= 0:
        raise ValueError("a positive known HWND and PID are required")
    results = []
    for role, kind, fallbacks in ROLES:
        require_owned(hwnd, pid, api)
        handle = api.get_icon(hwnd, kind, 1000)
        require_owned(hwnd, pid, api)
        source = "WM_GETICON/" + role
        if not handle:
            for index in fallbacks:
                require_owned(hwnd, pid, api)
                handle = api.class_icon(hwnd, index)
                require_owned(hwnd, pid, api)
                if handle:
                    source = "GetClassLongPtr/" + ("GCLP_HICONSM" if index == -34 else "GCLP_HICON")
                    break
        if not handle:
            raise ValueError("no valid runtime icon for " + role)
        if not isinstance(handle, int) or not 0 < handle < 1 << 64:
            raise ValueError("runtime icon returned an invalid handle")
        results.append({"role": role, "handle": int(handle), "source": source})
    return results


class Win32:
    def __init__(self):
        if os.name != "nt":
            raise OSError("actual runtime icon extraction requires Windows")
        from ctypes import wintypes as w
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.IsWindow.argtypes = [w.HWND]
        self.user.IsWindow.restype = w.BOOL
        self.user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        self.user.GetWindowThreadProcessId.restype = w.DWORD
        self.send = self.user.SendMessageTimeoutW
        self.send.argtypes = [w.HWND, w.UINT, ctypes.c_size_t, ctypes.c_ssize_t,
                              w.UINT, w.UINT, ctypes.POINTER(ctypes.c_size_t)]
        self.send.restype = ctypes.c_ssize_t
        self.get_class = self.user.GetClassLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else self.user.GetClassLongW
        self.get_class.argtypes = [w.HWND, ctypes.c_int]
        self.get_class.restype = ctypes.c_void_p

    def owner(self, hwnd):
        from ctypes import wintypes as w
        pid = w.DWORD()
        thread = self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return bool(self.user.IsWindow(hwnd) and thread), pid.value

    def get_icon(self, hwnd, kind, timeout):
        result = ctypes.c_size_t()
        # BLOCK | ABORTIFHUNG | ERRORONEXIT; no unbounded window procedure call.
        if not self.send(hwnd, 0x7F, kind, 0, 0x23, timeout, ctypes.byref(result)):
            raise OSError("WM_GETICON failed or exceeded its 1000ms bound")
        return result.value

    def class_icon(self, hwnd, index):
        return self.get_class(hwnd, index) or 0


MAX_PNG_BYTES = 4 * 1024 * 1024


def _png_rgba(path, max_dimension=512):
    """Decode only the bounded PNG subset emitted by System.Drawing here.

    No profiles are applied and no pixels are resized or recolored. Unsupported
    indexed, grayscale, 16-bit, interlaced or tRNS input is refused explicitly.
    """
    if not 1 <= max_dimension <= 1024:
        raise ValueError("unreviewed PNG dimension bound")
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("runtime PNG must be a regular file")
    with path.open('rb') as stream:
        png = stream.read(MAX_PNG_BYTES + 1)
    if len(png) > MAX_PNG_BYTES or png[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError("runtime PNG exceeds the byte bound or has an invalid signature")
    offset, chunks, header, ended = 8, 0, None, False
    compressed = bytearray()
    idat_seen = idat_closed = False
    while offset < len(png):
        chunks += 1
        if chunks > 4096 or offset + 12 > len(png):
            raise ValueError("invalid or excessive runtime PNG chunks")
        length = struct.unpack_from('>I', png, offset)[0]
        kind = png[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(png) or not all(65 <= b <= 90 or 97 <= b <= 122 for b in kind):
            raise ValueError("truncated or invalid PNG chunk")
        body = png[offset + 8:end - 4]
        crc = struct.unpack_from('>I', png, end - 4)[0]
        if zlib.crc32(kind + body) & 0xffffffff != crc:
            raise ValueError("PNG chunk CRC mismatch")
        offset = end
        if header is None and kind != b'IHDR':
            raise ValueError("PNG must begin with IHDR")
        if kind == b'IHDR':
            if header is not None or len(body) != 13:
                raise ValueError("duplicate or malformed PNG IHDR")
            width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', body)
            if not 1 <= width <= max_dimension or not 1 <= height <= max_dimension:
                raise ValueError("runtime icon dimensions are outside the reviewed bound")
            if depth != 8 or color not in (2, 6) or compression or filtering or interlace:
                raise ValueError("unsupported PNG format; expected 8-bit RGB/RGBA noninterlaced")
            header = width, height, 3 if color == 2 else 4
        elif kind == b'IDAT':
            if idat_closed:
                raise ValueError("PNG IDAT chunks must be contiguous")
            idat_seen = True
            compressed.extend(body)
        elif kind == b'IEND':
            if body or not idat_seen or offset != len(png):
                raise ValueError("malformed PNG end or trailing bytes")
            ended = True
            break
        else:
            if idat_seen:
                idat_closed = True
            if kind == b'tRNS':
                raise ValueError("unsupported PNG tRNS transparency")
            if kind == b'PLTE':
                if idat_seen or not body or len(body) > 768 or len(body) % 3:
                    raise ValueError("invalid optional PNG palette")
            elif not kind[0] & 0x20:
                raise ValueError("unsupported critical PNG chunk")
    if not ended or header is None:
        raise ValueError("incomplete runtime PNG")
    width, height, channels = header
    stride = width * channels
    expected = (stride + 1) * height
    decoder = zlib.decompressobj()
    try:
        # Never flush unbounded output: full valid input must reach eof within
        # this exact geometry limit, with no second stream or compressed tail.
        scanlines = decoder.decompress(bytes(compressed), expected + 1)
    except zlib.error as error:
        raise ValueError("invalid PNG zlib stream") from error
    if len(scanlines) != expected or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
        raise ValueError("PNG pixel stream exceeds or differs from its bounded geometry")
    rgba = bytearray(width * height * 4)
    previous = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        method = scanlines[start]
        if method > 4:
            raise ValueError("unsupported PNG row filter")
        row = bytearray(scanlines[start + 1:start + 1 + stride])
        for x in range(stride):
            left = row[x - channels] if x >= channels else 0
            up = previous[x]
            corner = previous[x - channels] if x >= channels else 0
            if method == 0:
                predictor = 0
            elif method == 1:
                predictor = left
            elif method == 2:
                predictor = up
            elif method == 3:
                predictor = (left + up) // 2
            else:
                p = left + up - corner
                distances = (abs(p - left), abs(p - up), abs(p - corner))
                predictor = (left, up, corner)[distances.index(min(distances))]
            row[x] = (row[x] + predictor) & 255
        if channels == 4:
            rgba[y * width * 4:(y + 1) * width * 4] = row
        else:
            for x in range(width):
                index = (y * width + x) * 4
                rgba[index:index + 4] = row[x * 3:x * 3 + 3] + b'\xff'
        previous = row
    return (width, height), rgba, hashlib.sha256(png).hexdigest()


def _normalized(path, max_dimension=512):
    size, data, digest = _png_rgba(path, max_dimension=max_dimension)
    for i in range(0, len(data), 4):
        if data[i + 3] == 0:
            data[i:i + 3] = b"\0\0\0"
    return size, bytes(data), digest


def compare_icon_pngs(actual, expected, allow_edge_tolerance=True, max_dimension=512):
    size, a, a_png = _normalized(actual, max_dimension=max_dimension)
    expected_size, b, b_png = _normalized(expected, max_dimension=max_dimension)
    digest = lambda size, raw: hashlib.sha256(struct.pack(">II", *size) + raw).hexdigest()
    result = {"actualDimensions": size, "expectedDimensions": expected_size,
              "actualPngSha256": a_png, "expectedPngSha256": b_png,
              "actualRgbaSha256": digest(size, a), "expectedRgbaSha256": digest(expected_size, b),
              "transparentRgbNormalizedToZero": True, "edgeTolerance": TOLERANCE.copy()}
    if size != expected_size:
        return dict(result, passed=False, exact=False, reason="dimensions differ")
    if not any(a[i] for i in range(3, len(a), 4)) or not any(b[i] for i in range(3, len(b), 4)):
        return dict(result, passed=False, exact=False, reason="blank runtime or approved icon")
    if a == b:
        return dict(result, passed=True, exact=True, reason="exact normalized RGBA",
                    metrics={"maxEdgeError": 0, "maxInteriorError": 0, "meanPremultipliedRgbaError": 0,
                             "meanAlphaError": 0, "pixelsOver8Fraction": 0, "changedPixels": 0})
    def premultiplied(raw):
        return [tuple([(raw[i + c] * raw[i + 3] + 127) // 255 for c in range(3)] + [raw[i + 3]]) for i in range(0, len(raw), 4)]
    pa, pb = premultiplied(a), premultiplied(b)
    width, height = size
    edges = set()
    for pixels in (pa, pb):
        for y in range(height):
            for x in range(width):
                i = y * width + x
                for xx, yy in ((x + 1, y), (x, y + 1)):
                    if xx < width and yy < height:
                        j = yy * width + xx
                        if max(abs(pixels[i][c] - pixels[j][c]) for c in range(4)) > 8:
                            edges.update((i, j))
    # One-pixel neighbourhood only, never a blanket image-wide allowance.
    edges = {yy * width + xx for i in edges for yy in range(max(0, i // width - 1), min(height, i // width + 2))
             for xx in range(max(0, i % width - 1), min(width, i % width + 2))}
    errors = [max(abs(x[c] - y[c]) for c in range(4)) for x, y in zip(pa, pb)]
    means = [sum(abs(x[c] - y[c]) for c in range(4)) / 4 for x, y in zip(pa, pb)]
    metrics = {"maxEdgeError": max((e for i, e in enumerate(errors) if i in edges), default=0),
               "maxInteriorError": max((e for i, e in enumerate(errors) if i not in edges), default=0),
               "meanPremultipliedRgbaError": sum(means) / len(means),
               "meanAlphaError": sum(abs(a[i] - b[i]) for i in range(3, len(a), 4)) / len(errors),
               "pixelsOver8Fraction": sum(e > 8 for e in errors) / len(errors),
               "changedPixels": sum(e > 0 for e in errors), "edgePixels": len(edges)}
    foreground = sum(b[i] > 0 for i in range(3, len(b), 4))
    passed = bool(allow_edge_tolerance and foreground
                  and metrics["maxEdgeError"] <= TOLERANCE["edgeMax"]
                  and metrics["maxInteriorError"] <= TOLERANCE["interiorMax"]
                  and metrics["meanPremultipliedRgbaError"] <= TOLERANCE["meanMax"]
                  and metrics["meanAlphaError"] <= TOLERANCE["alphaMeanMax"]
                  and metrics["pixelsOver8Fraction"] <= TOLERANCE["over8FractionMax"])
    return dict(result, passed=passed, exact=False, metrics=metrics,
                reason="bounded edge-only OS scaling difference" if passed else "approved icon pixels do not match")


POWERSHELL = r'''param([Parameter(Mandatory=$true)][string]$Config)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class BogoOwnedIcon {
  [DllImport("user32.dll")] static extern bool IsWindow(IntPtr hwnd);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
  [DllImport("user32.dll", SetLastError=true)] static extern IntPtr CreateIcon(IntPtr instance, int width, int height, byte planes, byte bits, byte[] mask, byte[] bgra);
  [DllImport("user32.dll", SetLastError=true)] static extern bool DestroyIcon(IntPtr owned);
  [DllImport("user32.dll", SetLastError=true)] static extern IntPtr CreateIconFromResourceEx(byte[] png, uint bytes, bool icon, uint version, int width, int height, uint flags);
  public static void RequireOwner(IntPtr hwnd, uint expected) {
    uint actual; uint thread = GetWindowThreadProcessId(hwnd, out actual);
    if (!IsWindow(hwnd) || thread == 0 || actual != expected) throw new InvalidOperationException("HWND owner changed; icon read refused");
  }
  public static IntPtr CreateReference(int width, int height, byte[] mask, byte[] bgra) {
    IntPtr owned = CreateIcon(IntPtr.Zero, width, height, 1, 32, mask, bgra);
    if (owned == IntPtr.Zero) throw new InvalidOperationException("could not create the owned reference icon");
    return owned;
  }
  public static void ReleaseReference(IntPtr owned) {
    if (owned != IntPtr.Zero && !DestroyIcon(owned)) throw new InvalidOperationException("could not release owned reference icon");
  }
  public static IntPtr CreateEframeReference(byte[] png, int width, int height) {
    IntPtr owned = CreateIconFromResourceEx(png, (uint)png.Length, true, 0x00030000, width, height, 0);
    if (owned == IntPtr.Zero) throw new InvalidOperationException("could not create the owned eframe reference icon");
    return owned;
  }
}
'@
$cfg = Get-Content -Raw -Encoding UTF8 -LiteralPath $Config | ConvertFrom-Json
$hwnd = [IntPtr]::new([Int64]::Parse($cfg.hwnd))
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $cfg.ico).Hash.ToLowerInvariant() -ne $cfg.sha256) { throw 'approved ICO changed before rendering' }
$rows = @()
$ownedReference = [IntPtr]::Zero
try {
if ($cfg.runtimeReference) {
  [BogoOwnedIcon]::RequireOwner($hwnd, [uint32]$cfg.pid)
  $ref = $cfg.runtimeReference
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $ref.png).Hash.ToLowerInvariant() -ne $ref.pngSha256) {throw 'approved runtime PNG changed'}
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $ref.mask).Hash.ToLowerInvariant() -ne $ref.maskSha256) {throw 'reference mask changed'}
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $ref.bgra).Hash.ToLowerInvariant() -ne $ref.bgraSha256) {throw 'reference pixels changed'}
  $ownedReference = [BogoOwnedIcon]::CreateReference([int]$ref.width, [int]$ref.height, [IO.File]::ReadAllBytes($ref.mask), [IO.File]::ReadAllBytes($ref.bgra))
}
foreach ($item in $cfg.icons) {
  [BogoOwnedIcon]::RequireOwner($hwnd, [uint32]$cfg.pid)
  $handle = [IntPtr]::new([Int64]::Parse($item.handle))
  # FromHandle borrows the app's HICON. Only our managed clone and bitmaps are disposed.
  $borrowed = [System.Drawing.Icon]::FromHandle($handle)
  $clone = [System.Drawing.Icon]$borrowed.Clone()
  $actual = $null; $approved = $null; $reference = $null; $ownedScaled = [IntPtr]::Zero
  try {
    $actual = $clone.ToBitmap()
    $bound = if ($cfg.runtimeReference) {1024} else {512}
    if ($actual.Width -lt 1 -or $actual.Width -gt $bound -or $actual.Height -lt 1 -or $actual.Height -gt $bound) { throw 'runtime icon dimensions exceed reviewed bounds' }
    if ($cfg.referenceGenerator) {
      $gen = $cfg.referenceGenerator
      if ((Get-FileHash -Algorithm SHA256 -LiteralPath $gen.executable).Hash.ToLowerInvariant() -ne $gen.executableSha256) {throw 'reference generator changed'}
      if ((Get-FileHash -Algorithm SHA256 -LiteralPath $ref.png).Hash.ToLowerInvariant() -ne $ref.pngSha256) {throw 'approved source changed before rasterization'}
      $frame = Join-Path $cfg.output ($item.role + '-eframe-reference.png')
      $generated = & $gen.executable $ref.png $frame ([string]$actual.Width) ([string]$actual.Height) 2>&1
      if ($LASTEXITCODE -ne 0) {throw "exact eframe raster generator failed: $generated"}
      [BogoOwnedIcon]::RequireOwner($hwnd, [uint32]$cfg.pid)
      $ownedScaled = [BogoOwnedIcon]::CreateEframeReference([IO.File]::ReadAllBytes($frame), $actual.Width, $actual.Height)
      $approvedBorrowed = [System.Drawing.Icon]::FromHandle($ownedScaled)
      $approved = [System.Drawing.Icon]$approvedBorrowed.Clone()
    } elseif ($cfg.runtimeReference) {
      if ($actual.Width -ne $ref.width -or $actual.Height -ne $ref.height) {throw 'runtime dimensions differ from approved PNG; no resizing is permitted'}
      $approvedBorrowed = [System.Drawing.Icon]::FromHandle($ownedReference)
      $approved = [System.Drawing.Icon]$approvedBorrowed.Clone()
    } else {
      $approved = [System.Drawing.Icon]::new([string]$cfg.ico, [System.Drawing.Size]::new($actual.Width, $actual.Height))
    }
    $reference = $approved.ToBitmap()
    if ($reference.Width -ne $actual.Width -or $reference.Height -ne $actual.Height) { throw 'approved ICO has no same-size rendered frame' }
    [BogoOwnedIcon]::RequireOwner($hwnd, [uint32]$cfg.pid)
    $actualPath = Join-Path $cfg.output ($item.role + '-actual.png')
    $expectedPath = Join-Path $cfg.output ($item.role + '-approved.png')
    $actual.Save($actualPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $reference.Save($expectedPath, [System.Drawing.Imaging.ImageFormat]::Png)
    [BogoOwnedIcon]::RequireOwner($hwnd, [uint32]$cfg.pid)
    $record = @{role=$item.role; actual=$actualPath; expected=$expectedPath; width=$actual.Width; height=$actual.Height}
    if ($cfg.referenceGenerator) {
      $record.generatedFrame=$frame
      $record.generatedFrameSha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $frame).Hash.ToLowerInvariant()
      if ($actual.Width -eq $ref.width -and $actual.Height -eq $ref.height) {
        $winitBorrowed = [System.Drawing.Icon]::FromHandle($ownedReference)
        $winitClone = [System.Drawing.Icon]$winitBorrowed.Clone()
        $winitBitmap = $null
        try {
          $winitBitmap = $winitClone.ToBitmap()
          $nativePath = Join-Path $cfg.output ($item.role + '-winit-approved.png')
          $winitBitmap.Save($nativePath, [System.Drawing.Imaging.ImageFormat]::Png)
          $record.winitExpected=$nativePath
        } finally {if ($winitBitmap) {$winitBitmap.Dispose()}; $winitClone.Dispose()}
      }
    }
    $rows += $record
  } finally {
    if ($reference) {$reference.Dispose()}; if ($approved) {$approved.Dispose()}
    if ($actual) {$actual.Dispose()}; $clone.Dispose()
    if ($ownedScaled -ne [IntPtr]::Zero) {[BogoOwnedIcon]::ReleaseReference($ownedScaled)}
  }
}
$rows | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $cfg.output 'rendered.json')
} finally {
  # This handle was created above by this verifier. Never pass app/borrowed handles here.
  if ($ownedReference -ne [IntPtr]::Zero) {[BogoOwnedIcon]::ReleaseReference($ownedReference)}
}
'''


def approved_ico(path, sha256):
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise ValueError("approved ICO SHA-256 is required")
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("approved ICO must be a regular file")
    raw = path.read_bytes()
    if len(raw) < 6 or raw[:4] != b"\0\0\1\0" or not 0 < int.from_bytes(raw[4:6], 'little') <= 256:
        raise ValueError("source asset is not a reviewed ICO")
    if hashlib.sha256(raw).hexdigest() != sha256.lower():
        raise ValueError("source ICO bytes do not match the approved owner-derived asset")
    return path.resolve()


def approved_runtime_png(path, sha256):
    """Caller must bind this hash to the app's actual compiled PNG source/provenance."""
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise ValueError("approved runtime PNG SHA-256 is required")
    path = Path(path)
    size, rgba, actual_hash = _png_rgba(path, max_dimension=1024)
    if actual_hash != sha256.lower() or min(size) < 16 or size[0] != size[1]:
        raise ValueError("runtime PNG does not match approved source hash/geometry")
    return path.resolve(), size, bytes(rgba)


def winit_reference_bytes(rgba, width, height):
    """Exact winit Windows RgbaIcon::into_windows_icon input, without resizing.

    See winit/src/platform_impl/windows/icon.rs: alpha wrapping_sub(255),
    R/B swap, then CreateIcon(0,width,height,1,32,and_mask,bgra).
    """
    if len(rgba) != width * height * 4:
        raise ValueError("runtime PNG RGBA geometry mismatch")
    mask = bytes((rgba[i + 3] - 255) & 255 for i in range(0, len(rgba), 4))
    bgra = bytearray(rgba)
    for i in range(0, len(bgra), 4):
        bgra[i], bgra[i + 2] = bgra[i + 2], bgra[i]
    return mask, bytes(bgra)


def reference_contract(application_cargo_lock):
    """Bind the standalone renderer to the exact reviewed application lock."""
    tool = Path(__file__).resolve().parents[1] / 'tools/runtime-icon-reference'
    contract = json.loads((tool / 'reference-contract.json').read_text(encoding='utf-8'))
    for relative, key in [('Cargo.toml', 'referenceCargoManifestSha256'), ('Cargo.lock', 'referenceCargoLockSha256'), ('src/main.rs', 'referenceRustSourceSha256')]:
        if hashlib.sha256((tool / relative).read_bytes()).hexdigest() != contract[key]:
            raise ValueError('reference renderer source/lock changed')
    application = Path(application_cargo_lock)
    if application.is_symlink() or not application.is_file():
        raise ValueError('authenticated application Cargo.lock is required')
    raw = application.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha not in contract['reviewedApplicationLocks'].values():
        raise ValueError('application lock was not reviewed for the reference algorithm')
    packages = tomllib.loads(raw.decode('utf-8'))['package']
    for name in ('image', 'eframe', 'winit'):
        matched = [p for p in packages if p['name'] == name]
        valid = len(matched) == 1 and matched[0]['version'] == contract[name + 'Version']
        if valid and name == 'winit':
            valid = {key: matched[0].get(key) for key in ('version', 'source', 'checksum')} in contract['reviewedWinitPackages']
        elif valid:
            valid = matched[0].get('checksum') == contract[name + 'Checksum']
        if not valid:
            raise ValueError('application rendering dependency differs from the exact reference contract')
    # The standalone closure is locked, and each registry dependency/checksum
    # must also occur in this authenticated application lock. No floating fetch.
    locked = tomllib.loads((tool / 'Cargo.lock').read_text(encoding='utf-8'))['package']
    identities = {(p['name'], p['version'], p.get('checksum')) for p in packages if p.get('source')}
    if any((p['name'], p['version'], p.get('checksum')) not in identities for p in locked if p.get('source')):
        raise ValueError('reference transitive closure differs from reviewed application dependencies')
    return tool, dict(contract, applicationCargoLockSha256=sha)


def application_lock_for(app):
    """Public, exact lock copy for artifact-only checks without source ZIPs."""
    tool = Path(__file__).resolve().parents[1] / 'tools/runtime-icon-reference'
    contract = json.loads((tool / 'reference-contract.json').read_text(encoding='utf-8'))
    if app not in contract['reviewedApplicationLocks']:
        raise ValueError('unknown reference application')
    path = tool / 'application-locks' / (app + '.Cargo.lock')
    if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != contract['reviewedApplicationLocks'][app]:
        raise ValueError('public reviewed application lock copy changed')
    reference_contract(path)
    return path


def build_reference_generator(application_cargo_lock, output):
    tool, contract = reference_contract(application_cargo_lock)
    env = os.environ.copy()
    env['RUSTUP_TOOLCHAIN'] = contract['rustToolchain']
    if env.get('KIO_CARGO_HOME'):
        env['CARGO_HOME'] = env['KIO_CARGO_HOME']
    compiler = subprocess.run(['rustc', '-Vv'], env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
    if compiler.returncode or not compiler.stdout.startswith('rustc ' + contract['rustToolchain'] + ' '):
        raise ValueError('reference compiler differs from reviewed toolchain')
    host = next((line[6:] for line in compiler.stdout.splitlines() if line.startswith('host: ')), None)
    if not host or not re.fullmatch(r'[a-zA-Z0-9_-]+', host):
        raise ValueError('unreadable Rust host target')
    target = output / 'reference-target'
    command = ['cargo', 'build', '--release', '--locked', '--offline', '--manifest-path', str(tool / 'Cargo.toml'),
               '--target-dir', str(target), '--target', host]
    built = subprocess.run(command, env=env, capture_output=True, timeout=240)
    (output / 'reference-cargo-build.log').write_bytes(built.stdout + built.stderr)
    if built.returncode:
        raise RuntimeError('locked reference renderer failed; see reference-cargo-build.log')
    executable = target / host / 'release/bogo-runtime-icon-reference.exe'
    if not executable.is_file():
        raise ValueError('compiled Windows reference renderer is absent')
    return {'executable': str(executable), 'executableSha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'toolchain': compiler.stdout, 'contract': contract, 'command': command}


def check_runtime_icons(hwnd, pid, ico, approved_ico_sha256, output_directory, powershell=None,
                        runtime_png=None, approved_runtime_png_sha256=None, application_cargo_lock=None):
    """Actual Windows entry point. Creates a fresh owned evidence directory.

    Prefer runtime_png + its provenance-bound SHA for winit's PNG viewport path.
    It is decoded and passed through the same CreateIcon pipeline at its native
    size. ICO-only mode is strict and refuses a frame of another size. PE and
    shortcut ICO validation remains a separate check by the caller.
    """
    if os.name != "nt":
        raise OSError("real Windows icon execution pending; this host is not Windows")
    if powershell is None:
        powershell = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    ico = approved_ico(ico, approved_ico_sha256)
    runtime = None
    if (runtime_png is None) != (approved_runtime_png_sha256 is None):
        raise ValueError("runtime PNG and its approved hash must be supplied together")
    if runtime_png is not None or approved_runtime_png_sha256 is not None:
        runtime = approved_runtime_png(runtime_png, approved_runtime_png_sha256)
    if application_cargo_lock is not None and runtime is None:
        raise ValueError('reference renderer lock requires an authenticated runtime PNG')
    api = Win32()
    require_owned(hwnd, pid, api)
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    config = {"hwnd": str(hwnd), "pid": pid, "ico": str(ico), "sha256": approved_ico_sha256.lower(),
              "output": str(output)}
    if runtime is not None:
        png, size, rgba = runtime
        mask, bgra = winit_reference_bytes(rgba, *size)
        (output / 'reference-mask.bin').write_bytes(mask)
        (output / 'reference-bgra.bin').write_bytes(bgra)
        config['runtimeReference'] = {'png': str(png), 'pngSha256': approved_runtime_png_sha256.lower(),
            'width': size[0], 'height': size[1], 'mask': str(output / 'reference-mask.bin'),
            'bgra': str(output / 'reference-bgra.bin'), 'maskSha256': hashlib.sha256(mask).hexdigest(),
            'bgraSha256': hashlib.sha256(bgra).hexdigest(), 'straightRgbaSha256': hashlib.sha256(rgba).hexdigest()}
        if application_cargo_lock is not None:
            config['referenceGenerator'] = build_reference_generator(application_cargo_lock, output)
    # First-frame eframe icon replacement may happen while the locked reference
    # tool builds. Borrow only the current handles after that work is complete.
    handles = collect_icon_handles(hwnd, pid, api)
    config['icons'] = [dict(item, handle=str(item['handle'] if item['handle'] < 1 << 63 else item['handle'] - (1 << 64))) for item in handles]
    (output / 'config.json').write_text(json.dumps(config), encoding='utf-8')
    (output / 'read-icons.ps1').write_text(POWERSHELL, encoding='utf-8')
    require_owned(hwnd, pid, api)
    command = [powershell, '-NoProfile', '-NonInteractive', '-File',
               str(output / 'read-icons.ps1'), '-Config', str(output / 'config.json')]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
    (output / 'powershell.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('owned runtime icon extraction failed: ' + result.stderr[-1500:])
    require_owned(hwnd, pid, api)
    if hashlib.sha256(ico.read_bytes()).hexdigest() != approved_ico_sha256.lower():
        raise ValueError("approved ICO changed during runtime readback")
    if runtime is not None:
        approved_runtime_png(runtime_png, approved_runtime_png_sha256)
    rows = json.loads((output / 'rendered.json').read_text(encoding='utf-8-sig'))
    if not isinstance(rows, list) or [r.get('role') for r in rows] != [r[0] for r in ROLES]:
        raise ValueError('missing or reordered runtime icon receipts')
    for row, handle in zip(rows, handles):
        for key, suffix in (("actual", "-actual.png"), ("expected", "-approved.png")):
            file = Path(row[key])
            if file.is_symlink() or file.resolve() != output / (row['role'] + suffix) or not file.is_file():
                raise ValueError("runtime icon receipt escaped its owned output files")
        if config.get('referenceGenerator'):
            generated = Path(row['generatedFrame'])
            if generated.is_symlink() or generated.resolve() != output / (row['role'] + '-eframe-reference.png') or hashlib.sha256(generated.read_bytes()).hexdigest() != row['generatedFrameSha256']:
                raise ValueError('generated eframe reference escaped or changed')
        compared = compare_icon_pngs(row['actual'], row['expected'], max_dimension=1024 if config.get('referenceGenerator') else max(runtime[1]) if runtime is not None else 512)
        if config.get('referenceGenerator') and row.get('winitExpected'):
            native = Path(row['winitExpected'])
            if native.is_symlink() or native.resolve() != output / (row['role'] + '-winit-approved.png'):
                raise ValueError('winit reference escaped its owned output')
            if not compared['passed']:
                fallback = compare_icon_pngs(row['actual'], native, max_dimension=max(runtime[1]))
                row['eframeComparison'] = compared
                compared = fallback
                row['acceptedReferencePipeline'] = 'winit native CreateIcon, exact authenticated source dimensions'
        row.update(compared)
        row.update({"handleSource": handle['source'], "borrowedHandleNeverDestroyed": True})
    report = {"schema": 1, "hwnd": hwnd, "pid": pid, "sourceIco": str(ico),
              "sourceIcoSha256": approved_ico_sha256.lower(), "runtimeExecuted": True,
              "passed": all(row['passed'] for row in rows), "icons": rows,
              "referencePipeline": "exact eframe image0.25.10 Lanczos3 PNG/CreateIconFromResourceEx" if config.get('referenceGenerator') else "winit CreateIcon from approved runtime PNG; straight BGRA plus alpha wrapping mask" if runtime else "approved ICO exact-size Icon constructor",
              "runtimePngReference": config.get('runtimeReference'),
              "referenceGenerator": config.get('referenceGenerator'),
              "evidenceScope": "owned WM_GETICON/class icon sources; no taskbar/compositor screenshot"}
    (output / 'runtime-icon-readback.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if not report['passed']:
        raise ValueError('runtime icon differs from approved owner icon; see runtime-icon-readback.json')
    return report
