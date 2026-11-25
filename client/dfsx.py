"""DFS-X client terminal.

Pakai:
  python dfsx.py upload <file> [--chunk-kb 1024] [--replication 2]
  python dfsx.py download <nama-file> [-o <output>]
  python dfsx.py list
  python dfsx.py delete <nama-file>
  python dfsx.py status

Env: DFSX_MASTER_URL (default: http://localhost:5000)

Alur upload: minta /plan ke master -> PUT tiap chunk LANGSUNG ke data node
yang ditunjuk -> POST /commit ke master. Alur download: minta peta chunk
ke master (GET /files/<nama>) -> GET tiap chunk langsung dari data node
pertama yang masih hidup -> rakit ulang sesuai urutan indeks.
"""

import argparse
import hashlib
import os
import sys
import time

import requests

MASTER_URL = os.environ.get("DFSX_MASTER_URL", "http://localhost:5000").rstrip("/")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def cmd_upload(args) -> int:
    path = args.file
    if not os.path.isfile(path):
        print(f"file tidak ditemukan: {path}")
        return 1
    filename = os.path.basename(path)
    size = os.path.getsize(path)
    chunk_size = args.chunk_kb * 1024
    t0 = time.time()
    plan = requests.post(
        MASTER_URL + "/plan",
        json={
            "filename": filename,
            "size": size,
            "chunk_size": chunk_size,
            "replication": args.replication,
        },
        timeout=10,
    )
    plan.raise_for_status()
    plan = plan.json()
    with open(path, "rb") as f:
        for ch in plan["chunks"]:
            data = f.read(chunk_size)
            for url in ch["urls"]:
                r = requests.put(url + "/chunk/" + ch["id"], data=data, timeout=30)
                r.raise_for_status()
    commit = requests.post(MASTER_URL + "/commit", json=plan, timeout=10)
    commit.raise_for_status()
    dt = time.time() - t0
    print(
        f"upload OK: {filename} ({size} byte, {len(plan['chunks'])} chunk, "
        f"replikasi {args.replication}x) dalam {dt:.2f} dtk "
        f"-> throughput {size / dt / 1024 / 1024:.2f} MB/detik"
    )
    return 0


def cmd_download(args) -> int:
    out = args.output or args.filename
    t0 = time.time()
    meta = requests.get(MASTER_URL + "/files/" + args.filename, timeout=10)
    if meta.status_code == 404:
        print(f"file tidak ditemukan di master: {args.filename}")
        return 1
    meta.raise_for_status()
    meta = meta.json()
    with open(out, "wb") as f:
        for ch in meta["chunks"]:
            data = None
            for url in ch["urls"]:
                try:
                    r = requests.get(url + "/chunk/" + ch["id"], timeout=30)
                    if r.status_code == 200:
                        data = r.content
                        break
                except requests.RequestException:
                    continue
            if data is None:
                print(f"GAGAL: chunk {ch['id']} tidak bisa diambil (semua replika mati?)")
                return 1
            f.write(data)
    dt = time.time() - t0
    size = os.path.getsize(out)
    print(
        f"download OK: {out} ({size} byte) dalam {dt:.2f} dtk "
        f"-> throughput {size / dt / 1024 / 1024:.2f} MB/detik"
    )
    return 0


def cmd_list(_args) -> int:
    files = requests.get(MASTER_URL + "/files", timeout=10).json()
    if not files:
        print("(belum ada file)")
        return 0
    for f in files:
        print(f"{f['filename']}\t{f['size']} byte\t{f['chunks']} chunk")
    return 0


def cmd_delete(args) -> int:
    r = requests.delete(MASTER_URL + "/files/" + args.filename, timeout=10)
    if r.status_code == 404:
        print(f"file tidak ditemukan: {args.filename}")
        return 1
    r.raise_for_status()
    print(f"hapus OK: {args.filename}")
    return 0


def cmd_status(_args) -> int:
    st = requests.get(MASTER_URL + "/status", timeout=10).json()
    print(f"master: {st['master']} | file tersimpan: {st['files']}")
    for n in st["nodes"]:
        state = "HIDUP" if n["alive"] else "MATI"
        print(f"  {n['name']} ({n['url']}): {state}, {n['chunks']} chunk")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="dfsx", description="DFS-X client terminal")
    sub = p.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("upload", help="upload file ke DFS-X")
    up.add_argument("file")
    up.add_argument("--chunk-kb", type=int, default=1024, help="ukuran chunk KB (default 1024)")
    up.add_argument("--replication", type=int, default=2, help="faktor replikasi (default 2)")
    up.set_defaults(func=cmd_upload)

    dl = sub.add_parser("download", help="download file dari DFS-X")
    dl.add_argument("filename")
    dl.add_argument("-o", "--output", default=None)
    dl.set_defaults(func=cmd_download)

    ls = sub.add_parser("list", help="daftar file")
    ls.set_defaults(func=cmd_list)

    rm = sub.add_parser("delete", help="hapus file")
    rm.add_argument("filename")
    rm.set_defaults(func=cmd_delete)

    st = sub.add_parser("status", help="heartbeat master + data node")
    st.set_defaults(func=cmd_status)

    args = p.parse_args()
    try:
        return args.func(args)
    except requests.ConnectionError:
        print(f"tidak bisa terhubung ke master {MASTER_URL} — pastikan master jalan.")
        return 1
    except requests.HTTPError as e:
        print(f"HTTP error: {e} — {e.response.text[:300]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
