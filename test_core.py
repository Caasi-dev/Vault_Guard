import tempfile, pathlib
from vault import Vault
from report import build_report

tmp = pathlib.Path(tempfile.mkdtemp())
src = tmp / "src"; (src / "sub").mkdir(parents=True)
(src / "a.txt").write_text("hola"); (src / "sub" / "b.txt").write_text("mundo"); (src / "c.txt").write_text("tres")
v = Vault(tmp / "vd")
print(v.add_external(None, src))
sid, sk = v.create_snapshot(); assert not sk
r, s = v.compare(sid); assert s["OK"] == 3, s
# modificar
(src / "a.txt").write_text("hola2"); v.add_external(v.children(None)[0]["id"], src / "a.txt")
# corromper
fid = [f for f in v.all_files() if f[1].endswith("c.txt")][0][0]; v.simulate_corruption(fid)
# faltante
bid = [f for f in v.all_files() if f[1].endswith("b.txt")][0][0]; v.delete(bid)
r, s = v.compare(sid); print(s)
assert s["MODIFICADO"] == 1 and s["CORRUPTO"] == 1 and s["FALTANTE"] == 1
build_report(str(tmp / "r.pdf"), v.snapshot(sid), r, s); assert (tmp / "r.pdf").stat().st_size > 1000
v.restore_snapshot(sid); r, s = v.compare(sid); assert s["OK"] == 3, s
print("TODO OK")
