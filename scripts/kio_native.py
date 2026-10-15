#!/usr/bin/env python3
"""Pinned full-source native builds. No web wrapper, remote creation, or implicit publication."""
from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.error
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"macos-arm64": "aarch64-apple-darwin", "windows-x64": "x86_64-pc-windows-msvc"}
HEX = re.compile(r"[a-f0-9]{64}\Z")
PRIVATE = re.compile(r"^(?:\.env(?:\..*)?|\.runtime\.json|id_rsa|id_ed25519|credentials\.json|token\.json)$", re.I)
RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.I)
PUBLIC_FILES = ("README.md", "LICENSE", ".gitignore", ".gitattributes", "manifests/word.lock.json", "manifests/programs.json",
                "patches/word/wordcraft-v0.7.0-kio-word.patch", "scripts/kio_native.py", "tests/test_builder.py", "tests/test_dependency_notices.py",
                ".github/workflows/full-native-word.yml")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_relative(value):
    require(isinstance(value, str) and value and "\\" not in value and "\0" not in value, "Invalid archive path")
    p = PurePosixPath(value)
    require(not p.is_absolute() and all(x not in ("", ".", "..") for x in value.split("/")), "Unsafe archive path: " + value)
    for part in p.parts:
        require(":" not in part and not part.endswith((".", " ")) and not RESERVED.fullmatch(part), "Unsafe cross-platform filename: " + value)
    return p


def check_public_path(value):
    p = safe_relative(value)
    require(not any(x in (".git", ".ssh", ".gnupg", "node_modules", "target", "__pycache__") for x in p.parts), "Private/build path refused: " + value)
    require(not any(PRIVATE.fullmatch(x) for x in p.parts), "Private filename refused: " + value)
    require(p.suffix.lower() not in (".p12", ".pfx", ".key", ".sqlite", ".sqlite3", ".db", ".pyc"), "Private file refused: " + value)
    return p


def regular_files(root, public=False, public_validator=None):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), "Expected a real directory")
    result = []
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in list(dirs):
            p = Path(base) / name
            require(not p.is_symlink(), "Directory symlink refused")
            if name in (".git", "__pycache__"):
                dirs.remove(name)
        for name in files:
            p = Path(base) / name
            require(p.is_file() and not p.is_symlink(), "Non-regular file refused")
            relative = p.relative_to(root).as_posix()
            ((public_validator or check_public_path) if public else safe_relative)(relative)
            result.append((relative, p))
    return sorted(result)


def tree_fingerprint(root, public_validator=None):
    h = hashlib.sha256()
    for relative, p in regular_files(root, public=True, public_validator=public_validator):
        h.update(relative.encode("utf-8") + b"\0" + digest(p).encode("ascii") + b"\n")
    return h.hexdigest()


def safe_extract(archive, destination, expected_root, max_bytes=768 * 1024 * 1024, public_validator=None):
    """Validate the entire tar before writing; links/devices/traversal/case collisions fail closed."""
    destination = Path(destination)
    require(not destination.exists(), "Extraction destination already exists")
    records, seen, total = [], set(), 0
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream.getmembers():
            name = member.name.rstrip("/")
            p = safe_relative(name)
            require(p.parts[0] == expected_root, "Unexpected archive root")
            require(member.isdir() or member.isfile(), "Archive link or special file refused: " + name)
            key = name.casefold()
            require(key not in seen, "Archive duplicate/case collision: " + name)
            seen.add(key)
            relative = PurePosixPath(*p.parts[1:]).as_posix() if len(p.parts) > 1 else ""
            if relative:
                (public_validator or check_public_path)(relative)
            total += member.size
            require(0 <= member.size <= 256 * 1024 * 1024 and total <= max_bytes and len(seen) <= 50000, "Archive expansion limit exceeded")
            records.append((member, relative))
        destination.mkdir(parents=True)
        try:
            for member, relative in records:
                if not relative:
                    continue
                target = destination.joinpath(*PurePosixPath(relative).parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with stream.extractfile(member) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    target.chmod(0o755 if member.mode & 0o111 else 0o644)
        except BaseException:
            shutil.rmtree(destination)
            raise


class LockedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        require(parsed.scheme == "https" and parsed.hostname == "codeload.github.com" and not parsed.username, "Archive redirect refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def archive_name(entry):
    return entry["root"] + ".tar.gz"


def verified_archive(entry, cache, offline=False):
    cache = Path(cache)
    require(not cache.is_symlink(), "Cache directory symlink refused")
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / archive_name(entry)
    if path.exists():
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == entry["bytes"] and digest(path) == entry["sha256"], "Cached archive does not match its immutable lock")
        return path
    require(not offline, "Pinned archive missing in offline cache: " + path.name)
    opener = urllib.request.build_opener(LockedRedirect())
    temporary = path.with_suffix(".download")
    require(not temporary.exists(), "Stale download exists; inspect and remove it explicitly")
    try:
        with opener.open(entry["url"], timeout=60) as source, temporary.open("xb") as output:
            count = 0
            while chunk := source.read(1024 * 1024):
                count += len(chunk)
                require(count <= entry["bytes"], "Downloaded archive exceeds locked size")
                output.write(chunk)
        require(count == entry["bytes"] and digest(temporary) == entry["sha256"], "Downloaded archive SHA/bytes mismatch")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def load_lock(app="word"):
    require(app == "word", "Only the reviewed Word pipeline is enabled")
    lock = json.loads((ROOT / "manifests" / (app + ".lock.json")).read_text(encoding="utf-8"))
    require(lock["schema"] == 1 and lock["id"] == app and lock["rust"] == "1.95.0", "Invalid build lock")
    require(lock["cargoPackages"] == ["wordcraft", "wordcraft-cli"], "The full native app and CLI must both be built")
    require(lock["name"] == "KIO Word" and lock["bundleId"] == "com.kio.word", "Unexpected product identity")
    require(re.fullmatch(r"0\.7\.0-kio\.[1-9][0-9]*", lock["version"]), "Invalid KIO release version")
    for key, repository in (("source", "storytold/wordcraft"), ("fonts", "storytold/craft-fonts")):
        entry = lock[key]
        require(entry["repository"] == repository and re.fullmatch(r"[a-f0-9]{40}", entry["commit"]), "Invalid immutable source")
        require(entry["url"] == "https://codeload.github.com/" + repository + "/tar.gz/" + entry["commit"], "Source URL outside fixed upstream")
        require(entry["root"] == repository.split("/")[1] + "-" + entry["commit"], "Invalid archive root")
        require(HEX.fullmatch(entry["sha256"]) and 0 < entry["bytes"] <= 128 * 1024 * 1024, "Invalid archive integrity data")
    patch = lock["branding"]
    require(patch["patch"] == "patches/word/wordcraft-v0.7.0-kio-word.patch" and isinstance(patch["sha256"], str) and HEX.fullmatch(patch["sha256"]), "Brand patch is not yet locked/reviewable")
    p = ROOT / patch["patch"]
    require(p.is_file() and not p.is_symlink() and digest(p) == patch["sha256"], "Brand patch integrity mismatch")
    return lock


def run(args, cwd=None, env=None, capture=False, timeout=None):
    result = subprocess.run([str(x) for x in args], cwd=cwd, env=env, check=True, timeout=timeout,
                            stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None)
    if capture:
        require(len(result.stdout) <= 16 * 1024 * 1024 and len(result.stderr) <= 1024 * 1024, "Unexpected command output size")
        return result.stdout.decode("utf-8", errors="replace").strip()
    return ""


def work_paths(app):
    work = ROOT / ".work" / app
    require(not work.is_symlink() and not work.parent.is_symlink(), "Work directory symlink refused")
    return work, work / "source", work / "craft-fonts"


def prepare(args, lock):
    work, source, fonts = work_paths(lock["id"])
    if work.exists():
        require(args.reset, "Prepared work already exists; use --reset to replace only this isolated work directory")
        shutil.rmtree(work)
    work.mkdir(parents=True)
    archives = {key: verified_archive(lock[key], args.archive_cache or ROOT / ".cache" / "archives", args.offline) for key in ("source", "fonts")}
    safe_extract(archives["source"], source, lock["source"]["root"])
    safe_extract(archives["fonts"], fonts, lock["fonts"]["root"])
    preserved = {str(p.relative_to(source)): digest(p) for p in source.rglob("Cargo.toml")}
    for name in ("Cargo.lock", "LICENSE-MIT", "LICENSE-APACHE", "NOTICE"):
        preserved[name] = digest(source / name)
    engines = {relative for relative, _ in regular_files(source) if relative.startswith("crates/") and "/src/" in relative}
    run(["git", "init", "--quiet"], cwd=source)
    run(["git", "config", "core.autocrlf", "false"], cwd=source)
    patch = ROOT / lock["branding"]["patch"]
    run(["git", "apply", "--check", "--binary", patch], cwd=source)
    run(["git", "apply", "--binary", patch], cwd=source)
    for name, sha in preserved.items():
        require((source / name).is_file() and digest(source / name) == sha, "Branding changed a protected Cargo/license file: " + name)
    require(all((source / relative).is_file() for relative in engines), "Branding removed original engine source")
    require(not any(p.is_file() and p.suffix.lower() != ".txt" for p in (source / "docs/brand").glob("*")), "Upstream trademark artwork must be removed from the modified distribution")
    plist_text = (source / "packaging/macos/Info.plist.in").read_text(encoding="utf-8")
    require(lock["bundleId"] in plist_text and lock["name"] in plist_text, "Brand patch did not supply the KIO bundle identity")
    record = {"schema": 1, "app": lock["id"], "lockSha256": digest(ROOT / "manifests/word.lock.json"),
              "sourceTreeSha256": tree_fingerprint(source), "fontsTreeSha256": tree_fingerprint(fonts),
              "source": lock["source"], "fonts": lock["fonts"], "branding": lock["branding"]}
    write_json(work / "prepared.json", record)
    print("Prepared the entire pinned WordCraft workspace and fonts with the locked KIO patch.")


def prepared(lock):
    work, source, fonts = work_paths(lock["id"])
    record = json.loads((work / "prepared.json").read_text(encoding="utf-8"))
    require(record["lockSha256"] == digest(ROOT / "manifests/word.lock.json"), "Build lock changed; prepare again")
    require(record["sourceTreeSha256"] == tree_fingerprint(source) and record["fontsTreeSha256"] == tree_fingerprint(fonts), "Prepared source/fonts were modified")
    return work, source, fonts, record


def build_env(lock, fonts, target_dir, target):
    env = os.environ.copy()
    env.update({"CRAFT_FONTS_DIR": str(fonts), "CRAFT_FONTS_REQUIRED": "1", "CARGO_TARGET_DIR": str(target_dir), "CARGO_HOME": os.environ.get("KIO_CARGO_HOME", str(ROOT / ".cache/cargo")),
                "SOURCE_DATE_EPOCH": str(lock["sourceDateEpoch"]), "WORDCRAFT_BUILD_SHA": lock["source"]["commit"],
                "WORDCRAFT_BUILD_DATE": time.strftime("%Y-%m-%d", time.gmtime(lock["sourceDateEpoch"]))})
    if target == "aarch64-apple-darwin":
        env["MACOSX_DEPLOYMENT_TARGET"] = "11.0"
    else:
        env["CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS"] = "-C target-feature=+crt-static"
        env["WORDCRAFT_REQUIRE_WINRES"] = "1"
    return env


def native_header(path, target, gui=False):
    with Path(path).open("rb") as stream:
        header = stream.read(4096)
    if target == "aarch64-apple-darwin":
        require(len(header) >= 32 and header[:4] == b"\xcf\xfa\xed\xfe", "Expected a native 64-bit little-endian Mach-O")
        require(struct.unpack_from("<I", header, 4)[0] == 0x0100000C, "Mach-O architecture is not arm64")
        require(struct.unpack_from("<I", header, 12)[0] == 2, "Mach-O is not an executable")
    else:
        require(len(header) >= 64 and header[:2] == b"MZ", "Expected a native Windows PE")
        offset = struct.unpack_from("<I", header, 0x3C)[0]
        with Path(path).open("rb") as stream:
            stream.seek(offset)
            pe = stream.read(128)
        require(len(pe) >= 94 and pe[:4] == b"PE\0\0" and struct.unpack_from("<H", pe, 4)[0] == 0x8664, "PE architecture is not x64")
        require(struct.unpack_from("<H", pe, 24)[0] == 0x20B, "PE is not 64-bit")
        require(struct.unpack_from("<H", pe, 0x5C)[0] == (2 if gui else 3), "PE GUI/CLI subsystem mismatch")


def build(args, lock):
    work, source, fonts, record = prepared(lock)
    target = TARGETS[args.platform]
    require((args.platform == "macos-arm64" and sys.platform == "darwin" and platform.machine() == "arm64") or
            (args.platform == "windows-x64" and sys.platform == "win32" and platform.machine().lower() in ("amd64", "x86_64")),
            "Build and smoke test on the actual target OS/architecture")
    target_dir = (ROOT / ".work/target" / args.platform).resolve()
    env = build_env(lock, fonts, target_dir, target)
    cargo = ["rustup", "run", lock["rust"], "cargo"]
    rustc = run(["rustup", "run", lock["rust"], "rustc", "--version"], env=env, capture=True)
    require(rustc.startswith("rustc " + lock["rust"] + " "), "Wrong Rust compiler")
    command = cargo + ["build", "--release", "--locked", "--target", target]
    for package in lock["cargoPackages"]:
        command += ["-p", package]
    run(command, cwd=source, env=env)
    test_command = cargo + ["test", "--release", "--locked", "--target", target]
    for package in lock["testPackages"]:
        test_command += ["-p", package]
    run(test_command, cwd=source, env=env)
    extension = ".exe" if args.platform.startswith("windows") else ""
    binaries = {key: target_dir / target / "release" / (name + extension) for key, name in lock["binaries"].items()}
    for key, path in binaries.items():
        native_header(path, target, key == "app")
    version = run([binaries["cli"], "--version"], cwd=source, env=env, capture=True, timeout=30)
    smoke = work / ("smoke-" + args.platform)
    smoke.mkdir(exist_ok=True)
    document, pdf, reopened = smoke / "sample.docx", smoke / "sample.pdf", smoke / "reopened.docx"
    run([binaries["cli"], "run", "--template", "sample", "--save", document], cwd=source, env=env, timeout=120)
    run([binaries["cli"], "convert", document, pdf], cwd=source, env=env, timeout=120)
    run([binaries["cli"], "convert", document, reopened], cwd=source, env=env, timeout=120)
    for path in (document, reopened):
        with zipfile.ZipFile(path) as archive:
            require("word/document.xml" in archive.namelist(), "DOCX smoke output is not a Word document")
    require(pdf.read_bytes().startswith(b"%PDF-"), "PDF smoke export failed")
    prepared(lock)  # Compilation must not rewrite the pinned source.
    result = {"schema": 1, "app": lock["id"], "platform": args.platform, "target": target,
              "version": lock["version"], "upstreamVersion": lock["upstreamVersion"], "rustc": rustc,
              "inputs": record, "binaries": {key: {"sha256": digest(p), "bytes": p.stat().st_size} for key, p in binaries.items()},
              "checks": {"nativeArchitecture": "passed", "upstreamCoreTests": "passed", "cliVersion": version,
                         "docxReopenAndPdf": "passed", "guiLaunch": "not-performed-by-orchestrator"},
              "upstreamGaps": lock["upstreamGaps"]}
    write_json(work / ("build-" + args.platform + ".json"), result)
    print("Built full native app + CLI; architecture, core tests and synthetic DOCX/PDF checks passed.")


def copy_license_tree(source, destination, public_validator=None):
    selected = []
    for relative, p in regular_files(source, public=True, public_validator=public_validator):
        name = p.name.upper()
        if name.startswith(("LICENSE", "COPYING", "NOTICE", "OFL", "UNLICENSE")) or name == "ATTRIBUTION.MD":
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
            selected.append(relative)
    require(selected, "No upstream license files found")
    return selected


_UPSTREAM_NOTICE_CACHE = {}

# Reviewed published archives declare MIT (alone or as an option) but omit a
# standalone license. These are exact published-source exceptions, not general
# license-expression exceptions: every original file is authenticated below.
# Older crates without VCS metadata are authenticated by their published
# archives only; no commit or immutable VCS URL is invented for them.
_REVIEWED_DECLARED_LICENSES = {
    "cms-0.2.3": {
        "name": "cms", "version": "0.2.3", "repository": "https://github.com/RustCrypto/formats/tree/master/cms",
        "vcsRepository": "RustCrypto/formats", "commit": "5821a21553509dbd03eae593b0a1fad4e2083d4e", "pathInVcs": "cms",
        "license": "Apache-2.0 OR MIT", "authors": ["RustCrypto Developers"],
        "vcsInfoPresent": True, "pathInVcsPresent": True, "declarationFiles": ["Cargo.toml", "Cargo.toml.orig", "README.md"],
        "archiveSha256": "7b77c319abfd5219629c45c34c89ba945ed3c5e49fcde9d16b6c3885f118a730", "archiveBytes": 179143,
        "filesManifestSha256": "3566b00b46b7b42cc0d6ed4424764f7d60db435144b2b68d2ae9671bb501caca", "fileCount": 62, "sourceBytes": 538193,
        "publicTestCertificates": {"tests/examples/example.pfx": {"bytes": 1516, "sha256": "94e84d9a00ed9545104823d95aab3741bb1544197f282e4031844f9ef40a05a6"}},
    },
    "fmt-derive-0.1.2": {
        "name": "fmt-derive", "version": "0.1.2", "repository": "https://github.com/danielschemmel/fmt-derive",
        "vcsRepository": "danielschemmel/fmt-derive", "commit": "3f1abe44dc5e36e467565d3bf636faba5193f2a1", "pathInVcs": "fmt-derive",
        "license": "MIT OR Apache-2.0", "authors": ["Daniel Schemmel <daniel@schemmel.net>"],
        "vcsInfoPresent": True, "pathInVcsPresent": True, "declarationFiles": ["Cargo.toml", "Cargo.toml.orig", "README.md"],
        "archiveSha256": "1cb4a4b45c26455885f8b462db12978e51f60cc914337bccb9a36faf93410169", "archiveBytes": 5201,
        "filesManifestSha256": "b35a3d17158fbc7ab8c2419e88b3bd582d78371b871e6f8a9e09830742ee7439", "fileCount": 14, "sourceBytes": 20515,
        "publicTestCertificates": {},
    },
    "fmt-derive-proc-0.1.2": {
        "name": "fmt-derive-proc", "version": "0.1.2", "repository": "https://github.com/danielschemmel/fmt-derive",
        "vcsRepository": "danielschemmel/fmt-derive", "commit": "3f1abe44dc5e36e467565d3bf636faba5193f2a1", "pathInVcs": "fmt-derive-proc",
        "license": "MIT OR Apache-2.0", "authors": ["Daniel Schemmel <daniel@schemmel.net>"],
        "vcsInfoPresent": True, "pathInVcsPresent": True, "declarationFiles": ["Cargo.toml", "Cargo.toml.orig", "README.md"],
        "archiveSha256": "7704da0760734344ce8753f15b21e97c6be85dc5a8f2c3a963fbd042b3380d23", "archiveBytes": 4154,
        "filesManifestSha256": "d7018a1d32aeed2ada20bbf7111847a834df461d6d31eeb70785542163c89101", "fileCount": 12, "sourceBytes": 24276,
        "publicTestCertificates": {},
    },
    "rustls-cng-0.7.1": {
        "name": "rustls-cng", "version": "0.7.1", "repository": "https://github.com/rustls/rustls-cng",
        "vcsRepository": "rustls/rustls-cng", "commit": "b9126716029a105a08c1786993922103d9865bad", "pathInVcs": "",
        "license": "MIT/Apache-2.0", "authors": ["Dmitry Pankratov <dmitry@pankratov.net>"],
        "vcsInfoPresent": True, "pathInVcsPresent": True, "declarationFiles": ["Cargo.toml", "Cargo.toml.orig", "README.md"],
        "archiveSha256": "3eeed9c3e96253f36d1cfdd593388ecca775b532b6ff0c649a3010f6af60fe70", "archiveBytes": 29106,
        "filesManifestSha256": "1cf3147636b5ca0f8d1e9bcf88cddb6527dc8fb6630cfe741b175c22ab9b85b9", "fileCount": 24, "sourceBytes": 87184,
        "publicTestCertificates": {
            "tests/assets/rustls-client.pfx": {"bytes": 2193, "sha256": "34fc3c153299596d2670c03aeb66dc272470e88453f60b3b0df54e7d0eb90164"},
            "tests/assets/rustls-ec.p12": {"bytes": 2249, "sha256": "189ffc17f91de863c32623757201684dfae1ac08017d5ecd180d066c5eaacd2c"},
            "tests/assets/rustls-server.pfx": {"bytes": 2257, "sha256": "4e0d0154a09176d129a6c3cacb82024409b6fe4fe541b3c1af9bfb1e60ea54ff"},
        },
    },
    "block-0.1.6": {
        "name": "block", "version": "0.1.6", "repository": "http://github.com/SSheldon/rust-block",
        "vcsRepository": None, "commit": None, "pathInVcs": None,
        "license": "MIT", "authors": ["Steven Sheldon"],
        "vcsInfoPresent": False, "pathInVcsPresent": False, "declarationFiles": ["Cargo.toml", "README.md"],
        "archiveSha256": "0d8c1fef690941d3e7788d328517591fecc684c084084702d6ff1641e993699a", "archiveBytes": 4077,
        "filesManifestSha256": "438aeb0004ae316f4618bf6597c498043e4b6a0640dd1b57e6c2e9e72d0807d3", "fileCount": 4, "sourceBytes": 15196,
        "publicTestCertificates": {},
    },
    "malloc_buf-0.0.6": {
        "name": "malloc_buf", "version": "0.0.6", "repository": "https://github.com/SSheldon/malloc_buf",
        "vcsRepository": None, "commit": None, "pathInVcs": None,
        "license": "MIT", "authors": ["Steven Sheldon"],
        "vcsInfoPresent": False, "pathInVcsPresent": False, "declarationFiles": ["Cargo.toml"],
        "archiveSha256": "62bb907fe88d54d8d9ce32a3cceab4218ed2f6b7d35617cafe9adf84e43919cb", "archiveBytes": 1239,
        "filesManifestSha256": "750a7cb75c76ac13a6448fec88535f22ca9b97432edc4f2e05e0a4b398b38130", "fileCount": 2, "sourceBytes": 2637,
        "publicTestCertificates": {},
    },
    "simd_helpers-0.1.0": {
        "name": "simd_helpers", "version": "0.1.0", "repository": "https://github.com/lu-zero/simd_helpers",
        "vcsRepository": "lu-zero/simd_helpers", "commit": "ca1a2f84aa386d758e98f8a609d990263932fb85", "pathInVcs": None,
        "license": "MIT", "authors": ["Luca Barbato <lu_zero@gentoo.org>"],
        "vcsInfoPresent": True, "pathInVcsPresent": False, "declarationFiles": ["Cargo.toml", "Cargo.toml.orig", "README.md"],
        "archiveSha256": "95890f873bec569a0362c235787f3aca6e1e887302ba4840839bcc6459c42da6", "archiveBytes": 1527,
        "filesManifestSha256": "7b361c6f6baf32d9baf33d39ec80036472a375245075b7d279cfb47eff1155bf", "fileCount": 7, "sourceBytes": 2500,
        "publicTestCertificates": {},
    },
    "zune-inflate-0.2.54": {
        "name": "zune-inflate", "version": "0.2.54", "repository": None,
        "vcsRepository": "etemesi254/zune-image", "commit": "69502ce83fdfecdd0beefd677e2abb3781b29d98", "pathInVcs": "zune-inflate",
        "license": "MIT OR Apache-2.0 OR Zlib", "authors": [],
        "vcsInfoPresent": True, "pathInVcsPresent": True, "declarationFiles": ["Cargo.toml", "Cargo.toml.orig", "README.md"],
        "archiveSha256": "73ab332fe2f6680068f3582b16a24f90ad7096d5d39b974d1c0aff0125116f02", "archiveBytes": 37973,
        "filesManifestSha256": "eb32c5ed232eb27d811b9c3c662514e4a4c6a898bef7bad44a81e5c0388319df", "fileCount": 16, "sourceBytes": 129125,
        "publicTestCertificates": {},
        # The published manifests omit repository/authors. Do not infer either
        # field from a homepage; authenticate these reviewed VCS-root originals.
        "upstreamNotices": [
            {"path": "LICENSE.md", "bytes": 384, "sha256": "e870d7fd7819a9f0453c62798cb52ae95d148a8c91dc2de1d983f997143c72de"},
            {"path": "LICENSE-ZLIB", "bytes": 818, "sha256": "7fa429541e55b1509909e058f2d21a37467e4958ec713b357f6e0cf9dc4ee352"},
        ],
    },
}


def _reviewed_json(path):
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= 1024 * 1024, "Invalid reviewed crate metadata")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate reviewed crate JSON key")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def reviewed_pinned_upstream_notices(pin):
    """Return only reviewed original notice bytes, authenticated even on cache hits."""
    records = []
    for notice in pin.get("upstreamNotices", []):
        require(set(notice) == {"path", "bytes", "sha256"} and notice["path"] in ("LICENSE.md", "LICENSE-ZLIB") and
                isinstance(notice["bytes"], int) and 20 <= notice["bytes"] <= 65536 and HEX.fullmatch(notice["sha256"]),
                "Invalid pinned original notice descriptor")
        require(pin["vcsInfoPresent"] and re.fullmatch(r"[a-f0-9]{40}", pin["commit"]), "Pinned notice needs an immutable VCS commit")
        url = "https://raw.githubusercontent.com/" + pin["vcsRepository"] + "/" + pin["commit"] + "/" + notice["path"]
        cache = ROOT / ".cache/upstream-licenses" / (hashlib.sha256(url.encode("ascii")).hexdigest() + ".txt")
        if cache.exists() or cache.is_symlink():
            require(cache.is_file() and not cache.is_symlink() and cache.stat().st_size == notice["bytes"], "Invalid pinned original notice cache")
            content = cache.read_bytes()
        else:
            request = urllib.request.Request(url, headers={"User-Agent": "KIO-native-license-collector"})
            with urllib.request.urlopen(request, timeout=30) as result:
                require(result.url == url, "Pinned original notice redirect refused")
                content = result.read(notice["bytes"] + 1)
        require(len(content) == notice["bytes"] and hashlib.sha256(content).hexdigest() == notice["sha256"],
                "Pinned original upstream notice checksum mismatch: " + notice["path"])
        # Never retain an unverified network response, even as a cache entry.
        if not cache.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(content)
        records.append({**notice, "url": url, "content": content})
    return records


def reviewed_declared_license(package, folder, destination):
    """Retain exact reviewed original crates, any pinned upstream notices and a labelled MIT body."""
    label = package["name"] + "-" + package["version"]
    pin = _REVIEWED_DECLARED_LICENSES.get(label)
    require(pin is not None, "Crate has no reviewed omitted-license exception: " + label)
    require(all(package.get(key) == pin[key] for key in ("name", "version", "repository", "license", "authors")) and
            package.get("source") == "registry+https://github.com/rust-lang/crates.io-index" and not package.get("license_file"),
            "Reviewed crate metadata differs from its exact published declaration: " + label)
    require(folder.is_dir() and not folder.is_symlink(), "Invalid reviewed crate source directory")
    checksum_path = folder / ".cargo-checksum.json"
    checksum = _reviewed_json(checksum_path)
    require(isinstance(checksum, dict) and set(checksum) == {"files", "package"} and checksum["package"] == pin["archiveSha256"],
            "Reviewed crate package checksum mismatch: " + label)
    hashes = checksum["files"]
    require(isinstance(hashes, dict) and len(hashes) == pin["fileCount"] and
            all(isinstance(name, str) and isinstance(value, str) and HEX.fullmatch(value) for name, value in hashes.items()),
            "Invalid reviewed crate file checksum map: " + label)
    canonical = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    require(hashlib.sha256(canonical).hexdigest() == pin["filesManifestSha256"], "Reviewed crate published file manifest mismatch: " + label)
    declaration_files = pin["declarationFiles"]
    require(declaration_files and "Cargo.toml" in declaration_files and len(declaration_files) == len(set(declaration_files)) and
            all(name in hashes for name in declaration_files),
            "Reviewed declaration source files missing")
    if pin["vcsInfoPresent"]:
        require(".cargo_vcs_info.json" in hashes, "Reviewed crate published VCS metadata missing")
        vcs = _reviewed_json(folder / ".cargo_vcs_info.json")
        require(isinstance(vcs, dict) and isinstance(vcs.get("git"), dict) and vcs["git"].get("sha1") == pin["commit"] and
                (("path_in_vcs" in vcs) == pin["pathInVcsPresent"]) and vcs.get("path_in_vcs") == pin["pathInVcs"],
                "Reviewed crate immutable VCS identity mismatch: " + label)
    else:
        require(".cargo_vcs_info.json" not in hashes and not (folder / ".cargo_vcs_info.json").exists() and
                pin["commit"] is None and pin["vcsRepository"] is None and pin["pathInVcs"] is None,
                "Reviewed legacy crate must not invent VCS metadata: " + label)
    # Do not use regular_files() here: it intentionally skips .git/__pycache__,
    # whereas an exact published-crate copy must reject every extra path.
    actual = {}
    for base, directories, filenames in os.walk(folder, followlinks=False):
        for name in directories:
            require(not (Path(base) / name).is_symlink(), "Reviewed crate directory symlink refused")
            check_public_path((Path(base) / name).relative_to(folder).as_posix())
        for name in filenames:
            path = Path(base) / name
            require(path.is_file() and not path.is_symlink(), "Reviewed crate link or special file refused")
            relative = path.relative_to(folder).as_posix()
            safe_relative(relative)
            actual[relative] = path
    # Cargo creates .cargo-ok after unpacking. It is not published source and
    # is never copied. The generated checksum file is retained as evidence.
    allowed = set(hashes) | {".cargo-checksum.json"}
    if ".cargo-ok" in actual:
        require(actual[".cargo-ok"].stat().st_size <= 1024, "Unexpected Cargo unpack marker size")
        allowed.add(".cargo-ok")
    require(set(actual) == allowed, "Reviewed crate has missing or additional source files: " + label)
    original, total = [], 0
    for relative, expected in sorted(hashes.items()):
        path = actual[relative]
        size = path.stat().st_size
        require(size <= 2 * 1024 * 1024 and digest(path) == expected, "Reviewed crate source checksum mismatch: " + relative)
        total += size
        try:
            check_public_path(relative)
        except ValueError:
            certificate = pin["publicTestCertificates"].get(relative)
            require(certificate is not None and certificate == {"bytes": size, "sha256": expected},
                    "Unreviewed private filename in original crate: " + relative)
        original.append({"path": relative, "bytes": size, "sha256": expected})
    require(total == pin["sourceBytes"] and total <= 2 * 1024 * 1024, "Reviewed crate complete source byte count mismatch")
    for relative, certificate in pin["publicTestCertificates"].items():
        require(relative in hashes and hashes[relative] == certificate["sha256"] and actual[relative].stat().st_size == certificate["bytes"],
                "Reviewed public test certificate checksum mismatch")
    require(not destination.exists() and not destination.is_symlink(), "Reviewed crate notice output must be fresh")
    # Authenticate the exact original notices before any destination is created.
    upstream_notices = reviewed_pinned_upstream_notices(pin)
    # Authenticate every input before writing anything, and verify copied bytes.
    for item in original + [{"path": ".cargo-checksum.json", "bytes": checksum_path.stat().st_size, "sha256": digest(checksum_path)}]:
        output = destination / "original-crate" / item["path"]
        output.parent.mkdir(parents=True, exist_ok=True)
        with actual[item["path"]].open("rb") as source, output.open("xb") as target:
            shutil.copyfileobj(source, target)
        require(output.stat().st_size == item["bytes"] and digest(output) == item["sha256"], "Reviewed original source changed while copying")
    mit = (ROOT / "LICENSE").read_text(encoding="utf-8")
    marker = "Permission is hereby granted"
    require(mit.count(marker) == 1, "Standard MIT source body is missing or ambiguous")
    body = mit[mit.index(marker):].strip() + "\n"
    require("THE SOFTWARE IS PROVIDED" in body and "KIO" not in body and "Copyright (c)" not in body, "Standard MIT body must not add KIO copyright")
    selection = ("This exact published crate declares MIT; this redistributed copy uses that declared license.\n" if pin["license"] == "MIT" else
                 "This exact published crate declares " + pin["license"] + "; KIO elects the MIT option for this redistributed copy.\n")
    explanation = ("KIO-supplied standard MIT license text; this is not an upstream license file.\n" + selection +
                   "The original authors, license declarations and complete published source bytes are preserved in original-crate/.\n"
                   "See REVIEWED-LICENSE-PROVENANCE.json for their exact authenticated origin.\n"
                   "The standard body below adds no copyright holder or copyright notice and does not replace original source notices.\n\n")
    standard = destination / "STANDARD-MIT-TEXT.txt"
    standard.write_text(explanation + body, encoding="utf-8")
    archive_url = "https://static.crates.io/crates/" + pin["name"] + "/" + label + ".crate"
    immutable_vcs_url = ("https://github.com/" + pin["vcsRepository"] + "/tree/" + pin["commit"] +
                         ("/" + pin["pathInVcs"] if pin["pathInVcs"] else "")) if pin["vcsInfoPresent"] else None
    provenance = {"schema": "kio.reviewed-declared-license.v1", "name": pin["name"], "version": pin["version"],
                  "repository": pin["repository"], "source": package["source"], "authors": pin["authors"],
                  "declaredLicense": pin["license"], "selectedLicense": "MIT", "commit": pin["commit"], "pathInVcs": pin["pathInVcs"],
                  "publishedArchive": {"url": archive_url,
                                       "bytes": pin["archiveBytes"], "sha256": pin["archiveSha256"]},
                  "sourceVerification": "Cargo package checksum plus pinned published path-to-SHA manifest and every original file SHA/byte count",
                  "filesManifestSha256": pin["filesManifestSha256"], "cargoChecksumFileSha256": digest(checksum_path),
                  "originalFiles": original, "sourceBytes": total, "excludedGeneratedFiles": [".cargo-ok"] if ".cargo-ok" in actual else [],
                  "originalDeclarationFiles": [{"path": "original-crate/" + name, "sha256": hashes[name],
                                                "publishedArchiveMember": label + "/" + name, "publishedArchiveUrl": archive_url}
                                               for name in declaration_files],
                  "immutableVcsUrl": immutable_vcs_url,
                  "publishedVcsMetadata": {"present": pin["vcsInfoPresent"], "pathInVcsKeyPresent": pin["pathInVcsPresent"],
                                           "status": "published-immutable-commit" if pin["vcsInfoPresent"] else "absent-in-published-archive"},
                  "sourceAuthority": "Exact checksum-authenticated published crate archive; VCS identity is supplementary only when published",
                  "reviewedPublicTestCertificates": pin["publicTestCertificates"],
                  "omission": ("This published crate omits standalone license files and its repository metadata; the reviewed immutable VCS-root originals are retained separately" if upstream_notices else
                               "No standalone upstream license file exists in this published crate or its reviewed immutable source location" if pin["vcsInfoPresent"] else
                               "No standalone license file or immutable VCS metadata exists in this exact published crate; the reviewed source authority is its published archive"),
                  "standardMit": {"file": standard.name, "sha256": digest(standard), "bodySha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                                  "providedBy": "KIO", "isUpstreamOriginal": False, "addsCopyrightNotice": False}}
    proof = destination / "REVIEWED-LICENSE-PROVENANCE.json"
    if upstream_notices:
        provenance["upstreamNotices"] = []
        for notice in upstream_notices:
            output = destination / ("UPSTREAM-" + notice["path"])
            output.write_bytes(notice["content"])
            require(output.stat().st_size == notice["bytes"] and digest(output) == notice["sha256"], "Copied original upstream notice changed")
            provenance["upstreamNotices"].append({key: notice[key] for key in ("path", "url", "bytes", "sha256")})
    write_json(proof, provenance)
    return [{"file": path.name, "url": None, "sha256": digest(path), "originalCrateFiles": len(original),
             "reason": "Exact reviewed published crate omits a standalone license; complete source/declarations retained and the declared MIT license explicitly selected"}
            for path in (standard, proof)] + [{"file": "UPSTREAM-" + notice["path"], "url": notice["url"], "sha256": notice["sha256"],
                                              "reason": "Exact reviewed immutable VCS-root original notice"} for notice in upstream_notices]


def upstream_license_files(package, folder, cache):
    """Some published crates omit workspace-root licenses. Fetch only their immutable VCS root."""
    repository = re.fullmatch(r"https?://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?(?:/tree/[^?#]+)?/?", package.get("repository") or "")
    require(repository, "Missing license requires an exact GitHub source repository: " + package["name"])
    vcs = folder / ".cargo_vcs_info.json"
    if vcs.is_file():
        commit = json.loads(vcs.read_text(encoding="utf-8"))["git"]["sha1"]
    else:
        commit = (package.get("source") or "").rsplit("#", 1)[-1]
    require(re.fullmatch(r"[a-f0-9]{40}", commit), "Missing license requires an immutable source commit")
    root = "https://raw.githubusercontent.com/" + repository[1] + "/" + commit + "/"
    if root in _UPSTREAM_NOTICE_CACHE:
        return _UPSTREAM_NOTICE_CACHE[root]
    cache.mkdir(parents=True, exist_ok=True)
    candidates = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENSE-MIT", "LICENSE-APACHE", "LICENSE-MIT.txt", "LICENSE-APACHE.txt", "LICENCE", "LICENCE.md", "COPYING", "LICENSE-ZLIB", "LICENSE_MIT", "LICENSE_APACHE", "NOTICE", "NOTICE.md")

    def fetch(name):
        url = root + name
        path = cache / (hashlib.sha256(url.encode("ascii")).hexdigest() + ".txt")
        if not path.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "KIO-native-license-collector"})
            try:
                with urllib.request.urlopen(request, timeout=30) as result:
                    require(result.url == url, "License redirect refused")
                    content = result.read(4 * 1024 * 1024 + 1)
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                raise
            require(20 <= len(content) <= 4 * 1024 * 1024 and not content.lstrip().lower().startswith((b"<!doctype html", b"<html")), "Unexpected upstream license response")
            path.write_bytes(content)
        require(path.is_file() and not path.is_symlink(), "Invalid license cache file")
        return name, path, url

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        records = [record for record in pool.map(fetch, candidates) if record is not None]
    _UPSTREAM_NOTICE_CACHE[root] = records
    return records


def dependency_source_files(package, folder):
    """Retain one reviewed immutable winit license link without allowing arbitrary source links."""
    expected_source = "git+https://github.com/skylartaylor/winit.git?rev=3d51077fd1a966f84df9ef287839dc84fd5b4ca7#3d51077fd1a966f84df9ef287839dc84fd5b4ca7"
    if not (package.get("name") == "winit" and package.get("version") == "0.30.13" and package.get("source") == expected_source):
        return regular_files(folder)
    root = Path(folder).resolve()
    link, target = root / "dpi/LICENSE", root / "LICENSE"
    require(link.is_symlink() or link.is_file(), "Reviewed winit license link missing")
    # Windows Git may materialize a symlink as its exact 10-byte target text.
    require((link.is_symlink() and os.readlink(link) == "../LICENSE") or
            (not link.is_symlink() and link.is_file() and link.stat().st_size == 10 and link.read_bytes() == b"../LICENSE"),
            "Reviewed winit license link target changed")
    require(target.is_file() and not target.is_symlink() and target.stat().st_size == 11323 and
            digest(target) == "6dc0e068dcf3a5bc8e054205b85b7720e1d49265bbc64bf515d2cf79197df69a",
            "Reviewed winit original license changed")
    result = []
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in list(dirs):
            p = Path(base) / name
            require(not p.is_symlink(), "Directory symlink refused")
            if name in (".git", "__pycache__"):
                dirs.remove(name)
        for name in files:
            p = Path(base) / name
            relative = p.relative_to(root).as_posix()
            safe_relative(relative)
            if relative == "dpi/LICENSE":
                # Copy the authenticated original license, preserving the link's logical path.
                result.append((relative, target))
            else:
                require(p.is_file() and not p.is_symlink(), "Non-regular file refused: " + relative)
                result.append((relative, p))
    return sorted(result)


def dependency_licenses(lock, source, env, target, destination):
    metadata = json.loads(run(["rustup", "run", lock["rust"], "cargo", "metadata", "--locked", "--format-version", "1", "--filter-platform", target], cwd=source, env=env, capture=True, timeout=600))
    allowed_roots = [source.resolve(), Path(env["CARGO_HOME"]).resolve()]
    index, missing = [], []
    for package in metadata["packages"]:
        folder = Path(package["manifest_path"]).parent.resolve()
        require(any(folder.is_relative_to(p) for p in allowed_roots), "Dependency source is outside the pinned workspace/Cargo cache")
        label = package["name"] + "-" + package["version"]
        safe_relative(label)
        if folder.is_relative_to(source.resolve()):
            continue  # Workspace license already included in full.
        names = set()
        for p in folder.iterdir():
            if p.is_file() and p.name.upper().startswith(("LICENSE", "COPYING", "NOTICE", "UNLICENSE", "OFL")):
                names.add(p)
        # REUSE packages ship their SPDX texts inside LICENSES/ rather than a
        # root LICENSE. Preserve those original files before seeking any remote
        # fallback; a Codeberg-hosted crate needs no GitHub mirror to retain them.
        reuse = folder / "LICENSES"
        if reuse.is_dir():
            require(not reuse.is_symlink(), "Dependency license directory is a symlink")
            for p in reuse.iterdir():
                if p.is_file() and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+-]*\.txt", p.name):
                    names.add(p)
        if package.get("license_file"):
            p = (folder / package["license_file"]).resolve()
            require(p.is_relative_to(folder), "Dependency license path escaped package")
            names.add(p)
        if not names and (package.get("source") or "").startswith("git+"):
            for ancestor in folder.parents:
                if not ancestor.is_relative_to(Path(env["CARGO_HOME"]).resolve()):
                    break
                if (ancestor / "Cargo.toml").is_file():
                    names.update(p for p in ancestor.iterdir() if p.is_file() and p.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")))
                    if names:
                        break
        retrieved = []
        if label in _REVIEWED_DECLARED_LICENSES:
            require(not names, "Reviewed omitted-license crate unexpectedly has a standalone notice")
            retrieved = reviewed_declared_license(package, folder, destination / label)
        elif not names:
            try:
                for filename, p, url in upstream_license_files(package, folder, ROOT / ".cache/upstream-licenses"):
                    out = destination / label / ("UPSTREAM-" + filename)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(p, out)
                    retrieved.append({"file": out.name, "url": url, "sha256": digest(p)})
            except ValueError:
                missing.append(label)
            if not retrieved and label not in missing:
                # This exact published MIT crate has no standalone license even in its
                # pinned VCS root. Retain every original byte, author declaration and
                # license expression, plus an explicitly labelled standard MIT text.
                if label == "dispatch-0.2.0" and package.get("license") == "MIT" and package.get("repository") == "http://github.com/SSheldon/rust-dispatch":
                    files = regular_files(folder, public=True)
                    require(sum(p.stat().st_size for _, p in files) < 1024 * 1024, "Reviewed dispatch source copy exceeded its bound")
                    for relative, p in files:
                        out = destination / label / "original-crate" / relative
                        out.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(p, out)
                    out = destination / label / "STANDARD-MIT-TEXT.txt"
                    mit = (ROOT / "LICENSE").read_text(encoding="utf-8")
                    mit = mit.replace("Copyright (c) 2026 KIO", "Original authors: " + ", ".join(package["authors"]) + " (see original-crate/Cargo.toml.orig).")
                    out.write_text("Standard MIT text included by KIO because the original crate declares MIT but omits a standalone license file. Original source and metadata are retained unchanged.\n\n" + mit, encoding="utf-8")
                    retrieved.append({"file": out.name, "url": None, "sha256": digest(out), "originalCrateFiles": len(files), "reason": "Original published crate declares MIT and has no standalone license file"})
                else:
                    missing.append(label)
        nested = [(relative, p) for relative, p in dependency_source_files(package, folder) if "/" in relative and Path(relative).name.upper().startswith(("LICENSE", "COPYING", "NOTICE", "OFL", "UNLICENSE"))]
        for relative, p in nested:
            require(p.stat().st_size <= 4 * 1024 * 1024, "Invalid nested license file")
            out = destination / label / "bundled-notices" / relative
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, out)
        notice_paths = {p: p.relative_to(folder).as_posix() if p.is_relative_to(folder) else p.name for p in names}
        for p in sorted(names):
            require(p.is_file() and not p.is_symlink() and p.stat().st_size <= 4 * 1024 * 1024, "Invalid dependency license file")
            out = destination / label / notice_paths[p]
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, out)
        index.append({"name": package["name"], "version": package["version"], "license": package.get("license"),
                      "repository": package.get("repository"), "files": sorted(notice_paths.values()) + [r["file"] for r in retrieved], "immutableUpstreamNotices": retrieved, "bundledNotices": [r for r, _ in nested]})
    write_json(destination / "index.json", index)
    require(not missing, "Dependencies without a packaged license file need review: " + ", ".join(missing))


def make_notices(lock, source, fonts, destination, record, env, target):
    destination.mkdir(parents=True, exist_ok=True)
    copy_license_tree(source, destination / "WordCraft")
    copy_license_tree(fonts, destination / "craft-fonts")
    dependency_licenses(lock, source, env, target, destination / "Rust-dependencies")
    for name in ("KIO-FORK.md", "README.md", "ROADMAP.md", "docs/gaps.md", "docs/target-app-parity.md"):
        p = source / name
        if p.is_file():
            out = destination / "WordCraft" / name
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, out)
    write_json(destination / "BUILD-PROVENANCE.json", record)
    (destination / "KIO-README.txt").write_text(
        "KIO Word " + lock["version"] + "\nBased on the complete WordCraft " + lock["upstreamVersion"] + " native application.\n"
        "The original application engine, commands and formats are retained.\n"
        "This is a development fork; command-registry coverage is not Microsoft Word compatibility.\n"
        "Read upstream ROADMAP.md, docs/gaps.md and docs/target-app-parity.md for limitations.\n"
        "No Apple notarization or Windows publisher certificate is provided by this pipeline.\n"
        "Source: use the matching KIO Word full-source release asset with fonts, Cargo.lock and build instructions.\n"
        "No Electron prototype runtime is included. No hosted AI account or personal data is included.\n", encoding="utf-8")


def existing_build(args, lock, source, fonts, record):
    """Explicit import of a caller-reviewed host build; never claim this orchestrator compiled it."""
    target = TARGETS[args.platform]
    require(args.platform == "macos-arm64" and sys.platform == "darwin" and platform.machine() == "arm64", "Existing-target import is limited to the reviewed native Mac host build")
    base = Path(args.existing_target).resolve()
    folder = base if base.name == "release" else base / "release"
    binaries = {key: folder / name for key, name in lock["binaries"].items()}
    for key, p in binaries.items():
        require(p.is_file(), "Missing full native binary")
        native_header(p, target, key == "app")
    version = run([binaries["cli"], "--version"], capture=True, timeout=30)
    app_version = run([binaries["app"], "--version"], capture=True, timeout=30)
    require(re.match(r"wordcraft-cli " + re.escape(lock["upstreamVersion"]) + r"(?:\s|$)", version) and
            re.match(r"wordcraft " + re.escape(lock["upstreamVersion"]) + r"(?:\s|$)", app_version),
            "Existing binaries do not identify as the pinned full WordCraft app/CLI version")
    result = {"schema": 1, "app": lock["id"], "platform": args.platform, "target": target, "version": lock["version"],
              "upstreamVersion": lock["upstreamVersion"], "inputs": record, "buildOrigin": "existing-host-build-explicitly-selected-by-caller",
              "checks": {"nativeArchitecture": "passed", "cliVersion": version, "appVersion": app_version,
                         "upstreamCoreTests": "not-repeated-for-import", "docxReopenAndPdf": "not-repeated-for-import", "guiLaunch": "not-performed-by-orchestrator"},
              "binaries": {key: {"sha256": digest(p), "bytes": p.stat().st_size} for key, p in binaries.items()}, "upstreamGaps": lock["upstreamGaps"]}
    return binaries, result


def package(args, lock):
    work, source, fonts, inputs = prepared(lock)
    target = TARGETS[args.platform]
    require((args.platform == "macos-arm64" and sys.platform == "darwin") or (args.platform == "windows-x64" and sys.platform == "win32"), "Package on the actual target OS")
    target_dir = ROOT / ".work/target" / args.platform
    env = build_env(lock, fonts, target_dir, target)
    if args.existing_target:
        binaries, record = existing_build(args, lock, source, fonts, inputs)
    else:
        record = json.loads((work / ("build-" + args.platform + ".json")).read_text(encoding="utf-8"))
        require(record["inputs"] == inputs, "Build provenance differs from prepared input")
        extension = ".exe" if args.platform.startswith("windows") else ""
        binaries = {key: target_dir / target / "release" / (name + extension) for key, name in lock["binaries"].items()}
    for key, p in binaries.items():
        require(p.is_file() and digest(p) == record["binaries"][key]["sha256"], "Built binary changed before packaging")
        native_header(p, target, key == "app")
    stage = work / ("package-" + args.platform)
    require(not stage.exists(), "Package staging exists; inspect/remove this isolated package directory before repeating")
    stage.mkdir()
    output = ROOT / "dist" / (lock["id"] + "-" + args.platform)
    require(not output.exists(), "Release output already exists; refuse to overwrite a reviewable release")
    output.mkdir(parents=True)
    base = "KIO-Word-" + lock["version"] + "-" + args.platform
    if args.platform == "macos-arm64":
        app = stage / "KIO Word.app"
        macos, resources = app / "Contents/MacOS", app / "Contents/Resources"
        macos.mkdir(parents=True)
        resources.mkdir()
        shutil.copy2(binaries["app"], macos / "KIO Word")
        shutil.copy2(binaries["cli"], macos / "kio-word-cli")
        for p in macos.iterdir():
            p.chmod(0o755)
        shutil.copyfile(source / lock["icon"], resources / "KIO Word.icns")
        text = (source / "packaging/macos/Info.plist.in").read_text(encoding="utf-8")
        text = text.replace("@VERSION@", lock["version"]).replace("@SHORT_VERSION@", lock["upstreamVersion"]).replace("@BUILD_SHA@", lock["source"]["commit"])
        info = plistlib.loads(text.encode("utf-8"))
        require(info["CFBundleIdentifier"] == lock["bundleId"] and info["CFBundleExecutable"] == "KIO Word" and info["CFBundleIconFile"] == "KIO Word", "Unexpected patched bundle metadata")
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
        (app / "Contents/PkgInfo").write_bytes(b"APPL????")
        make_notices(lock, source, fonts, resources / "OpenSourceLicenses", record, env, target)
        identity = os.environ.get("KIO_MAC_SIGN_IDENTITY", "-")
        sign_basic = ["codesign", "--force", "--sign", identity, "--timestamp=none" if identity == "-" else "--timestamp"]
        sign = sign_basic.copy()
        if identity != "-":
            sign += ["--options", "runtime", "--entitlements", source / "packaging/macos/entitlements.plist"]
        for p in (macos / "kio-word-cli", macos / "KIO Word", app):
            run(sign + [p])
        run(["codesign", "--verify", "--strict", "--deep", app])
        run(["ditto", "-c", "-k", "--norsrc", "--noextattr", "--keepParent", app, output / (base + ".zip")])
        dmg_stage = stage / "dmg"
        dmg_stage.mkdir()
        run(["ditto", app, dmg_stage / app.name])
        (dmg_stage / "Applications").symlink_to("/Applications")
        run(["hdiutil", "makehybrid", "-hfs", "-hfs-volume-name", "KIO Word", "-o", stage / "raw.dmg", dmg_stage])
        run(["hdiutil", "convert", stage / "raw.dmg", "-format", "UDZO", "-imagekey", "zlib-level=9", "-o", output / (base + ".dmg")])
        run(sign_basic + [output / (base + ".dmg")])
        run(["codesign", "--verify", "--strict", output / (base + ".dmg")])
        record["signing"] = {"kind": "ad-hoc" if identity == "-" else "caller-supplied-identity", "notarized": False}
    else:
        folder = stage / "KIO Word"
        folder.mkdir()
        shutil.copy2(binaries["app"], folder / "KIO Word.exe")
        shutil.copy2(binaries["cli"], folder / "kio-word-cli.exe")
        make_notices(lock, source, fonts, folder / "OpenSourceLicenses", record, env, target)
        with zipfile.ZipFile(output / (base + ".zip"), "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for relative, p in regular_files(folder, public=True):
                archive.write(p, "KIO Word/" + relative)
        record["signing"] = {"kind": "unsigned", "publisherCertificate": False}
    write_json(output / (base + "-provenance.json"), record)
    finalize_release(output, lock, args.platform)
    print("Full native package: " + str(output))


def finalize_release(output, lock, kind):
    base = "KIO-Word-" + lock["version"] + "-" + kind
    files = [{"path": relative, "sha256": digest(p), "bytes": p.stat().st_size} for relative, p in regular_files(output, public=True)]
    require(files and all("/" not in f["path"] for f in files), "Release artifacts must be a flat, explicit file list")
    manifest = output / (base + "-manifest.json")
    write_json(manifest, {"schema": 1, "app": lock["id"], "version": lock["version"], "kind": kind,
                          "upstreamCommit": lock["source"]["commit"], "brandingPatchSha256": lock["branding"]["sha256"], "files": files})
    entries = files + [{"path": manifest.name, "sha256": digest(manifest), "bytes": manifest.stat().st_size}]
    (output / (base + "-SHA256SUMS.txt")).write_text("".join(f["sha256"] + "  " + f["path"] + "\n" for f in entries), encoding="utf-8")
    verify_release(output)


def verify_release(folder, expected=None, expected_kind=None):
    folder = Path(folder)
    manifests = list(folder.glob("KIO-Word-*-manifest.json"))
    require(len(manifests) == 1, "Expected exactly one release manifest")
    path = manifests[0]
    value = json.loads(path.read_text(encoding="utf-8"))
    require(value["schema"] == 1 and value["app"] == "word" and value["kind"] in (*TARGETS, "source"), "Invalid release manifest identity")
    require(re.fullmatch(r"0\.7\.0-kio\.[1-9][0-9]*", value["version"]) and re.fullmatch(r"[a-f0-9]{40}", value["upstreamCommit"]) and HEX.fullmatch(value["brandingPatchSha256"]), "Invalid release input identity")
    if expected is not None:
        require(value["version"] == expected["version"] and value["upstreamCommit"] == expected["source"]["commit"] and value["brandingPatchSha256"] == expected["branding"]["sha256"], "Release does not match the reviewed source/patch lock")
    if expected_kind is not None:
        require(value["kind"] == expected_kind, "Release platform mismatch")
    prefix = "KIO-Word-" + value["version"] + "-" + value["kind"]
    require(path.name == prefix + "-manifest.json", "Release manifest name does not match content")
    seen = {path.name, prefix + "-SHA256SUMS.txt"}
    suffixes = {"macos-arm64": (".zip", ".dmg", "-provenance.json"), "windows-x64": (".zip", "-provenance.json"), "source": (".zip", "-provenance.json")}
    require({item["path"] for item in value["files"]} == {prefix + suffix for suffix in suffixes[value["kind"]]}, "Release file allowlist mismatch")
    checksum_lines = []
    for item in value["files"]:
        name = item["path"]
        require(safe_relative(name).name == name and name.startswith(prefix) and name not in seen, "Unexpected release filename")
        require(HEX.fullmatch(item["sha256"]) and 0 < item["bytes"] <= 2 * 1024 * 1024 * 1024, "Invalid release file metadata")
        p = folder / name
        require(p.is_file() and not p.is_symlink() and p.stat().st_size == item["bytes"] and digest(p) == item["sha256"], "Release artifact SHA/bytes mismatch")
        checksum_lines.append(item["sha256"] + "  " + name + "\n")
        seen.add(name)
    checksum_lines.append(digest(path) + "  " + path.name + "\n")
    require((folder / (prefix + "-SHA256SUMS.txt")).read_text(encoding="utf-8") == "".join(checksum_lines), "Checksum file does not match release manifest")
    require({n for n, _ in regular_files(folder, public=True)} == seen, "Unlisted file in release directory")
    return [folder / name for name in sorted(seen)]


def create_tar(output, files, epoch):
    """Deterministic archive metadata; never traverse arbitrary workspace roots."""
    with Path(output).open("xb") as stream, gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0, compresslevel=6) as compressed, tarfile.open(fileobj=compressed, mode="w") as archive:
        seen = set()
        for name, p in sorted(files, key=lambda pair: pair[0]):
            safe_relative(name)
            require(name.casefold() not in seen and p.is_file() and not p.is_symlink(), "Unsafe/duplicate source archive file")
            seen.add(name.casefold())
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.uid, info.gid = p.stat().st_size, epoch, 0, 0
            info.mode = 0o755 if p.stat().st_mode & stat.S_IXUSR else 0o644
            with p.open("rb") as source:
                archive.addfile(info, source)


def create_source_zip(output, files, epoch):
    seen = set()
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for name, p in sorted(files, key=lambda pair: pair[0]):
            safe_relative(name)
            require(name.casefold() not in seen and p.is_file() and not p.is_symlink(), "Unsafe/duplicate source archive file")
            seen.add(name.casefold())
            info = zipfile.ZipInfo(name, time.gmtime(max(epoch, 315532800))[:6])
            info.create_system = 3
            info.external_attr = ((stat.S_IFREG | (0o755 if p.stat().st_mode & stat.S_IXUSR else 0o644)) << 16)
            info.compress_type = zipfile.ZIP_DEFLATED
            with archive.open(info, "w", force_zip64=True) as target, p.open("rb") as source:
                shutil.copyfileobj(source, target)


def make_source(args, lock):
    work, source, fonts, record = prepared(lock)
    vendor_files = []
    if args.vendor:
        vendor = work / "vendor"
        require(not vendor.exists(), "Vendored source already exists; inspect it before repeating")
        env = build_env(lock, fonts, ROOT / ".work/target/source", TARGETS["macos-arm64"])
        config = run(["rustup", "run", lock["rust"], "cargo", "vendor", "--locked", "--versioned-dirs", vendor], cwd=source, env=env, capture=True, timeout=1800)
        config = config.replace(str(vendor), "vendor").replace(str(vendor).replace("\\", "\\\\"), "vendor")
        require(str(ROOT) not in config and "[source.vendored-sources]" in config, "Cargo vendor config contains an unexpected local path")
        config_file = work / "kio-vendor.toml"
        config_file.write_text(config + "\n", encoding="utf-8")
        vendor_files = [("wordcraft/vendor/" + r, p) for r, p in regular_files(vendor)]
        vendor_files.append(("wordcraft/.cargo/kio-vendor.toml", config_file))
    source_readme = work / "SOURCE-README.txt"
    source_readme.write_text(
        "Full modified KIO Word project source and pinned fonts; Cargo.lock fixes third-party dependencies.\n"
        + ("All Cargo-vendored sources are also included; the optional offline config is .cargo/kio-vendor.toml.\n" if args.vendor else "Third-party Cargo source archives are fetched by Cargo using Cargo.lock; they are not duplicated in this ZIP.\n") +
        "Original engine and commands are retained. Read WordCraft ROADMAP/gaps for limitations.\n"
        "Install Rust 1.95.0 with the native target, then:\n"
        "  cd wordcraft\n"
        "  CRAFT_FONTS_DIR=../craft-fonts CRAFT_FONTS_REQUIRED=1 cargo +1.95.0 build --release --locked -p wordcraft -p wordcraft-cli\n"
        "PowerShell: set $env:CRAFT_FONTS_DIR to the absolute craft-fonts directory and $env:CRAFT_FONTS_REQUIRED='1' before that cargo command.\n"
        "Build orchestration and the exact KIO binary patch are in orchestrator/.\n"
        "Mac/Windows SDKs and Rust compiler are platform prerequisites, not bundled toolchains.\n", encoding="utf-8")
    files = [("wordcraft/" + r, p) for r, p in regular_files(source, public=True)]
    files += [("craft-fonts/" + r, p) for r, p in regular_files(fonts, public=True)]
    files += vendor_files
    files += [("SOURCE-README.txt", source_readme), ("BUILD-INPUTS.json", work / "prepared.json")]
    for selected in PUBLIC_FILES:
        path = ROOT / selected
        require(path.is_file() and not path.is_symlink(), "Missing reviewed public orchestrator file: " + selected)
        files.append(("orchestrator/" + selected, path))
    output = ROOT / "dist/word-source"
    require(not output.exists(), "Source release already exists; refuse to overwrite")
    output.mkdir(parents=True)
    create_source_zip(output / ("KIO-Word-" + lock["version"] + "-source.zip"), files, lock["sourceDateEpoch"])
    write_json(output / ("KIO-Word-" + lock["version"] + "-source-provenance.json"), {"schema": 1, "inputs": record, "vendored": args.vendor, "fileCount": len(files)})
    finalize_release(output, lock, "source")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "build", "package", "source", "verify", "publish-draft"))
    parser.add_argument("--app", default="word", choices=("word",))
    parser.add_argument("--platform", choices=tuple(TARGETS))
    parser.add_argument("--archive-cache", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--vendor", action="store_true", help="Also include all Cargo dependency sources; not needed by default for this MIT/Apache project")
    parser.add_argument("--existing-target", type=Path, help="Explicit caller-reviewed Mac implicit target/release directory; no rebuild or fabricated test claims")
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    if args.command == "verify":
        require(args.directory, "--directory is required")
        verify_release(args.directory)
        print("Exact release file list, bytes and SHA-256 verified.")
        return
    lock = load_lock(args.app)
    if args.command in ("build", "package"):
        require(args.platform, "--platform is required")
    if args.command == "prepare":
        prepare(args, lock)
    elif args.command == "build":
        build(args, lock)
    elif args.command == "package":
        package(args, lock)
    elif args.command == "source":
        make_source(args, lock)
    elif args.command == "publish-draft":
        require(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and os.environ.get("GITHUB_REF") == "refs/heads/main", "Publication is limited to manual dispatch on main")
        require(os.environ.get("KIO_PUBLISH_DRAFT") == "true" and args.directory, "Explicit manual publication flag and artifacts are required")
        files = []
        for kind in (*TARGETS, "source"):
            files += verify_release(args.directory / ("word-" + kind), lock, kind)
        notes = ROOT / "README.md"
        run(["gh", "release", "create", "word-v" + lock["version"], "--draft", "--target", os.environ["GITHUB_SHA"],
             "--title", "KIO Word " + lock["version"] + " full native development build", "--notes-file", notes, *files])


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print("Build stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
