"""Almacenamiento aislado (estilo Drive) con respaldos versionados y verificación SHA-256.

Todo vive dentro de la carpeta `vault_data/` de la app; nunca se modifica el disco fuera de ella
(salvo al exportar o guardar reportes cuando el usuario lo pide explícitamente).
"""
import hashlib
import os
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

CHUNK = 1024 * 1024


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


class Vault:
    def __init__(self, root):
        self.root = Path(root)
        self.files_dir = self.root / "files"
        self.objects_dir = self.root / "objects"
        self.reports_dir = self.root / "reports"
        for d in (self.files_dir, self.objects_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "vault.db")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS nodes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER, name TEXT NOT NULL, is_dir INTEGER NOT NULL,
            size INTEGER DEFAULT 0, sha256 TEXT, storage TEXT, mtime REAL);
        CREATE TABLE IF NOT EXISTS snapshots(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, kind TEXT,
            created REAL, file_count INTEGER, total_size INTEGER);
        CREATE TABLE IF NOT EXISTS entries(
            snapshot_id INTEGER, path TEXT, sha256 TEXT, size INTEGER);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        """)
        self.db.commit()

    # ---------------- ajustes ----------------
    def get(self, key, default=None):
        r = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, str(value)))
        self.db.commit()

    # ---------------- árbol de archivos ----------------
    def children(self, parent_id):
        return self.db.execute(
            "SELECT * FROM nodes WHERE parent_id IS ? ORDER BY is_dir DESC, LOWER(name)",
            (parent_id,)).fetchall()

    def node(self, node_id):
        return self.db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()

    def path_of(self, node_id) -> str:
        parts = []
        while node_id is not None:
            n = self.node(node_id)
            parts.append(n["name"])
            node_id = n["parent_id"]
        return "/".join(reversed(parts))

    def breadcrumb(self, node_id):
        crumbs = []
        while node_id is not None:
            n = self.node(node_id)
            crumbs.append((n["id"], n["name"]))
            node_id = n["parent_id"]
        return list(reversed(crumbs))

    def _find(self, parent_id, name):
        return self.db.execute("SELECT * FROM nodes WHERE parent_id IS ? AND name=?",
                               (parent_id, name)).fetchone()

    def mkdir(self, parent_id, name):
        ex = self._find(parent_id, name)
        if ex:
            if ex["is_dir"]:
                return ex["id"]
            raise ValueError(f"Ya existe un archivo llamado '{name}'")
        cur = self.db.execute(
            "INSERT INTO nodes(parent_id,name,is_dir,mtime) VALUES(?,?,1,?)",
            (parent_id, name, time.time()))
        self.db.commit()
        return cur.lastrowid

    def add_file(self, parent_id, src) -> bool:
        """Copia un archivo externo al entorno. Devuelve True si reemplazó una versión previa."""
        src = Path(src)
        name = src.name
        storage = uuid.uuid4().hex
        dest = self.files_dir / storage
        h = hashlib.sha256()
        with open(src, "rb") as fi, open(dest, "wb") as fo:
            while chunk := fi.read(CHUNK):
                h.update(chunk)
                fo.write(chunk)
        size = dest.stat().st_size
        ex = self._find(parent_id, name)
        replaced = False
        if ex:
            if ex["is_dir"]:
                dest.unlink()
                raise ValueError(f"Ya existe una carpeta llamada '{name}'")
            old = self.files_dir / ex["storage"]
            if old.exists():
                old.unlink()
            self.db.execute(
                "UPDATE nodes SET size=?, sha256=?, storage=?, mtime=? WHERE id=?",
                (size, h.hexdigest(), storage, time.time(), ex["id"]))
            replaced = True
        else:
            self.db.execute(
                "INSERT INTO nodes(parent_id,name,is_dir,size,sha256,storage,mtime) VALUES(?,?,0,?,?,?,?)",
                (parent_id, name, size, h.hexdigest(), storage, time.time()))
        self.db.commit()
        return replaced

    def add_external(self, parent_id, src):
        """Añade archivo o carpeta (recursivo). Devuelve (añadidos, reemplazados)."""
        src = Path(src)
        added = replaced = 0
        if src.is_dir():
            folder = self.mkdir(parent_id, src.name)
            for child in sorted(src.iterdir()):
                a, r = self.add_external(folder, child)
                added += a
                replaced += r
        elif src.is_file():
            if self.add_file(parent_id, src):
                replaced += 1
            else:
                added += 1
        return added, replaced

    def rename(self, node_id, new_name):
        n = self.node(node_id)
        ex = self._find(n["parent_id"], new_name)
        if ex and ex["id"] != node_id:
            raise ValueError("Ya existe un elemento con ese nombre")
        self.db.execute("UPDATE nodes SET name=? WHERE id=?", (new_name, node_id))
        self.db.commit()

    def is_descendant(self, node_id, ancestor_id):
        while node_id is not None:
            if node_id == ancestor_id:
                return True
            node_id = self.node(node_id)["parent_id"]
        return False

    def move(self, node_id, new_parent_id):
        n = self.node(node_id)
        if new_parent_id is not None and self.is_descendant(new_parent_id, node_id):
            raise ValueError("No puedes mover una carpeta dentro de sí misma")
        if self._find(new_parent_id, n["name"]):
            raise ValueError("Ya existe un elemento con ese nombre en el destino")
        self.db.execute("UPDATE nodes SET parent_id=? WHERE id=?", (new_parent_id, node_id))
        self.db.commit()

    def folders(self):
        """Lista (id, ruta) de todas las carpetas; id None = raíz."""
        out = [(None, "/ (raíz)")]
        rows = self.db.execute("SELECT id FROM nodes WHERE is_dir=1").fetchall()
        out += sorted(((r["id"], "/" + self.path_of(r["id"])) for r in rows), key=lambda x: x[1].lower())
        return out

    def delete(self, node_id):
        n = self.node(node_id)
        if n["is_dir"]:
            for c in self.children(node_id):
                self.delete(c["id"])
        elif n["storage"]:
            p = self.files_dir / n["storage"]
            if p.exists():
                p.unlink()
        self.db.execute("DELETE FROM nodes WHERE id=?", (node_id,))
        self.db.commit()

    def all_files(self):
        """[(id, ruta, size, sha_registrado, storage)] de todo el árbol."""
        rows = self.db.execute("SELECT * FROM nodes WHERE is_dir=0").fetchall()
        return [(r["id"], self.path_of(r["id"]), r["size"], r["sha256"], r["storage"]) for r in rows]

    def export(self, node_id, dest_dir):
        n = self.node(node_id)
        dest_dir = Path(dest_dir)
        if n["is_dir"]:
            target = dest_dir / n["name"]
            target.mkdir(parents=True, exist_ok=True)
            for c in self.children(node_id):
                self.export(c["id"], target)
        else:
            shutil.copy2(self.files_dir / n["storage"], dest_dir / n["name"])

    def simulate_corruption(self, node_id):
        """Altera un byte del archivo almacenado (para probar la detección)."""
        n = self.node(node_id)
        if n["is_dir"]:
            raise ValueError("Selecciona un archivo")
        p = self.files_dir / n["storage"]
        with open(p, "r+b") as f:
            data = f.read(1)
            f.seek(0)
            if data:
                f.write(bytes([data[0] ^ 0xFF]))
            else:
                f.write(b"\x00")

    # ---------------- respaldos ----------------
    def create_snapshot(self, kind="manual", name=None):
        """Respalda todos los archivos. Los archivos ya corruptos NO se respaldan (se reportan)."""
        entries, skipped = [], []
        for _id, path, size, sha, storage in self.all_files():
            src = self.files_dir / storage
            if not src.exists() or sha256_file(src) != sha:
                skipped.append(path)
                continue
            obj = self.objects_dir / sha
            if not obj.exists():
                shutil.copy2(src, obj)
            entries.append((path, sha, size))
        now = time.time()
        label = name or f"{'Auto' if kind == 'auto' else 'Manual'} {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}"
        cur = self.db.execute(
            "INSERT INTO snapshots(name,kind,created,file_count,total_size) VALUES(?,?,?,?,?)",
            (label, kind, now, len(entries), sum(e[2] for e in entries)))
        sid = cur.lastrowid
        self.db.executemany("INSERT INTO entries VALUES(?,?,?,?)", [(sid, *e) for e in entries])
        self.db.commit()
        self.set("last_backup", now)
        return sid, skipped

    def snapshots(self):
        return self.db.execute("SELECT * FROM snapshots ORDER BY created DESC").fetchall()

    def snapshot(self, sid):
        return self.db.execute("SELECT * FROM snapshots WHERE id=?", (sid,)).fetchone()

    def delete_snapshot(self, sid):
        self.db.execute("DELETE FROM entries WHERE snapshot_id=?", (sid,))
        self.db.execute("DELETE FROM snapshots WHERE id=?", (sid,))
        self.db.commit()
        self._prune_objects()

    def apply_retention(self, keep):
        for s in self.snapshots()[keep:]:
            self.delete_snapshot(s["id"])

    def _prune_objects(self):
        used = {r[0] for r in self.db.execute("SELECT DISTINCT sha256 FROM entries")}
        for p in self.objects_dir.iterdir():
            if p.name not in used:
                p.unlink()

    def restore_snapshot(self, sid):
        """Reemplaza el contenido actual por el del respaldo. Devuelve lista de archivos no restaurables."""
        rows = self.db.execute("SELECT * FROM entries WHERE snapshot_id=?", (sid,)).fetchall()
        failed = []
        for c in self.children(None):
            self.delete(c["id"])
        for r in rows:
            obj = self.objects_dir / r["sha256"]
            if not obj.exists() or sha256_file(obj) != r["sha256"]:
                failed.append(r["path"])
                continue
            parent = None
            *dirs, fname = r["path"].split("/")
            for d in dirs:
                parent = self.mkdir(parent, d)
            storage = uuid.uuid4().hex
            shutil.copy2(obj, self.files_dir / storage)
            self.db.execute(
                "INSERT INTO nodes(parent_id,name,is_dir,size,sha256,storage,mtime) VALUES(?,?,0,?,?,?,?)",
                (parent, fname, r["size"], r["sha256"], storage, time.time()))
        self.db.commit()
        return failed

    # ---------------- comparación ----------------
    def compare(self, sid):
        """Compara el estado actual contra un respaldo, recalculando hashes reales.

        Estados: OK, MODIFICADO (cambio legítimo, ambos íntegros), CORRUPTO (el contenido
        no coincide con su hash registrado), FALTANTE (en respaldo, no en actual), NUEVO.
        """
        snap = {r["path"]: r for r in self.db.execute(
            "SELECT * FROM entries WHERE snapshot_id=?", (sid,))}
        live = {p: (size, sha, storage) for _i, p, size, sha, storage in self.all_files()}
        results = []
        for path in sorted(set(snap) | set(live), key=str.lower):
            s, l = snap.get(path), live.get(path)
            row = {"path": path, "status": "OK", "detail": "", "live_sha": None, "snap_sha": None,
                   "size": None}
            if s is not None:
                row["snap_sha"] = s["sha256"]
                row["size"] = s["size"]
            if l is not None:
                row["live_sha"] = l[1]
                row["size"] = l[0]
            if s is None:
                row["status"], row["detail"] = "NUEVO", "No existía en el respaldo"
            elif l is None:
                row["status"], row["detail"] = "FALTANTE", "Existe en el respaldo pero no en el entorno actual"
            else:
                lp = self.files_dir / l[2]
                sp = self.objects_dir / s["sha256"]
                live_actual = sha256_file(lp) if lp.exists() else None
                snap_actual = sha256_file(sp) if sp.exists() else None
                problems = []
                if live_actual != l[1]:
                    problems.append("archivo actual corrupto (el contenido no coincide con su hash registrado)")
                if snap_actual != s["sha256"]:
                    problems.append("copia en el respaldo corrupta o ausente")
                if problems:
                    row["status"], row["detail"] = "CORRUPTO", "; ".join(problems)
                elif l[1] != s["sha256"]:
                    row["status"], row["detail"] = "MODIFICADO", "Contenido distinto al respaldo (versión nueva, ambos íntegros)"
                else:
                    row["detail"] = "Idéntico al respaldo"
            results.append(row)
        summary = {k: 0 for k in ("OK", "MODIFICADO", "CORRUPTO", "FALTANTE", "NUEVO")}
        for r in results:
            summary[r["status"]] += 1
        return results, summary
