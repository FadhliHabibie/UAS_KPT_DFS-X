"""DFS-X data node: menyimpan chunk file dan melayani REST chunk API.

Jalan dengan env:
  NODE_ID  - nama node ini, mis. node1 (default: node1)
  PORT     - port HTTP node ini (default: 5001)
  DATA_DIR - folder penyimpanan chunk (default: ./data)

Endpoint:
  GET    /health            -> {"node", "status", "chunks"}
  PUT    /chunk/<id>        -> simpan chunk (body = byte mentah)
  GET    /chunk/<id>        -> ambil chunk
  HEAD   /chunk/<id>        -> cek chunk ada atau tidak
  DELETE /chunk/<id>        -> hapus chunk
"""

import os

from flask import Flask, abort, jsonify, request, send_file

app = Flask(__name__)

NODE_ID = os.environ.get("NODE_ID", "node1")
PORT = int(os.environ.get("PORT", "5001"))
DATA_DIR = os.environ.get(
    "DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
)
os.makedirs(DATA_DIR, exist_ok=True)


def chunk_path(chunk_id: str) -> str:
    # Hanya nama file polos, cegah path traversal (mis. "../").
    return os.path.join(DATA_DIR, os.path.basename(chunk_id))


@app.route("/health", methods=["GET"])
def health():
    n = sum(
        1
        for f in os.listdir(DATA_DIR)
        if os.path.isfile(os.path.join(DATA_DIR, f))
    )
    return jsonify({"node": NODE_ID, "status": "ok", "chunks": n})


@app.route("/chunk/<chunk_id>", methods=["PUT", "POST"])
def put_chunk(chunk_id):
    with open(chunk_path(chunk_id), "wb") as f:
        f.write(request.get_data())
    return jsonify({"node": NODE_ID, "chunk": chunk_id, "stored": True}), 201


@app.route("/chunk/<chunk_id>", methods=["GET"])
def get_chunk(chunk_id):
    path = chunk_path(chunk_id)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype="application/octet-stream")


@app.route("/chunk/<chunk_id>", methods=["HEAD"])
def head_chunk(chunk_id):
    if os.path.isfile(chunk_path(chunk_id)):
        return "", 200
    abort(404)


@app.route("/chunk/<chunk_id>", methods=["DELETE"])
def delete_chunk(chunk_id):
    path = chunk_path(chunk_id)
    if os.path.isfile(path):
        os.remove(path)
        return jsonify({"node": NODE_ID, "chunk": chunk_id, "deleted": True})
    abort(404)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
