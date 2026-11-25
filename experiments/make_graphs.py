"""DFS-X: grafik hasil eksperimen dari CSV run_experiments.py.

Baca semua results_*.csv di --results-dir, agregasi per konfigurasi,
lalu simpan PNG:
  throughput_vs_replikasi.png   (chunk 1 MB; upload vs download)
  latensi_vs_chunk.png          (replikasi 2x; upload vs download)
  throughput_per_config.png     (semua konfigurasi, upload vs download)

Pakai: python experiments/make_graphs.py --results-dir experiments/results
       --out-dir experiments/results/grafik
"""

import argparse
import glob
import os
import re
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402


def load(results_dir: str) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(results_dir, "results_*.csv")))
    if not files:
        print(f"tidak ada results_*.csv di {results_dir}")
        sys.exit(1)
    frames = []
    for path in files:
        df = pd.read_csv(path)
        m = re.search(r"results_(\d+)x_(\d+)kb\.csv", os.path.basename(path))
        if m:
            df["replication"] = int(m.group(1))
            df["chunk_kb"] = int(m.group(2))
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def main() -> int:
    p = argparse.ArgumentParser(description="Grafik hasil eksperimen DFS-X")
    p.add_argument("--results-dir", required=True)
    p.add_argument("--out-dir", required=True)
    args = p.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    df = load(args.results_dir)
    agg = df.groupby(["replication", "chunk_kb"]).agg(
        upload_MBps=("upload_MBps", "mean"),
        download_MBps=("download_MBps", "mean"),
        upload_s=("upload_s", "mean"),
        download_s=("download_s", "mean"),
        n=("file", "count"),
    ).reset_index()
    agg.to_csv(os.path.join(args.out_dir, "agregat_per_config.csv"), index=False)
    print(agg.to_string(index=False))

    # 1. Throughput vs replikasi (chunk 1 MB, kalau ada; kalau tidak, chunk pertama)
    sub = agg[agg["chunk_kb"] == 1024]
    if sub.empty:
        sub = agg[agg["chunk_kb"] == agg["chunk_kb"].min()]
    chunk_label = int(sub["chunk_kb"].iloc[0])
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar([f"{int(r)}x" for r in sub["replication"]] , sub["upload_MBps"], label="Upload")
    ax.bar([f"{int(r)}x" for r in sub["replication"]], sub["download_MBps"],
           bottom=sub["upload_MBps"], label="Download", alpha=0.7)
    ax.set_xlabel("Faktor replikasi")
    ax.set_ylabel("Throughput rata-rata (MB/detik)")
    ax.set_title(f"Throughput vs replikasi (chunk {chunk_label} KB, per file)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(args.out_dir, "throughput_vs_replikasi.png"), dpi=150)
    plt.close(fig)

    # 2. Latensi vs ukuran chunk (replikasi 2x, kalau ada)
    sub2 = agg[agg["replication"] == 2]
    if sub2.empty:
        sub2 = agg[agg["replication"] == agg["replication"].min()]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    x = [f"{int(c)} KB" for c in sub2["chunk_kb"]]
    ax.plot(x, sub2["upload_s"], marker="o", label="Upload")
    ax.plot(x, sub2["download_s"], marker="s", label="Download")
    ax.set_xlabel("Ukuran chunk")
    ax.set_ylabel("Latensi rata-rata per file (detik)")
    ax.set_title(f"Latensi vs ukuran chunk (replikasi {int(sub2['replication'].iloc[0])}x)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(args.out_dir, "latensi_vs_chunk.png"), dpi=150)
    plt.close(fig)

    # 3. Throughput semua konfigurasi
    fig, ax = plt.subplots(figsize=(8, 4.5))
    labels = [f"{int(r)}x / {int(c)} KB" for r, c in zip(agg["replication"], agg["chunk_kb"])]
    xs = range(len(agg))
    ax.bar([x - 0.2 for x in xs], agg["upload_MBps"], width=0.4, label="Upload")
    ax.bar([x + 0.2 for x in xs], agg["download_MBps"], width=0.4, label="Download")
    ax.set_xticks(list(xs))
    ax.set_xticklabels(labels, rotation=25, ha="right")
    ax.set_ylabel("Throughput rata-rata (MB/detik)")
    ax.set_title("Throughput per konfigurasi")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(args.out_dir, "throughput_per_config.png"), dpi=150)
    plt.close(fig)

    print(f"Grafik tersimpan di {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
