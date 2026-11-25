"""DFS-X master: metadata, partisi hash, replikasi, heartbeat.

Jalan dengan env:
  PORT            - port HTTP master (default: 5000)
  MASTER_DATA_DIR - folder metadata.json (default: ./data)
  DATANODE_URLS   - daftar URL data node, dipisah koma, URUTAN PENTING
                    (default: http://localhost:5001,http://localhost:5002,http://localhost:5003)
                    Urutan URL = node1, node2, node3.

Alur (sesuai rencana):
  1. Client minta rencana penempatan: POST /plan
     -> master hitung partisi hash (SHA-256 nama file + indeks chunk,
        modulo jumlah node) + daftar node replika.
  2. Client PUT tiap chunk LANGSUNG ke data node yang ditunjuk.
  3. Client konfirmasi: POST /commit -> master verifikasi tiap chunk
     ada di >= 1 node, lalu simpan metadata (persisten di metadata.json).
  4. Download: client GET /files/<nama> (peta chunk), lalu GET chunk
     langsung dari data node pertama yang hidup.

Endpoint:
  GET    /status                  -> heartbeat tiap data node + jumlah file
  POST   /plan                    -> rencana penempatan chunk
  POST   /commit                  -> simpan metadata setelah chunk ter-upload
  GET    /files                   -> daftar file
  GET    /files/<nama>            -> metadata + peta chunk satu file
  GET    /files/<nama>/download   -> master merakit ulang file (jalan pintas demo)
  DELETE /files/<nama>            -> hapus metadata + semua chunk di node

Yang BELUM ada di skeleton ini (tahap 25-27 Nov): re-replikasi otomatis
saat satu node mati permanen. Saat ini ketahanan datang dari replikasi:
file tetap bisa di-download selama >= 1 replika tiap chunk masih hidup.
"""

import hashlib
import json
import os

import requests
from flask import Flask, Response, abort, jsonify, request

app = Flask(__name__)

PORT = int(os.environ.get("PORT", "5000"))
DATA_DIR = os.environ.get(
    "MASTER_DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
)
os.makedirs(DATA_DIR, exist_ok=True)
META_FILE = os.path.join(DATA_DIR, "metadata.json")

DATANODE_URLS = [
    u.rstrip("/")
    for u in os.environ.get(
        "DATANODE_URLS",
        "http://localhost:5001,http://localhost:5002,http://localhost:5003",
    ).split(",")
    if u.strip()
]
NODE_NAMES = [f"node{i + 1}" for i in range(len(DATANODE_URLS))]


def load_meta():
    if os.path.isfile(META_FILE):
        with open(META_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_meta(meta):
    tmp = META_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp, META_FILE)


def chunk_id_for(filename: str, index: int) -> str:
    # ID chunk stabil + aman URL: hash nama file + indeks, bukan nama mentah.
    prefix = hashlib.sha256(filename.encode()).hexdigest()[:12]
    return f"{prefix}-{index:04d}"


def place_chunk(filename: str, index: int, replication: int) -> list[int]:
    """Partisi hash: node primer = SHA-256(nama:index) mod jumlah node,
    replika = node berikutnya secara siklik."""
    digest = int(hashlib.sha256(f"{filename}:{index}".encode()).hexdigest(), 16)
    primary = digest % len(DATANODE_URLS)
    n = max(1, min(replication, len(DATANODE_URLS)))
    return [(primary + i) % len(DATANODE_URLS) for i in range(n)]


def node_alive(url: str, timeout: float = 2.0):
    try:
        r = requests.get(url + "/health", timeout=timeout)
        if r.status_code == 200:
            return True, r.json().get("chunks", 0)
    except requests.RequestException:
        pass
    return False, 0


@app.route("/status", methods=["GET"])
def status():
    nodes = []
    for name, url in zip(NODE_NAMES, DATANODE_URLS):
        alive, n_chunks = node_alive(url)
        nodes.append(
            {"name": name, "url": url, "alive": alive, "chunks": n_chunks}
        )
    meta = load_meta()
    return jsonify({"master": "ok", "nodes": nodes, "files": len(meta)})


@app.route("/plan", methods=["POST"])
def plan():
    body = request.get_json(force=True)
    filename = body.get("filename")
    size = int(body.get("size", 0))
    chunk_size = int(body.get("chunk_size", 1024 * 1024))
    replication = int(body.get("replication", 2))
    if not filename or size <= 0 or chunk_size <= 0:
        abort(400, "filename, size (>0), dan chunk_size (>0) wajib diisi")
    n_chunks = (size + chunk_size - 1) // chunk_size
    chunks = []
    for i in range(n_chunks):
        node_idx = place_chunk(filename, i, replication)
        chunks.append(
            {
                "index": i,
                "id": chunk_id_for(filename, i),
                "nodes": [NODE_NAMES[j] for j in node_idx],
                "urls": [DATANODE_URLS[j] for j in node_idx],
            }
        )
    return jsonify(
        {
            "filename": filename,
            "size": size,
            "chunk_size": chunk_size,
            "replication": replication,
            "chunks": chunks,
        }
    )


@app.route("/commit", methods=["POST"])
def commit():
    body = request.get_json(force=True)
    filename = body.get("filename")
    chunks = body.get("chunks", [])
    if not filename or not chunks:
        abort(400, "filename dan chunks wajib diisi")
    # Verifikasi: tiap chunk harus ada di >= 1 node yang ditunjuk.
    missing = []
    for ch in chunks:
        ok = False
        for url in ch.get("urls", []):
            try:
                r = requests.head(url + "/chunk/" + ch["id"], timeout=2)
                if r.status_code == 200:
                    ok = True
                    break
            except requests.RequestException:
                continue
        if not ok:
            missing.append(ch["id"])
    if missing:
        return jsonify({"error": "chunk belum ada di node manapun", "missing": missing}), 400
    meta = load_meta()
    meta[filename] = {
        "filename": filename,
        "size": body.get("size"),
        "chunk_size": body.get("chunk_size"),
        "replication": body.get("replication"),
        "chunks": chunks,
    }
    save_meta(meta)
    return jsonify({"stored": True, "filename": filename, "chunks": len(chunks)}), 201


@app.route("/files", methods=["GET"])
def list_files():
    meta = load_meta()
    return jsonify(
        [
            {"filename": name, "size": info.get("size"), "chunks": len(info.get("chunks", []))}
            for name, info in meta.items()
        ]
    )


@app.route("/files/<path:filename>", methods=["GET"])
def get_file(filename):
    meta = load_meta()
    if filename not in meta:
        abort(404)
    return jsonify(meta[filename])


@app.route("/files/<path:filename>/download", methods=["GET"])
def download_file(filename):
    """Jalan pintas demo: master merakit ulang file dari chunk.
    Client normal (client/dfsx.py) mengambil chunk langsung dari node."""
    meta = load_meta()
    if filename not in meta:
        abort(404)
    info = meta[filename]

    def generate():
        for ch in info["chunks"]:
            data = None
            for url in ch["urls"]:
                try:
                    r = requests.get(url + "/chunk/" + ch["id"], timeout=5)
                    if r.status_code == 200:
                        data = r.content
                        break
                except requests.RequestException:
                    continue
            if data is None:
                raise RuntimeError(f"chunk {ch['id']} tidak bisa diambil dari node manapun")
            yield data

    return Response(
        generate(),
        mimetype="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/files/<path:filename>", methods=["DELETE"])
def delete_file(filename):
    meta = load_meta()
    if filename not in meta:
        abort(404)
    info = meta.pop(filename)
    save_meta(meta)
    deleted, failed = 0, 0
    for ch in info["chunks"]:
        for url in ch["urls"]:
            try:
                r = requests.delete(url + "/chunk/" + ch["id"], timeout=2)
                if r.status_code == 200:
                    deleted += 1
                else:
                    failed += 1
            except requests.RequestException:
                failed += 1
    return jsonify({"deleted": True, "filename": filename, "chunk_deletes_ok": deleted})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
