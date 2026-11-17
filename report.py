"""Generación del reporte PDF de comparación (reportlab)."""
import time
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

GREEN = colors.HexColor("#16a34a")
DARK = colors.HexColor("#0b0f0d")
STATUS_COLORS = {
    "OK": colors.HexColor("#16a34a"), "MODIFICADO": colors.HexColor("#d97706"),
    "CORRUPTO": colors.HexColor("#dc2626"), "FALTANTE": colors.HexColor("#7c3aed"),
    "NUEVO": colors.HexColor("#2563eb"),
}


def _fmt_size(n):
    if n is None:
        return "-"
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def build_report(path, snapshot, results, summary):
    ss = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=ss["Title"], textColor=GREEN, alignment=0, fontSize=22)
    small = ParagraphStyle("s", parent=ss["BodyText"], fontSize=7.5, leading=9)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=10)
    h2 = ParagraphStyle("h", parent=ss["Heading2"], textColor=DARK)

    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm,
                            title="Reporte de integridad - VaultGuard")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    snap_date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snapshot["created"]))
    total = len(results)
    bad = summary["CORRUPTO"]
    verdict = ("INTEGRIDAD VERIFICADA: no se detectaron archivos corruptos." if bad == 0
               else f"ATENCIÓN: se detectaron {bad} archivo(s) corrupto(s).")
    vcolor = GREEN if bad == 0 else STATUS_COLORS["CORRUPTO"]

    el = [Paragraph("VaultGuard · Reporte de integridad", title),
          Paragraph(f"Generado: {now}<br/>Respaldo comparado: <b>{snapshot['name']}</b> ({snap_date})<br/>"
                    f"Archivos analizados: {total}", body),
          Spacer(1, 6 * mm),
          Paragraph(f"<font color='{vcolor.hexval().replace('0x', '#')}'><b>{verdict}</b></font>", body),
          Spacer(1, 4 * mm), Paragraph("Resumen", h2)]

    rows = [["Estado", "Cantidad"]] + [[k, str(v)] for k, v in summary.items()]
    t = Table(rows, colWidths=[50 * mm, 30 * mm], hAlign="LEFT")
    style = [("BACKGROUND", (0, 0), (-1, 0), DARK), ("TEXTCOLOR", (0, 0), (-1, 0), GREEN),
             ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 9)]
    for i, k in enumerate(summary, start=1):
        style.append(("TEXTCOLOR", (0, i), (0, i), STATUS_COLORS[k]))
        style.append(("FONTNAME", (0, i), (0, i), "Helvetica-Bold"))
    t.setStyle(TableStyle(style))
    el += [t, Spacer(1, 6 * mm), Paragraph("Detalle por archivo", h2)]

    data = [["Archivo", "Tamaño", "Estado", "Detalle / SHA-256"]]
    cmds = [("BACKGROUND", (0, 0), (-1, 0), DARK), ("TEXTCOLOR", (0, 0), (-1, 0), GREEN),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, 0), 8)]
    # Los problemas primero
    order = {"CORRUPTO": 0, "FALTANTE": 1, "MODIFICADO": 2, "NUEVO": 3, "OK": 4}
    for i, r in enumerate(sorted(results, key=lambda r: order[r["status"]]), start=1):
        hashes = ""
        if r["snap_sha"]:
            hashes += f"<br/>Respaldo: {r['snap_sha'][:32]}…"
        if r["live_sha"]:
            hashes += f"<br/>Actual: {r['live_sha'][:32]}…"
        data.append([Paragraph(r["path"], small), _fmt_size(r["size"]), r["status"],
                     Paragraph(r["detail"] + hashes, small)])
        cmds.append(("TEXTCOLOR", (2, i), (2, i), STATUS_COLORS[r["status"]]))
        cmds.append(("FONTNAME", (2, i), (2, i), "Helvetica-Bold"))
        cmds.append(("FONTSIZE", (1, i), (2, i), 8))
    if len(data) == 1:
        data.append(["(sin archivos)", "", "", ""])
    dt = Table(data, colWidths=[55 * mm, 20 * mm, 24 * mm, 81 * mm], repeatRows=1)
    dt.setStyle(TableStyle(cmds))
    el.append(dt)

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(15 * mm, 8 * mm, "VaultGuard · SHA-256")
        canvas.drawRightString(A4[0] - 15 * mm, 8 * mm, f"Página {d.page}")
        canvas.setStrokeColor(GREEN)
        canvas.line(15 * mm, 11 * mm, A4[0] - 15 * mm, 11 * mm)
        canvas.restoreState()

    doc.build(el, onFirstPage=footer, onLaterPages=footer)
    return path
