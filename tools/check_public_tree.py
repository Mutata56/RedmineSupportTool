#!/usr/bin/env python3
"""Check publication paths and infrastructure identifiers without printing values."""
from __future__ import annotations

import argparse
import ipaddress
import pathlib
import re
import struct
import subprocess
import sys
import zlib

BLOCKED_PARTS = {".git", ".claude", ".codex", ".agents", ".venv", "venv", "__pycache__", ".pytest_cache", "state", "logs", "attachments", "backups", "outputs"}
PUBLIC_CONFIGS = {"README.md", "config.example.json", "secrets.example.json", "shift_schedule.example.json", "grafana_sets.example.yml", "table_analysis.example.json"}
PUBLIC_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "rm", "api.anthropic.com", "api.telegram.org", "ntfy.sh", "www.w3.org", "github.com"}
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
EMAIL = re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL = re.compile(r"https?://([^\s/\"'<>?#)]+)")
PERSONAL_PATH = re.compile(r"/(?:Users|home)/[^\s/\"']+")
PUBLIC_SCREENSHOTS = {f"documentation/screenshots/{name}.png" for name in ("overview", "emails", "tickets", "approvals", "chat")}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def check_screenshot(relative, data):
    """Allow only reviewed screenshots, with no metadata or trailing payload.

    Pixel contents still require visual review before publication.
    """
    if relative not in PUBLIC_SCREENSHOTS:
        return ["unexpected_binary_file"]
    if not data.startswith(PNG_SIGNATURE):
        return ["invalid_screenshot_png"]
    offset = len(PNG_SIGNATURE)
    chunks = []
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + length
        if end > len(data):
            return ["invalid_screenshot_png"]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        checksum = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if zlib.crc32(kind + payload) != checksum:
            return ["invalid_screenshot_png"]
        if kind not in {b"IHDR", b"IDAT", b"IEND"}:
            return ["unexpected_png_metadata"]
        chunks.append(kind)
        if kind == b"IHDR" and (len(chunks) != 1 or length != 13):
            return ["invalid_screenshot_png"]
        offset = end
        if kind == b"IEND":
            if length or offset != len(data):
                return ["invalid_screenshot_png"]
            break
    if not chunks or chunks[0] != b"IHDR" or chunks[-1] != b"IEND" or b"IDAT" not in chunks:
        return ["invalid_screenshot_png"]
    return []


def allowed_host(host):
    host = host.split(":", 1)[0].lower()
    return host in PUBLIC_HOSTS or host.endswith((".example.invalid", ".invalid", ".test", ".localhost")) or host in {"example.com", "example.invalid"}


def check_path(relative):
    path = pathlib.PurePosixPath(relative)
    if any(part in BLOCKED_PARTS for part in path.parts):
        return "private_runtime_path"
    if path.parts and path.parts[0] == "config" and (len(path.parts) != 2 or path.name not in PUBLIC_CONFIGS):
        return "private_config_path"
    if path.name in {"AGENTS.md", "CLAUDE_SESSIONS.md"} or path.name.startswith(".env") or path.suffix in {".key", ".pem", ".p12", ".pfx", ".token", ".log", ".jsonl", ".bak", ".old"}:
        return "private_file_type"
    return None


def check_text(text):
    findings = set()
    if PERSONAL_PATH.search(text):
        findings.add("personal_absolute_path")
    for value in IPV4.findall(text):
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        documentation = any(address in ipaddress.ip_network(block) for block in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"))
        if not documentation and not address.is_loopback and not address.is_unspecified:
            findings.add("non_example_ip")
    for value in EMAIL.findall(text):
        if value.rsplit("@", 1)[1] not in {"example.invalid", "example.com", "users.noreply.github.com"}:
            findings.add("non_example_email")
    for host in URL.findall(text):
        if not allowed_host(host):
            findings.add("non_public_service_host")
    return sorted(findings)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1])
    parser.add_argument("--staged", action="store_true", help="Read publication content directly from the Git index")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.staged:
        paths = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"]).decode().split("\0")
    elif (root / ".git").exists():
        paths = subprocess.check_output(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]).decode().split("\0")
    else:
        paths = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and not any(part in BLOCKED_PARTS for part in p.relative_to(root).parts)]
    errors = []
    count = 0
    for relative in filter(None, paths):
        count += 1
        finding = check_path(relative)
        if finding:
            errors.append((relative, finding))
            continue
        data = subprocess.check_output(["git", "-C", str(root), "show", ":" + relative]) if args.staged else (root / relative).read_bytes()
        if "vendor" in pathlib.PurePosixPath(relative).parts:
            continue
        if relative in PUBLIC_SCREENSHOTS:
            errors.extend((relative, category) for category in check_screenshot(relative, data))
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            errors.append((relative, "unexpected_binary_file"))
            continue
        errors.extend((relative, category) for category in check_text(text))
    for path, category in errors:
        print(f"{path}: {category}")
    print(f"Checked {count} files; {len(errors)} findings. Values are never printed.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
