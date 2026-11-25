# DFS-X — Mini Distributed File System

**Judul UAS:** DFS-X: Analisis Throughput dan Latensi Upload/Download pada Mini
Distributed File System dengan Partisi Hash dan Replikasi Berbasis Docker Compose
**Mata kuliah:** Komputasi Paralel & Terdistribusi — **Ujian:** Kamis, 3 Desember 2026
**Dosen:** Ir. Randi Rizal, Ph.D. — **Kelompok:** 2 orang (nomor kelompok + nama anggota ke-2 menyusul)

## Arsitektur

```
                 +------------------+
                 |  client/dfsx.py  |  terminal: upload / download / list / delete / status
                 +--------+---------+
                          | 1. minta /plan (penempatan chunk)
                          v
                 +------------------+  metadata: nama file -> daftar chunk
                 |  master (REST)   |  partisi hash SHA-256(nama:indeks) mod 3
                 |  :5000           |  heartbeat data node, metadata.json
                 +--------+---------+
                          | 2. client PUT chunk LANGSUNG ke data node
          +---------------+---------------+
          v               v               v
   datanode1 :5001  datanode2 :5002  datanode3 :5003
   (volume Docker)   (volume Docker)   (volume Docker)
```

- **Partisi hash:** chunk `i` file `F` primernya node `SHA-256("F:i") mod 3`.
- **Replikasi:** default 2x — tiap chunk ada di node primer + node berikutnya (siklik).
  File tetap bisa di-download selama >= 1 replika tiap chunk masih hidup.
- **Download:** client tanya peta chunk ke master, lalu ambil tiap chunk dari
  data node pertama yang masih hidup, rakit ulang sesuai urutan indeks.

## Cara jalan (Docker — yang utama)

Butuh Docker Desktop (di Windows paling gampang lewat WSL — cek dulu
`docker --version` sebelum mulai).

```bash
docker compose up --build
# master http://localhost:5000, data node 5001-5003
pip install -r client/requirements.txt
python client/dfsx.py status
python client/dfsx.py upload contoh.txt
python client/dfsx.py download contoh.txt -o contoh_unduh.txt
python client/dfsx.py list
```

## Cara jalan tanpa Docker (untuk tes cepat / kalau Docker belum siap)

4 terminal, dari folder `dfs-x/` (butuh `pip install -r requirements.txt`):

```bash
# terminal 1-3: data node
PORT=5001 NODE_ID=node1 DATA_DIR=./data/dn1 python datanode/app.py
PORT=5002 NODE_ID=node2 DATA_DIR=./data/dn2 python datanode/app.py
PORT=5003 NODE_ID=node3 DATA_DIR=./data/dn3 python datanode/app.py
# terminal 4: master
MASTER_DATA_DIR=./data/master python master/app.py
# terminal 5: client
python client/dfsx.py status
```

## Yang sudah dites (skeleton, 20 Nov 2026, di VM Muse)

- Upload file 1,3 MB (chunk 256 KB, replikasi 2x) -> download ulang, hash SHA-256 sama persis.
- Matikan 1 data node (node2, yang menyimpan 5 dari 10 salinan chunk) ->
  `status` menampilkan node2 MATI, download tetap berhasil dari replika,
  hash SHA-256 sama persis dengan file asli.
- `list`, `delete`, `status` (heartbeat) jalan.
- Docker Compose belum dites end-to-end di VM ini (tidak ada Docker di VM);
  tes `docker compose up` di laptop sebelum demo.

## Eksperimen 100 file (harness sudah siap, dites 20 Nov 2026)

`experiments/run_experiments.py` + `experiments/make_graphs.py` — dibuat
lebih awal dari jadwal 28–29 Nov, tinggal dijalankan di laptop setelah
Docker dites:

```bash
# eksperimen utama sesuai soal: 100 file x 512 KB = 50 MB, replikasi 2x, chunk 1 MB
python experiments/run_experiments.py --out-dir experiments/results
# sapuan replikasi 1x/2x/3x x chunk 256 KB/1 MB/4 MB (9 konfigurasi)
python experiments/run_experiments.py --sweep --out-dir experiments/results
# grafik dari CSV hasil: throughput vs replikasi, latensi vs chunk
python experiments/make_graphs.py --results-dir experiments/results --out-dir experiments/results/grafik
```

Dites end-to-end di VM (mode tanpa Docker, 20 Nov 2026): 100/100 file,
hash SHA-256 download cocok semua, upload 34,66 MB/detik, download
89,65 MB/detik, latensi rata-rata upload 0,0146 dtk / download 0,0057 dtk.
**Angka VM ini BUKAN hasil laporan** — angka final harus dari run ulang di
laptop dengan Docker Compose, karena mesinnya beda.

## Yang BELUM ada (tahap berikut, sesuai timeline)

- **25-27 Nov:** re-replikasi otomatis saat satu node mati permanen.
- **28-29 Nov:** eksperimen 100 file (total 50 MB) + grafik throughput/latensi
  (replikasi 1x/2x/3x, chunk 256 KB/1 MB/4 MB, matikan 1 node) — harness-nya
  sudah siap (lihat di atas), tinggal run di laptop.
- **Bonus +5%:** monitoring/dashboard, Kubernetes — hanya kalau inti sudah beres.

## Pembagian 2 orang (dari rencana)

- **Orang 1:** master + metadata + partisi hash + replikasi.
- **Orang 2:** data node + client terminal + eksperimen + grafik.
- Laporan IEEE + PPT dikerjakan bareng di akhir; demo 10 menit dua-duanya harus paham kodenya.
