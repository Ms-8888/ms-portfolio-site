"""Deploy the static site over SFTP. Never deletes anything on the server.

Credentials are read from a file outside every repository and are never printed:
    C:\\Users\\moosh\\.secrets\\Combell.env      (override with --env)
    SSH-HOST=...  SSH-USERNAME=...  SSH-PASSWORD=...  [SSH-PORT=22]  [REMOTE-ROOT=/www]

Commands (run with the project's venv: .venv\\Scripts\\python scripts\\deploy.py <command>):
    plan                  offline: list what would be uploaded, check for files that must not go online
    list [remote_dir]     read-only: names in a remote directory (to find the web root)
    backup [remote_dir]   read-only: download a remote folder (default <root>/project2) into backup/
    deploy                dry run: show what would be uploaded where (no upload)
    deploy --yes          upload every file in site/ to the root, then compare sizes
    htaccess --yes        upload extras/htaccess.txt as <root>/.htaccess, re-check the live pages and remove the
                          file again if any page stops answering
    remove-old --yes      delete <root>/project2 ONLY (the retired old site), after checking that its file
                          count equals the newest local backup/remote-project2-* folder

First connection to a server stops after printing its host key fingerprint; run again with
--trust-new-host to remember it. A changed fingerprint later always stops the script.
"""

import argparse
import hashlib
import base64
import posixpath
import stat
import sys
import time
from pathlib import Path

import paramiko

PROJECT = Path(__file__).resolve().parent.parent
SITE = PROJECT / "site"
DEFAULT_ENV = Path.home() / ".secrets" / "Combell.env"
KNOWN_HOST_FILE = Path.home() / ".secrets" / "combell_hostkey.txt"
FORBIDDEN_NAMES = (".env", ".git", ".secrets", ".venv", "node_modules", "Thumbs.db", ".DS_Store")
FORBIDDEN_SUFFIXES = (".env", ".pem", ".key", ".bak", ".py", ".log")


def read_env(path: Path) -> dict:
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip().upper()] = value.strip().strip("\"'")
    return values


def local_files() -> list[Path]:
    files = sorted(p for p in SITE.rglob("*") if p.is_file())
    problems = [
        p for p in files
        if any(part in FORBIDDEN_NAMES for part in p.relative_to(SITE).parts) or p.suffix.lower() in FORBIDDEN_SUFFIXES
    ]
    if problems:
        sys.exit("refusing: files that must not go online: " + ", ".join(str(p.relative_to(SITE)) for p in problems))
    return files


def connect(args) -> paramiko.SFTPClient:
    env = read_env(Path(args.env))
    missing = [k for k in ("SSH-HOST", "SSH-USERNAME", "SSH-PASSWORD") if not env.get(k)]
    if missing:
        sys.exit("missing in the env file: " + ", ".join(missing))
    port = int(env.get("SSH-PORT") or 22)
    transport = paramiko.Transport((env["SSH-HOST"], port))
    transport.banner_timeout = 20
    transport.start_client(timeout=20)
    key = transport.get_remote_server_key()
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
    known = KNOWN_HOST_FILE.read_text().strip() if KNOWN_HOST_FILE.exists() else ""
    if known and known != fingerprint:
        transport.close()
        sys.exit("STOP: the server's host key changed. Do not continue until you know why.")
    if not known:
        print(f"server host key ({key.get_name()}): {fingerprint}")
        if not args.trust_new_host:
            transport.close()
            sys.exit("first connection: compare the fingerprint if Combell shows one, then run again with --trust-new-host")
        KNOWN_HOST_FILE.write_text(fingerprint)
        print("host key remembered")
    transport.auth_password(env["SSH-USERNAME"], env["SSH-PASSWORD"])
    print("connected (credentials not shown)")
    sftp = paramiko.SFTPClient.from_transport(transport)
    sftp.root = env.get("REMOTE-ROOT", "")
    return sftp


def remote_root(args, sftp) -> str:
    root = args.root or sftp.root
    if not root:
        sys.exit("no remote web root known: run 'list' to find it, then add REMOTE-ROOT=<path> to the env file or pass --root")
    return root.rstrip("/") or "/"


def cmd_plan(args):
    files = local_files()
    total = sum(p.stat().st_size for p in files)
    for p in files:
        print(f"  {p.stat().st_size:>8}  {p.relative_to(SITE).as_posix()}")
    print(f"{len(files)} files, {total / 1024:.0f} KB; no forbidden files found")


def cmd_list(args):
    sftp = connect(args)
    target = args.path or sftp.root or "."
    for entry in sorted(sftp.listdir_attr(target), key=lambda e: e.filename):
        kind = "dir " if stat.S_ISDIR(entry.st_mode) else "file"
        print(f"  {kind} {entry.filename}")


def download_tree(sftp, remote: str, local: Path, counter: dict):
    local.mkdir(parents=True, exist_ok=True)
    for entry in sftp.listdir_attr(remote):
        r = posixpath.join(remote, entry.filename)
        l = local / entry.filename
        if stat.S_ISDIR(entry.st_mode):
            download_tree(sftp, r, l, counter)
        else:
            sftp.get(r, str(l))
            counter["files"] += 1
            counter["bytes"] += entry.st_size


def cmd_backup(args):
    sftp = connect(args)
    source = args.path or posixpath.join(remote_root(args, sftp), "project2")
    target = PROJECT / "backup" / f"remote-{posixpath.basename(source)}-{time.strftime('%Y%m%d-%H%M%S')}"
    counter = {"files": 0, "bytes": 0}
    download_tree(sftp, source, target, counter)
    print(f"downloaded {counter['files']} files, {counter['bytes'] / 1024:.0f} KB into {target.relative_to(PROJECT)}")


def ensure_dir(sftp, path: str):
    parts, current = path.strip("/").split("/"), "/" if path.startswith("/") else ""
    for part in parts:
        current = posixpath.join(current, part) if current else part
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)


def cmd_deploy(args):
    files = local_files()
    sftp = connect(args)
    root = remote_root(args, sftp)
    print(f"target root: {root}")
    if not args.yes:
        for p in files:
            print(f"  would upload {p.relative_to(SITE).as_posix()}")
        print(f"dry run: {len(files)} files would go to {root}. Nothing was changed. Add --yes to upload.")
        return
    ensure_dir(sftp, root)
    for p in files:
        rel = p.relative_to(SITE).as_posix()
        remote = posixpath.join(root, rel)
        ensure_dir(sftp, posixpath.dirname(remote))
        sftp.put(str(p), remote)
    wrong = [p.relative_to(SITE).as_posix() for p in files if sftp.stat(posixpath.join(root, p.relative_to(SITE).as_posix())).st_size != p.stat().st_size]
    print(f"uploaded {len(files)} files; size mismatches: {wrong or 'none'}")
    if wrong:
        sys.exit(1)


def count_remote(sftp, remote: str) -> int:
    total = 0
    for entry in sftp.listdir_attr(remote):
        if stat.S_ISLNK(entry.st_mode):
            sys.exit("STOP: symbolic link found inside the folder; not deleting")
        total += count_remote(sftp, posixpath.join(remote, entry.filename)) if stat.S_ISDIR(entry.st_mode) else 1
    return total


def remove_tree(sftp, remote: str):
    for entry in sftp.listdir_attr(remote):
        path = posixpath.join(remote, entry.filename)
        remove_tree(sftp, path) if stat.S_ISDIR(entry.st_mode) else sftp.remove(path)
    sftp.rmdir(remote)


def cmd_remove_old(args):
    backups = sorted((PROJECT / "backup").glob("remote-project2-*"))
    if not backups:
        sys.exit("no local backup of project2 found; run 'backup' first")
    local_count = sum(1 for p in backups[-1].rglob("*") if p.is_file())
    sftp = connect(args)
    target = posixpath.join(remote_root(args, sftp), "project2")
    remote_count = count_remote(sftp, target)
    print(f"server: {remote_count} files in {target}; local backup {backups[-1].name}: {local_count} files")
    if remote_count != local_count:
        sys.exit("STOP: counts differ, the backup does not match the server")
    if not args.yes:
        print("dry run: nothing deleted. Add --yes to delete the folder.")
        return
    remove_tree(sftp, target)
    print("deleted", target)


LIVE = "https://msportfolio.be"
CHECK_PATHS = ["/", "/en/", "/projecten/", "/en/projects/", "/cv/", "/contact/", "/css/style.css", "/img/og-image-v2.jpg"]


def live_ok() -> list[str]:
    import urllib.request, urllib.error
    bad = []
    for path in CHECK_PATHS:
        try:
            with urllib.request.urlopen(urllib.request.Request(LIVE + path, headers={"User-Agent": "site-check/1.0"}), timeout=25) as r:
                if r.status != 200:
                    bad.append(f"{path}: {r.status}")
        except urllib.error.HTTPError as e:
            bad.append(f"{path}: {e.code}")
        except Exception as e:
            bad.append(f"{path}: {type(e).__name__}")
    return bad


def cmd_htaccess(args):
    source = PROJECT / "extras" / "htaccess.txt"
    sftp = connect(args)
    target = posixpath.join(remote_root(args, sftp), ".htaccess")
    try:
        sftp.stat(target)
        sys.exit("STOP: a .htaccess already exists on the server; not overwriting it")
    except FileNotFoundError:
        pass
    if not args.yes:
        print(f"dry run: would upload {source.name} as {target}. Add --yes to upload.")
        return
    sftp.put(str(source), target)
    time.sleep(3)
    bad = live_ok()
    if bad:
        sftp.remove(target)
        sys.exit("ROLLED BACK (.htaccess removed), problems: " + "; ".join(bad))
    print("uploaded .htaccess; all checked pages still answer 200")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["plan", "list", "backup", "deploy", "remove-old", "htaccess"])
    parser.add_argument("path", nargs="?")
    parser.add_argument("--env", default=str(DEFAULT_ENV))
    parser.add_argument("--root")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--trust-new-host", action="store_true")
    args = parser.parse_args()
    {"plan": cmd_plan, "list": cmd_list, "backup": cmd_backup, "deploy": cmd_deploy, "remove-old": cmd_remove_old, "htaccess": cmd_htaccess}[args.command](args)


if __name__ == "__main__":
    main()
