import tempfile, pathlib
from vault import Vault, type_folder
from report import build_report

tmp = pathlib.Path(tempfile.mkdtemp())
src = tmp / "src"; (src / "sub").mkdir(parents=True)
(src / "a.txt").write_text("hola"); (src / "sub" / "b.txt").write_text("mundo"); (src / "c.txt").write_text("tres")
v = Vault(tmp / "vd")
print(v.add_external(None, src))
sid, sk = v.create_snapshot(); assert not sk
r, s = v.compare(sid); assert s["OK"] == 3, s
paths = [f[1] for f in v.all_files()]
assert "src/Texto/a.txt" in paths and "src/sub/Texto/b.txt" in paths, paths
# modificar
(src / "a.txt").write_text("hola2"); v.add_external(None, src / "a.txt")
assert "Texto/a.txt" in [f[1] for f in v.all_files()]
v.delete(v._find(v._find(None, "Texto")["id"], "a.txt")["id"])  # limpiar el archivo suelto de la prueba
# corromper
fid = [f for f in v.all_files() if f[1].endswith("c.txt")][0][0]; v.simulate_corruption(fid)
# faltante
bid = [f for f in v.all_files() if f[1].endswith("b.txt")][0][0]; v.delete(bid)
r, s = v.compare(sid); print(s)
assert s["CORRUPTO"] == 1 and s["FALTANTE"] == 1
build_report(str(tmp / "r.pdf"), v.snapshot(sid), r, s); assert (tmp / "r.pdf").stat().st_size > 1000
v.restore_snapshot(sid); r, s = v.compare(sid); assert s["OK"] == 3, s

# --- organización por tipo + orden alfabético
v2 = Vault(tmp / "vd2")
files = tmp / "files"; files.mkdir()
for n in ["zeta.pdf", "Árbol.pdf", "beta.PDF", "informe.docx", "datos.xlsx", "foto.jpg", "x.zip", "y.rar", "LEEME", "nota.xyz"]:
    (files / n).write_text(n)
for f in files.iterdir():
    v2.add_external(None, f)
top = [n["name"] for n in v2.children(None)]
print(top)
assert set(top) == {"PDF", "Word", "Excel", "Imágenes", "Comprimidos", "Otros", "XYZ"}, top
assert [n["name"] for n in v2.children(v2._find(None, "PDF")["id"])] == ["Árbol.pdf", "beta.PDF", "zeta.pdf"]
assert type_folder("a.docx") == "Word" and type_folder("a.PDF") == "PDF"
print("TODO OK")
