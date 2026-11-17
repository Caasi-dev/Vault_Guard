"""VaultGuard - organiza, respalda y verifica la integridad de tus archivos."""
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QMainWindow, QMessageBox, QPushButton, QSpinBox, QStackedWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QGroupBox, QFormLayout, QTableWidget,
    QTableWidgetItem, QAbstractItemView,
)

from report import build_report
from vault import Vault

ROOT = Path(__file__).resolve().parent / "vault_data"

STYLE = """
* { font-family: 'Segoe UI', sans-serif; font-size: 13px; color: #d6e4dc; }
QMainWindow, QWidget#page, QDialog, QMessageBox, QInputDialog { background: #0b0f0d; }
QFrame#sidebar { background: #070a09; border-right: 1px solid #16231c; }
QLabel#logo { font-size: 20px; font-weight: 700; color: #22c55e; padding: 18px 16px 12px 16px; }
QLabel#title { font-size: 20px; font-weight: 600; color: #ffffff; }
QLabel#muted { color: #7b9185; }
QLabel#drop { border: 2px dashed #1f6f43; border-radius: 10px; padding: 14px; color: #4ade80; background: #0d1511; }
QPushButton#nav { text-align: left; padding: 11px 18px; border: none; border-left: 3px solid transparent;
    background: transparent; color: #9fb4a8; }
QPushButton#nav:hover { background: #0f1a14; }
QPushButton#nav:checked { background: #0f1a14; color: #22c55e; border-left: 3px solid #22c55e; font-weight: 600; }
QPushButton { background: #14201a; border: 1px solid #1f3a2c; border-radius: 6px; padding: 7px 14px; }
QPushButton:hover { border-color: #22c55e; }
QPushButton:disabled { color: #4b5b52; border-color: #16231c; }
QPushButton#primary { background: #16a34a; border: 1px solid #22c55e; color: #04110a; font-weight: 600; }
QPushButton#primary:hover { background: #22c55e; }
QPushButton#danger:hover { border-color: #ef4444; color: #ef4444; }
QTreeWidget, QTableWidget { background: #0d1411; border: 1px solid #16231c; border-radius: 8px;
    alternate-background-color: #0f1813; gridline-color: #16231c; outline: 0; }
QTreeWidget::item, QTableWidget::item { padding: 5px; }
QTreeWidget::item:selected, QTableWidget::item:selected { background: #14532d; color: #ffffff; }
QHeaderView::section { background: #101a15; color: #22c55e; border: none; border-bottom: 1px solid #1f3a2c; padding: 6px; font-weight: 600; }
QComboBox, QSpinBox { background: #101a15; border: 1px solid #1f3a2c; border-radius: 6px; padding: 5px 8px; min-height: 20px; }
QComboBox:hover, QSpinBox:hover { border-color: #22c55e; }
QComboBox QAbstractItemView { background: #101a15; selection-background-color: #14532d; border: 1px solid #1f3a2c; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #1f6f43; border-radius: 4px; background: #0d1411; }
QCheckBox::indicator:checked { background: #22c55e; }
QGroupBox { border: 1px solid #16231c; border-radius: 8px; margin-top: 14px; padding: 14px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; color: #22c55e; padding: 0 6px; }
QScrollBar:vertical { background: #0b0f0d; width: 10px; }
QScrollBar::handle:vertical { background: #1f3a2c; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #22c55e; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QToolTip { background: #101a15; color: #d6e4dc; border: 1px solid #22c55e; }
"""

STATUS_COLOR = {"OK": "#22c55e", "MODIFICADO": "#f59e0b", "CORRUPTO": "#ef4444",
                "FALTANTE": "#a78bfa", "NUEVO": "#60a5fa"}


def fmt_size(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def fmt_time(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(t))) if t else "—"


class DropTree(QTreeWidget):
    dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            self.dropped.emit(paths)


def page_title(text, sub=None):
    box = QVBoxLayout()
    t = QLabel(text); t.setObjectName("title")
    box.addWidget(t)
    if sub:
        s = QLabel(sub); s.setObjectName("muted"); s.setWordWrap(True)
        box.addWidget(s)
    return box


# ---------------------------------------------------------------- Archivos
class FilesPage(QWidget):
    changed = Signal()

    def __init__(self, vault):
        super().__init__()
        self.setObjectName("page")
        self.v = vault
        self.cwd = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addLayout(page_title("Mis archivos", "Entorno aislado: los archivos se copian a la app y nunca se modifican en tu disco."))

        bar = QHBoxLayout()
        self.up_btn = QPushButton("⬆ Subir"); self.up_btn.clicked.connect(self.go_up)
        self.crumb = QLabel(); self.crumb.setStyleSheet("color:#22c55e; font-weight:600;")
        bar.addWidget(self.up_btn); bar.addWidget(self.crumb, 1)
        for text, fn, name in [("📁 Nueva carpeta", self.new_folder, ""), ("＋ Agregar…", self.add_dialog, "primary"),
                               ("✎ Renombrar", self.rename, ""), ("➜ Mover", self.move, ""),
                               ("⬇ Exportar", self.export, ""), ("🧪 Simular corrupción", self.corrupt, ""),
                               ("🗑 Eliminar", self.delete, "danger")]:
            b = QPushButton(text); b.clicked.connect(fn)
            if name:
                b.setObjectName(name)
            if "Simular" in text:
                b.setToolTip("Altera un byte del archivo seleccionado para probar la detección de corrupción")
            bar.addWidget(b)
        lay.addLayout(bar)

        self.drop = QLabel("⇩  Arrastra aquí archivos o carpetas para agregarlos a esta ubicación")
        self.drop.setObjectName("drop"); self.drop.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.drop)

        self.tree = DropTree()
        self.tree.setHeaderLabels(["Nombre", "Tamaño", "Modificado", "SHA-256"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        h = self.tree.header(); h.setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setColumnWidth(1, 90); self.tree.setColumnWidth(2, 150); self.tree.setColumnWidth(3, 200)
        self.tree.itemDoubleClicked.connect(self.open_item)
        self.tree.dropped.connect(self.add_paths)
        lay.addWidget(self.tree, 1)
        self.status = QLabel(); self.status.setObjectName("muted")
        lay.addWidget(self.status)
        self.refresh()

    def refresh(self):
        self.tree.clear()
        crumbs = self.v.breadcrumb(self.cwd)
        self.crumb.setText("  ›  ".join(["Inicio"] + [n for _i, n in crumbs]))
        self.up_btn.setEnabled(self.cwd is not None)
        rows = self.v.children(self.cwd)
        for r in rows:
            it = QTreeWidgetItem([("📁 " if r["is_dir"] else "📄 ") + r["name"],
                                  "" if r["is_dir"] else fmt_size(r["size"]), fmt_time(r["mtime"]),
                                  "" if r["is_dir"] else (r["sha256"] or "")[:24] + "…"])
            it.setData(0, Qt.UserRole, r["id"])
            it.setData(0, Qt.UserRole + 1, bool(r["is_dir"]))
            self.tree.addTopLevelItem(it)
        self.status.setText(f"{len(rows)} elemento(s)")

    def selected_ids(self):
        return [i.data(0, Qt.UserRole) for i in self.tree.selectedItems()]

    def go_up(self):
        if self.cwd is not None:
            self.cwd = self.v.node(self.cwd)["parent_id"]
            self.refresh()

    def open_item(self, item, _c):
        if item.data(0, Qt.UserRole + 1):
            self.cwd = item.data(0, Qt.UserRole)
            self.refresh()

    def err(self, e):
        QMessageBox.warning(self, "VaultGuard", str(e))

    def add_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Selecciona archivos")
        if files:
            self.add_paths(files)

    def add_paths(self, paths):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        added = replaced = 0
        try:
            for p in paths:
                a, r = self.v.add_external(self.cwd, p)
                added += a; replaced += r
        except Exception as e:
            QApplication.restoreOverrideCursor(); self.err(e); return
        QApplication.restoreOverrideCursor()
        self.refresh(); self.changed.emit()
        self.status.setText(f"{added} agregado(s), {replaced} reemplazado(s) por nueva versión")

    def new_folder(self):
        name, ok = QInputDialog.getText(self, "Nueva carpeta", "Nombre:")
        if ok and name.strip():
            try:
                self.v.mkdir(self.cwd, name.strip()); self.refresh()
            except Exception as e:
                self.err(e)

    def rename(self):
        ids = self.selected_ids()
        if len(ids) != 1:
            return
        n = self.v.node(ids[0])
        name, ok = QInputDialog.getText(self, "Renombrar", "Nuevo nombre:", text=n["name"])
        if ok and name.strip():
            try:
                self.v.rename(ids[0], name.strip()); self.refresh(); self.changed.emit()
            except Exception as e:
                self.err(e)

    def move(self):
        ids = self.selected_ids()
        if not ids:
            return
        folders = self.v.folders()
        label, ok = QInputDialog.getItem(self, "Mover a", "Carpeta destino:", [f[1] for f in folders], 0, False)
        if not ok:
            return
        dest = folders[[f[1] for f in folders].index(label)][0]
        try:
            for i in ids:
                self.v.move(i, dest)
        except Exception as e:
            self.err(e)
        self.refresh(); self.changed.emit()

    def export(self):
        ids = self.selected_ids()
        if not ids:
            return
        d = QFileDialog.getExistingDirectory(self, "Exportar a la carpeta…")
        if d:
            for i in ids:
                self.v.export(i, d)
            self.status.setText(f"Exportado a {d}")

    def corrupt(self):
        ids = self.selected_ids()
        if len(ids) != 1:
            return
        if QMessageBox.question(self, "Simular corrupción",
                                "Esto altera un byte del archivo dentro del entorno para probar la verificación. ¿Continuar?") \
                == QMessageBox.Yes:
            try:
                self.v.simulate_corruption(ids[0])
            except Exception as e:
                self.err(e)

    def delete(self):
        ids = self.selected_ids()
        if ids and QMessageBox.question(self, "Eliminar", f"¿Eliminar {len(ids)} elemento(s) del entorno?\n"
                                        "Los respaldos existentes no se ven afectados.") == QMessageBox.Yes:
            for i in ids:
                self.v.delete(i)
            self.refresh(); self.changed.emit()


# ---------------------------------------------------------------- Respaldos
UNITS = [("Minutos", 60), ("Horas", 3600), ("Días", 86400)]


class BackupPage(QWidget):
    changed = Signal()

    def __init__(self, vault):
        super().__init__()
        self.setObjectName("page")
        self.v = vault
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addLayout(page_title("Respaldos", "Copias versionadas dentro del entorno. Los respaldos automáticos funcionan mientras la app esté abierta."))

        box = QGroupBox("Respaldo automático")
        form = QFormLayout(box)
        self.enable = QCheckBox("Activar respaldos por intervalo")
        self.every = QSpinBox(); self.every.setRange(1, 10000)
        self.unit = QComboBox(); self.unit.addItems([u[0] for u in UNITS])
        self.keep = QSpinBox(); self.keep.setRange(1, 1000)
        row = QHBoxLayout(); row.addWidget(self.every); row.addWidget(self.unit); row.addStretch()
        form.addRow(self.enable)
        form.addRow("Cada:", row)
        form.addRow("Conservar últimos:", self.keep)
        save = QPushButton("Guardar configuración"); save.setObjectName("primary")
        save.clicked.connect(self.save_cfg)
        self.next_lbl = QLabel(); self.next_lbl.setObjectName("muted")
        form.addRow(save, self.next_lbl)
        lay.addWidget(box)

        bar = QHBoxLayout()
        now = QPushButton("💾 Respaldar ahora"); now.setObjectName("primary"); now.clicked.connect(lambda: self.backup("manual"))
        rest = QPushButton("↩ Restaurar seleccionado"); rest.clicked.connect(self.restore)
        dele = QPushButton("🗑 Eliminar"); dele.setObjectName("danger"); dele.clicked.connect(self.delete)
        bar.addWidget(now); bar.addWidget(rest); bar.addWidget(dele); bar.addStretch()
        lay.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Nombre", "Tipo", "Fecha", "Archivos", "Tamaño"])
        self.tree.setAlternatingRowColors(True); self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        lay.addWidget(self.tree, 1)

        self.load_cfg(); self.refresh()
        self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(15000)

    def interval_secs(self):
        return int(self.v.get("interval_value", 1)) * UNITS[int(self.v.get("interval_unit", 0))][1]

    def load_cfg(self):
        self.enable.setChecked(self.v.get("auto_enabled", "0") == "1")
        self.every.setValue(int(self.v.get("interval_value", 60)))
        self.unit.setCurrentIndex(int(self.v.get("interval_unit", 0)))
        self.keep.setValue(int(self.v.get("keep", 20)))
        self.update_next()

    def save_cfg(self):
        self.v.set("auto_enabled", "1" if self.enable.isChecked() else "0")
        self.v.set("interval_value", self.every.value())
        self.v.set("interval_unit", self.unit.currentIndex())
        self.v.set("keep", self.keep.value())
        # El intervalo cuenta desde ahora al activar/cambiar
        self.v.set("last_backup", time.time())
        self.update_next()

    def update_next(self):
        if self.v.get("auto_enabled", "0") == "1":
            nxt = float(self.v.get("last_backup", time.time())) + self.interval_secs()
            self.next_lbl.setText(f"Próximo respaldo: {fmt_time(nxt)}")
        else:
            self.next_lbl.setText("Respaldo automático desactivado")

    def tick(self):
        if self.v.get("auto_enabled", "0") != "1":
            return
        last = float(self.v.get("last_backup", 0) or 0)
        if time.time() - last >= self.interval_secs():
            self.backup("auto")

    def backup(self, kind):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            _sid, skipped = self.v.create_snapshot(kind)
            self.v.apply_retention(int(self.v.get("keep", 20)))
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh(); self.update_next(); self.changed.emit()
        if skipped:
            QMessageBox.warning(self, "Respaldo", "Estos archivos están corruptos y NO se respaldaron:\n\n" + "\n".join(skipped))

    def refresh(self):
        self.tree.clear()
        for s in self.v.snapshots():
            it = QTreeWidgetItem([s["name"], "Automático" if s["kind"] == "auto" else "Manual",
                                  fmt_time(s["created"]), str(s["file_count"]), fmt_size(s["total_size"])])
            it.setData(0, Qt.UserRole, s["id"])
            self.tree.addTopLevelItem(it)

    def current(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    def restore(self):
        sid = self.current()
        if sid and QMessageBox.question(self, "Restaurar", "Se reemplazará TODO el contenido actual del entorno por el del respaldo. ¿Continuar?") == QMessageBox.Yes:
            failed = self.v.restore_snapshot(sid)
            self.changed.emit()
            if failed:
                QMessageBox.warning(self, "Restaurar", "No se pudieron restaurar (copia corrupta):\n" + "\n".join(failed))
            else:
                QMessageBox.information(self, "Restaurar", "Restauración completada.")

    def delete(self):
        sid = self.current()
        if sid and QMessageBox.question(self, "Eliminar respaldo", "¿Eliminar este respaldo?") == QMessageBox.Yes:
            self.v.delete_snapshot(sid); self.refresh(); self.changed.emit()


# ---------------------------------------------------------------- Comparar
class ComparePage(QWidget):
    def __init__(self, vault):
        super().__init__()
        self.setObjectName("page")
        self.v = vault
        self.last = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addLayout(page_title("Comparar y verificar", "Recalcula el SHA-256 real de cada archivo y lo contrasta con el registrado y con el respaldo para detectar corrupción."))
        bar = QHBoxLayout()
        self.combo = QComboBox(); self.combo.setMinimumWidth(320)
        go = QPushButton("🔍 Comparar y generar PDF"); go.setObjectName("primary"); go.clicked.connect(self.run)
        self.open_btn = QPushButton("Abrir último PDF"); self.open_btn.clicked.connect(self.open_pdf); self.open_btn.setEnabled(False)
        bar.addWidget(QLabel("Respaldo:")); bar.addWidget(self.combo); bar.addWidget(go); bar.addWidget(self.open_btn); bar.addStretch()
        lay.addLayout(bar)
        self.summary = QLabel(""); self.summary.setTextFormat(Qt.RichText)
        lay.addWidget(self.summary)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Archivo", "Estado", "Tamaño", "Detalle"])
        self.table.setAlternatingRowColors(True); self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        h = self.table.horizontalHeader(); h.setSectionResizeMode(0, QHeaderView.Stretch); h.setSectionResizeMode(3, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)
        self.reload()

    def reload(self):
        self.combo.clear()
        for s in self.v.snapshots():
            self.combo.addItem(f"{s['name']}  ({s['file_count']} archivos)", s["id"])

    def run(self):
        sid = self.combo.currentData()
        if sid is None:
            QMessageBox.information(self, "Comparar", "Primero crea un respaldo."); return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            results, summ = self.v.compare(sid)
            snap = self.v.snapshot(sid)
            pdf = self.v.reports_dir / f"reporte_{time.strftime('%Y%m%d_%H%M%S')}.pdf"
            build_report(str(pdf), snap, results, summ)
        finally:
            QApplication.restoreOverrideCursor()
        self.last = pdf
        self.open_btn.setEnabled(True)
        self.summary.setText("  ".join(f"<span style='color:{STATUS_COLOR[k]}'><b>{k}: {v}</b></span>" for k, v in summ.items()))
        self.table.setRowCount(len(results))
        for i, r in enumerate(results):
            for c, txt in enumerate([r["path"], r["status"], fmt_size(r["size"]) if r["size"] is not None else "—", r["detail"]]):
                it = QTableWidgetItem(txt)
                if c == 1:
                    it.setForeground(QColor(STATUS_COLOR[r["status"]]))
                self.table.setItem(i, c, it)
        m = QMessageBox(self); m.setWindowTitle("Reporte generado")
        m.setText(f"Reporte PDF guardado en:\n{pdf}")
        b = m.addButton("Abrir PDF", QMessageBox.AcceptRole); m.addButton("Guardar copia…", QMessageBox.ActionRole); m.addButton("Cerrar", QMessageBox.RejectRole)
        m.exec()
        if m.clickedButton() is b:
            self.open_pdf()
        elif m.clickedButton().text() == "Guardar copia…":
            dest, _ = QFileDialog.getSaveFileName(self, "Guardar reporte", pdf.name, "PDF (*.pdf)")
            if dest:
                import shutil; shutil.copy2(pdf, dest)

    def open_pdf(self):
        if self.last:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last)))


# ---------------------------------------------------------------- Ventana
class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VaultGuard")
        self.resize(1200, 760)
        self.v = Vault(ROOT)
        side = QFrame(); side.setObjectName("sidebar"); side.setFixedWidth(210)
        sl = QVBoxLayout(side); sl.setContentsMargins(0, 0, 0, 0); sl.setSpacing(2)
        logo = QLabel("🛡 VaultGuard"); logo.setObjectName("logo"); sl.addWidget(logo)
        self.stack = QStackedWidget()
        self.files = FilesPage(self.v); self.backup = BackupPage(self.v); self.compare = ComparePage(self.v)
        self.btns = []
        for i, (txt, page) in enumerate([("🗂  Archivos", self.files), ("💾  Respaldos", self.backup), ("🔍  Comparar", self.compare)]):
            b = QPushButton(txt); b.setObjectName("nav"); b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self.go(i))
            sl.addWidget(b); self.btns.append(b); self.stack.addWidget(page)
        sl.addStretch()
        info = QLabel(f"Entorno aislado:\n{ROOT}"); info.setObjectName("muted"); info.setWordWrap(True)
        info.setContentsMargins(14, 0, 14, 14); info.setStyleSheet("font-size:10px;")
        sl.addWidget(info)
        central = QWidget(); hl = QHBoxLayout(central); hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(0)
        hl.addWidget(side); hl.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.backup.changed.connect(self.compare.reload)
        self.backup.changed.connect(self.files.refresh)
        self.files.changed.connect(self.compare.reload)
        self.go(0)

    def go(self, i):
        self.stack.setCurrentIndex(i)
        for j, b in enumerate(self.btns):
            b.setChecked(j == i)
        if i == 2:
            self.compare.reload()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    w = Main(); w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
