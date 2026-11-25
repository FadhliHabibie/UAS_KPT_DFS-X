"""DFS-X: eksperimen upload/download 100 file (total 50 MB) + sapuan konfigurasi.

Dipakai untuk Bab Hasil laporan (rencana 28-29 Nov 2026), dibuat lebih awal
20 Nov 2026 supaya tinggal dijalankan di laptop setelah Docker dites.

Yang diukur per file: latensi upload, latensi download, throughput
(MB/detik), dan verifikasi hash SHA-256 hasil download vs file asli.

Cara pakai (dari folder dfs-x/, master + 3 data node sudah jalan):
  # Eksperimen utama sesuai soal: 100 file x 512 KB = 50 MB, replikasi 2x,
  # chunk 1 MB (default):
  python experiments/run_experiments.py --out-dir experiments/results

  # Tes cepat (5 file kecil) sebelum eksperimen penuh:
  python experiments/run_experiments.py --n 5 --size-kb 128 --chunk-kb 256 --out-dir /tmp/dfsx-smoke

  # Sapuan replikasi 1x/2x/3x x chunk 256 KB/1 MB/4 MB (9 konfigurasi,
  # lama — jalankan sekali saja, tiap konfigurasi menghapus filenya lagi):
  python experiments/run_experiments.py --sweep --out-dir experiments/results

Hasil per konfigurasi: results_<rep>x_<chunk>kb.csv (satu baris per file)
+ summary.json (rata-rata/median/total). Grafik dibuat terpisah dengan
make_graphs.py. File uji dibuat deterministik (seed tetap) dari folder
--work-dir dan dihapus dari DFS-X setelah tiap konfigurasi (kecuali --keep),
supaya konfigurasi berikutnya mulai dari keadaan bersih.
"""

import argparse
import csv
import hashlib
import json
import os
import statistics
import sys
import tempfile
import time

import requests

MASTER_URL = os.environ.get("DFSX_MASTER_URL", "http://localhost:5000").rstrip("/")


def deterministic_bytes(size: int, seed: int) -> bytes:
    """Byte deterministik: blok SHA-256(seed:counter) diulang sampai size."""
    out = bytearray()
    counter = 0
    while len(out) < size:
        out += hashlib.sha256(f"dfsx-{seed}:{counter}".encode()).digest()
        counter += 1
    return bytes(out[:size])


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def upload_file(master: str, path: str, chunk_kb: int, replication: int) -> float:
    """Upload satu file lewat API master/data node (alur sama dengan client).
    Mengembalikan latensi upload dalam detik."""
    filename = os.path.basename(path)
    size = os.path.getsize(path)
    chunk_size = chunk_kb * 1024
    t0 = time.time()
    plan = requests.post(
        master + "/plan",
        json={"filename": filename, "size": size,
              "chunk_size": chunk_size, "replication": replication},
        timeout=30,
    )
    plan.raise_for_status()
    plan = plan.json()
    with open(path, "rb") as f:
        for ch in plan["chunks"]:
            data = f.read(chunk_size)
            for url in ch["urls"]:
                r = requests.put(url + "/chunk/" + ch["id"], data=data, timeout=60)
                r.raise_for_status()
    commit = requests.post(master + "/commit", json=plan, timeout=30)
    commit.raise_for_status()
    return time.time() - t0


def download_file(master: str, filename: str) -> tuple[float, bytes]:
    """Download satu file, rakit dari chunk pertama yang hidup per chunk.
    Mengembalikan (latensi detik, isi file)."""
    t0 = time.time()
    meta = requests.get(master + "/files/" + filename, timeout=30)
    meta.raise_for_status()
    meta = meta.json()
    parts = []
    for ch in meta["chunks"]:
        data = None
        for url in ch["urls"]:
            try:
                r = requests.get(url + "/chunk/" + ch["id"], timeout=60)
                if r.status_code == 200:
                    data = r.content
                    break
            except requests.RequestException:
                continue
        if data is None:
            raise RuntimeError(f"chunk {ch['id']} tidak bisa diambil")
        parts.append(data)
    return time.time() - t0, b"".join(parts)


def delete_file(master: str, filename: str) -> None:
    try:
        requests.delete(master + "/files/" + filename, timeout=10)
    except requests.RequestException:
        pass


def run_config(master: str, work_dir: str, out_dir: str, n: int, size_kb: int,
               chunk_kb: int, replication: int, keep: bool) -> dict:
    """Jalankan satu konfigurasi penuh, tulis CSV + ringkasan, kembalikan summary."""
    size = size_kb * 1024
    tag = f"{replication}x_{chunk_kb}kb"
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, f"results_{tag}.csv")
    rows = []
    total_bytes = 0
    for i in range(1, n + 1):
        filename = f"dfsx-exp-{tag}-f{i:03d}.bin"
        path = os.path.join(work_dir, filename)
        data = deterministic_bytes(size, seed=i)
        with open(path, "wb") as f:
            f.write(data)
        expected = sha256_bytes(data)
        try:
            t_up = upload_file(master, path, chunk_kb, replication)
            t_down, got = download_file(master, filename)
            ok = sha256_bytes(got) == expected
        finally:
            if not keep:
                delete_file(master, filename)
            try:
                os.remove(path)
            except OSError:
                pass
        if not ok:
            raise RuntimeError(f"hash download tidak cocok: {filename}")
        rows.append({
            "config": tag, "file": filename, "size_bytes": size,
            "upload_s": round(t_up, 4), "download_s": round(t_down, 4),
            "upload_MBps": round(size / t_up / 1024 / 1024, 3),
            "download_MBps": round(size / t_down / 1024 / 1024, 3),
            "hash_ok": ok,
        })
        total_bytes += size
        print(f"  [{tag}] {i}/{n} {filename}: up {t_up:.3f} dtk, "
              f"down {t_down:.3f} dtk, hash OK", flush=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    up = [r["upload_s"] for r in rows]
    down = [r["download_s"] for r in rows]
    summary = {
        "config": tag, "replication": replication, "chunk_kb": chunk_kb,
        "n_files": n, "size_kb_per_file": size_kb,
        "total_MB": round(total_bytes / 1024 / 1024, 2),
        "upload_latency_mean_s": round(statistics.mean(up), 4),
        "upload_latency_median_s": round(statistics.median(up), 4),
        "download_latency_mean_s": round(statistics.mean(down), 4),
        "download_latency_median_s": round(statistics.median(down), 4),
        "upload_throughput_mean_MBps": round(statistics.mean([r["upload_MBps"] for r in rows]), 3),
        "download_throughput_mean_MBps": round(statistics.mean([r["download_MBps"] for r in rows]), 3),
        "upload_total_s": round(sum(up), 3),
        "download_total_s": round(sum(down), 3),
        "hash_all_ok": all(r["hash_ok"] for r in rows),
        "csv": os.path.basename(csv_path),
    }
    print(f"[{tag}] SELESAI: {n} file, {summary['total_MB']} MB, "
          f"upload {summary['upload_throughput_mean_MBps']} MB/detik, "
          f"download {summary['download_throughput_mean_MBps']} MB/detik, "
          f"latensi upload rata-rata {summary['upload_latency_mean_s']} dtk, "
          f"latensi download rata-rata {summary['download_latency_mean_s']} dtk")
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description="Eksperimen DFS-X: 100 file, throughput + latensi")
    p.add_argument("--master", default=MASTER_URL)
    p.add_argument("--n", type=int, default=100, help="jumlah file (default 100)")
    p.add_argument("--size-kb", type=int, default=512, help="ukuran tiap file KB (default 512 -> total 50 MB)")
    p.add_argument("--chunk-kb", type=int, default=1024, help="ukuran chunk KB (default 1024)")
    p.add_argument("--replication", type=int, default=2, help="faktor replikasi (default 2)")
    p.add_argument("--sweep", action="store_true",
                   help="sapuan replikasi 1x/2x/3x x chunk 256 KB/1 MB/4 MB")
    p.add_argument("--out-dir", default="experiments/results")
    p.add_argument("--work-dir", default=None, help="folder file uji sementara (default: temp)")
    p.add_argument("--keep", action="store_true", help="jangan hapus file dari DFS-X setelah uji")
    args = p.parse_args()

    try:
        st = requests.get(args.master + "/status", timeout=10)
        st.raise_for_status()
    except requests.RequestException as e:
        print(f"tidak bisa terhubung ke master {args.master}: {e}")
        print("Pastikan master + 3 data node jalan (docker compose up / mode tanpa Docker di README).")
        return 1

    configs = ([(r, c) for r in (1, 2, 3) for c in (256, 1024, 4096)]
               if args.sweep else [(args.replication, args.chunk_kb)])
    work_dir = args.work_dir or tempfile.mkdtemp(prefix="dfsx-exp-")
    os.makedirs(work_dir, exist_ok=True)
    summaries = []
    for replication, chunk_kb in configs:
        summaries.append(run_config(args.master, work_dir, args.out_dir,
                                    args.n, args.size_kb, chunk_kb,
                                    replication, args.keep))
    with open(os.path.join(args.out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"master": args.master, "configs": summaries}, f, indent=2)
    print(f"\nRingkasan tersimpan: {os.path.join(args.out_dir, 'summary.json')}")
    print("Grafik: python experiments/make_graphs.py --results-dir "
          f"{args.out_dir} --out-dir {args.out_dir}/grafik")
    return 0


if __name__ == "__main__":
    sys.exit(main())
