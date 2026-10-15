import hashlib
import importlib.util
import io
import json
import struct
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/kio_native.py"
spec = importlib.util.spec_from_file_location("builder", SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class NativeBuildGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def archive(self, entries):
        path = self.root / "source.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, kind, value in entries:
                info = tarfile.TarInfo(name)
                if kind == "file":
                    data = value.encode()
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
                elif kind == "directory":
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                else:
                    info.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
                    info.linkname = value
                    archive.addfile(info)
        return path

    def test_full_source_extract_keeps_engine_and_workspace(self):
        source = self.archive([("root/Cargo.toml", "file", "workspace"), ("root/crates/engine/src/lib.rs", "file", "engine")])
        output = self.root / "out"
        builder.safe_extract(source, output, "root")
        self.assertEqual((output / "Cargo.toml").read_text(), "workspace")
        self.assertEqual((output / "crates/engine/src/lib.rs").read_text(), "engine")

    def test_traversal_is_rejected_before_any_file_is_written(self):
        source = self.archive([("root/valid", "file", "ok"), ("root/../../escaped", "file", "bad")])
        output = self.root / "out"
        with self.assertRaises(ValueError):
            builder.safe_extract(source, output, "root")
        self.assertFalse(output.exists())
        self.assertFalse((self.root / "escaped").exists())

    def test_archive_links_are_never_followed(self):
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind):
                source = self.archive([("root/link", kind, "/etc/passwd")])
                with self.assertRaises(ValueError):
                    builder.safe_extract(source, self.root / kind, "root")

    def test_case_collision_and_duplicates_are_rejected_for_windows(self):
        for names in (("root/Foo", "root/foo"), ("root/file", "root/file")):
            with self.subTest(names=names):
                source = self.archive([(n, "file", "x") for n in names])
                with self.assertRaises(ValueError):
                    builder.safe_extract(source, self.root / "out", "root")

    def test_wrong_archive_root_private_files_and_expansion_are_rejected(self):
        for name in ("other/file", "root/.env", "root/.ssh/key", "root/CON", "root/C:drive"):
            with self.subTest(name=name):
                source = self.archive([(name, "file", "secret")])
                with self.assertRaises(ValueError):
                    builder.safe_extract(source, self.root / "out", "root")
        source = self.archive([("root/file", "file", "012345")])
        with self.assertRaises(ValueError):
            builder.safe_extract(source, self.root / "out", "root", max_bytes=5)

    def test_pinned_cache_refuses_tampering_even_offline(self):
        cache = self.root / "cache"
        cache.mkdir()
        path = cache / "fixed.tar.gz"
        path.write_bytes(b"expected")
        entry = {"root": "fixed", "bytes": 8, "sha256": hashlib.sha256(b"expected").hexdigest()}
        self.assertEqual(builder.verified_archive(entry, cache, True), path)
        path.write_bytes(b"modified")
        with self.assertRaises(ValueError):
            builder.verified_archive(entry, cache, True)

    def test_source_lock_and_patch_are_immutable_and_full_native(self):
        lock = builder.load_lock()
        self.assertEqual(lock["cargoPackages"], ["wordcraft", "wordcraft-cli"])
        self.assertEqual(builder.digest(builder.ROOT / lock["branding"]["patch"]), lock["branding"]["sha256"])
        fake = self.root / "project"
        (fake / "manifests").mkdir(parents=True)
        lock["fonts"]["url"] = "https://attacker.invalid/source"
        (fake / "manifests/word.lock.json").write_text(json.dumps(lock))
        with patch.object(builder, "ROOT", fake), self.assertRaises(ValueError):
            builder.load_lock()

    def test_fingerprint_detects_source_mutation(self):
        source = self.root / "source"
        source.mkdir()
        (source / "engine.rs").write_text("original")
        before = builder.tree_fingerprint(source)
        (source / "engine.rs").write_text("modified")
        self.assertNotEqual(before, builder.tree_fingerprint(source))

    def test_macho_requires_arm64_native_executable(self):
        binary = self.root / "app"
        header = bytearray(64)
        header[:4] = b"\xcf\xfa\xed\xfe"
        struct.pack_into("<I", header, 4, 0x0100000C)
        struct.pack_into("<I", header, 12, 2)
        binary.write_bytes(header)
        builder.native_header(binary, "aarch64-apple-darwin", True)
        struct.pack_into("<I", header, 4, 0x01000007)
        binary.write_bytes(header)
        with self.assertRaises(ValueError):
            builder.native_header(binary, "aarch64-apple-darwin", True)
        binary.write_bytes(b"\0asm" + bytes(64))
        with self.assertRaises(ValueError):
            builder.native_header(binary, "aarch64-apple-darwin", True)

    def test_windows_checks_architecture_and_separate_gui_cli_subsystems(self):
        binary = self.root / "app.exe"
        header = bytearray(256)
        header[:2] = b"MZ"
        struct.pack_into("<I", header, 0x3C, 64)
        header[64:68] = b"PE\0\0"
        struct.pack_into("<H", header, 68, 0x8664)
        struct.pack_into("<H", header, 88, 0x20B)
        struct.pack_into("<H", header, 64 + 0x5C, 2)
        binary.write_bytes(header)
        builder.native_header(binary, "x86_64-pc-windows-msvc", True)
        with self.assertRaises(ValueError):
            builder.native_header(binary, "x86_64-pc-windows-msvc", False)
        struct.pack_into("<H", header, 68, 0xAA64)
        binary.write_bytes(header)
        with self.assertRaises(ValueError):
            builder.native_header(binary, "x86_64-pc-windows-msvc", True)

    def release(self):
        output = self.root / "release"
        output.mkdir()
        lock = builder.load_lock()
        base = "KIO-Word-" + lock["version"] + "-windows-x64"
        (output / (base + ".zip")).write_bytes(b"binary fixture")
        (output / (base + "-provenance.json")).write_text("{}")
        builder.finalize_release(output, lock, "windows-x64")
        return output, lock

    def test_release_exact_hashes_and_matching_input_lock(self):
        output, lock = self.release()
        self.assertEqual(len(builder.verify_release(output, lock, "windows-x64")), 4)
        lock["branding"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            builder.verify_release(output, lock)

    def test_release_rejects_unlisted_private_file_and_modified_artifact(self):
        output, _ = self.release()
        private = output / "private.txt"
        private.write_text("not an artifact")
        with self.assertRaises(ValueError):
            builder.verify_release(output)
        private.unlink()
        next(output.glob("*.zip")).write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            builder.verify_release(output)

    def test_source_zip_is_deterministic_retains_sources_and_refuses_links(self):
        source = self.root / "engine.rs"
        source.write_text("full engine")
        files = [("wordcraft/crates/engine/src/lib.rs", source)]
        first, second = self.root / "one.zip", self.root / "two.zip"
        builder.create_source_zip(first, files, 1791983245)
        builder.create_source_zip(second, files, 1791983245)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(archive.read(files[0][0]), b"full engine")
        if hasattr(Path, "symlink_to"):
            link = self.root / "link"
            try:
                link.symlink_to(source)
            except OSError:
                return  # Windows runners can forbid unprivileged symlink creation.
            with self.assertRaises(ValueError):
                builder.create_source_zip(self.root / "unsafe.zip", [("wordcraft/link", link)], 1791983245)

    def test_source_allowlist_has_no_private_or_build_roots(self):
        for name in builder.PUBLIC_FILES:
            builder.check_public_path(name)
            self.assertFalse(name.startswith((".work/", ".cache/", "dist/")))
            self.assertTrue((builder.ROOT / name).is_file())


if __name__ == "__main__":
    unittest.main()
