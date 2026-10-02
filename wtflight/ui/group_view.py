"""Painted HUD text block: shared by the editor preview and the in-game overlay."""

import time
from html import escape

from PySide6.QtCore import QPoint, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from wtflight.core.alerts import metric_risk, warning_for
from wtflight.core.metrics import (available_metrics, expand_engine_metric, metric_help,
                                   metric_label, metric_value, number)
from wtflight.core.profiles import hud_label
from wtflight.ui.theme import INK, MUTED, ORANGE, RED, TEAL

# Drag-and-drop payload carrying a metric id from the catalogue.
MIME = "application/x-wt-metric"


def alert_level(tone, caution_ratio=.9):
    """Normalize row state for the warning animation."""
    if tone == "critical" or (isinstance(tone, (float, int)) and tone >= 1):
        return "critical"
    if tone == "caution" or (isinstance(tone, (float, int)) and tone >= caution_ratio):
        return "caution"
    return ""


def flashing_alert_color(level, normal, now=None):
    """Alternate an alerted HUD row between its normal colour and yellow/red."""
    if not level:
        return QColor(normal)
    now = time.monotonic() if now is None else now
    if int(now * 5) % 2:
        return QColor(RED if level == "critical" else ORANGE)
    return QColor(normal)


class GroupView(QWidget):
    selected = Signal(str)
    moved = Signal()
    added = Signal(str, str)

    def __init__(self, group, editor, parent=None):
        super().__init__(parent)
        self.group = group
        self.editor = editor
        self.sample = ("offline", {}, {})
        self.limits = {}
        self.is_selected = False
        self.press = None
        self.hover_pos = QPoint()
        self.setMouseTracking(True)
        self.tooltip_timer = QTimer(self)
        self.tooltip_timer.setSingleShot(True)
        self.tooltip_timer.setInterval(550)
        self.tooltip_timer.timeout.connect(self.show_metric_tooltip)
        self.flash_timer = QTimer(self)
        self.flash_timer.setInterval(100)
        self.flash_timer.timeout.connect(self.update)
        self.flash_timer.start()
        # A popup parented to an embedded GroupView is automatically embedded by
        # QGraphicsProxyWidget too. Keep it outside the scene, in screen coordinates.
        self.metric_tip = QLabel(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                                Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput |
                                Qt.BypassGraphicsProxyWidget)
        self.destroyed.connect(self.metric_tip.deleteLater)
        self.metric_tip.setObjectName("metricDescriptionTip")
        self.metric_tip.setWordWrap(True)
        self.metric_tip.setTextFormat(Qt.RichText)
        self.metric_tip.setFixedWidth(340)
        tip_font = QFont(QApplication.font())
        tip_font.setPixelSize(15)
        self.metric_tip.setFont(tip_font)
        self.metric_tip.setAttribute(Qt.WA_ShowWithoutActivating)
        self.metric_tip.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.metric_tip.setStyleSheet(
            "QLabel#metricDescriptionTip { color: #f1f5f9; background: #111a20; "
            "font-family: 'Segoe UI'; font-size: 15px; border: 1px solid #64808b; border-radius: 7px; "
            "padding: 10px 12px; }"
        )
        self.metric_tip.hide()
        self.setAttribute(Qt.WA_TranslucentBackground)
        if editor:
            self.setAcceptDrops(True)
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.adjustSize()

    def lines(self):
        mode, state, indicators = self.sample
        active = mode in ("live", "demo")
        available = set(available_metrics(state, indicators, self.limits)) if active else None
        lines = []
        if self.group.get("title_visible"):
            lines.append((self.group.get("title", "БЛОК"), "", "title", "__title__"))
        for configured_metric in self.group.get("metrics", []):
            metric_ids = expand_engine_metric(configured_metric, state) if active else [configured_metric]
            for metric_id in metric_ids:
                if active and metric_id not in available:
                    continue
                if metric_id == "warning":
                    severity, warning = warning_for(self.sample, self.limits)
                    value = warning if active else "ОЖИДАНИЕ БОЯ"
                    if not value or severity in ("normal", "unset"):
                        continue
                    lines.append(("", value, severity or "unset", "warning"))
                else:
                    value = metric_value(metric_id, state, indicators, self.limits) if active else "—"
                    label_map = self.group.get("label_map", {})
                    label = (label_map.get(metric_id, label_map.get(configured_metric, hud_label(metric_id)))
                             if self.group.get("compact_labels", True) else metric_label(metric_id))
                    label = label.upper() if self.group.get("labels", True) else ""
                    risk = metric_risk(metric_id, state, self.limits, state.get("_fuel_minutes", 3)) if active else None
                    lines.append((label, value, risk if risk is not None else "normal", metric_id))
        return lines

    def hud_font(self):
        font = QFont(self.group.get("font_family", "Consolas"))
        font.setPixelSize(int(self.group.get("size", 18)))
        font.setBold(self.group.get("bold", True))
        return font

    def sizeHint(self):
        fm = QFontMetrics(self.hud_font())
        rows = self.lines() or [("", "—", "normal", "__empty__")]
        gap = fm.horizontalAdvance(" ")
        label_width = max(fm.horizontalAdvance(a) for a, _, _, _ in rows)
        width = label_width + gap + max(fm.horizontalAdvance(b) for _, b, _, _ in rows)
        pad = 10 if self.group.get("style") == "panel" else 3
        spacing = int(self.group.get("spacing", 1))
        return QSize(max(40, width + pad * 2), max(20, len(rows) * (fm.height() + spacing) + pad * 2))

    def set_sample(self, sample, limits):
        self.sample = sample
        self.limits = limits
        self.adjustSize()
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        g = self.group
        painter.setFont(self.hud_font())
        fm = painter.fontMetrics()
        panel = g.get("style") == "panel"
        if panel:
            painter.setBrush(QColor(14, 23, 39, 220))
            painter.setPen(QPen(QColor("#36506b"), 1))
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 5, 5)
        if self.editor and self.is_selected:
            pen = QPen(QColor(TEAL), 1.5, Qt.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 10, 10)
        x = 10 if panel else 3
        y = x + fm.ascent()
        gap = fm.horizontalAdvance(" ")
        lines = self.lines() or [("", "—", "normal", "__empty__")]
        label_width = max((fm.horizontalAdvance(a) for a, _, _, _ in lines), default=0)
        for label, value, tone, _metric_id in lines:
            level = alert_level(tone, number(self.sample[1].get("_warning_ratio")) or .9)
            tone_color = RED if tone == "critical" else ORANGE if tone == "caution" else g.get("color", INK)
            critical_row, caution_row = level == "critical", level == "caution"
            if not level and isinstance(tone, (float, int)) and tone > .75:
                start = QColor(g.get("color", INK)) if tone < .9 else QColor(ORANGE)
                end = QColor(ORANGE if tone < .9 else RED)
                blend = min(1, max(0, (tone - .75) / .15 if tone < .9 else (tone - .9) / .1))
                tone_color = QColor(round(start.red() + (end.red() - start.red()) * blend),
                                    round(start.green() + (end.green() - start.green()) * blend),
                                    round(start.blue() + (end.blue() - start.blue()) * blend))
            if tone in ("title", "unset"):
                tone_color = g.get("accent", TEAL) if tone == "title" else MUTED
            label_color = RED if critical_row else ORANGE if caution_row else g.get("accent", TEAL)
            if level:
                tone_color = flashing_alert_color(level, g.get("color", INK))
                label_color = flashing_alert_color(level, g.get("accent", TEAL))
            if g.get("shadow", True):
                painter.setPen(QColor(4, 12, 25, 190))
                painter.drawText(x + 1, y + 1, label)
                painter.drawText(x + label_width + (gap if label and value else 0) + 1, y + 1, value)
            def draw_hud_text(text, left, fill):
                if not text:
                    return
                outline = g.get("outline", True)
                path = QPainterPath()
                path.addText(float(left), float(y), painter.font(), text)
                if outline:
                    pen = QPen(QColor(g.get("outline_color", "#07140f")),
                               float(g.get("outline_width", 1.4)), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                    painter.strokePath(path, pen)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(fill))
                painter.drawPath(path)
                painter.setBrush(Qt.NoBrush)
            draw_hud_text(label, x, label_color)
            draw_hud_text(value, x + label_width + (gap if label and value else 0), tone_color)
            y += fm.height() + int(g.get("spacing", 1))
        painter.end()

    def mousePressEvent(self, event):
        if self.editor and event.button() == Qt.LeftButton:
            self.tooltip_timer.stop()
            self.metric_tip.hide()
            if hasattr(self, "canvas"):
                self.canvas.setFocus(Qt.MouseFocusReason)
                if event.modifiers() & Qt.ControlModifier:
                    selected = set(self.canvas.selected_ids)
                    if self.group["id"] in selected:
                        selected.remove(self.group["id"])
                    else:
                        selected.add(self.group["id"])
                    primary = self.group["id"] if self.group["id"] in selected else None
                    self.canvas.set_selection(selected, primary)
                elif self.group["id"] not in self.canvas.selected_ids:
                    self.canvas.set_selection({self.group["id"]}, self.group["id"])
            selected_id = (self.canvas.selected_id if hasattr(self, "canvas") and
                           event.modifiers() & Qt.ControlModifier else self.group["id"])
            self.selected.emit(selected_id or "")
            if hasattr(self, "canvas") and self.group["id"] not in self.canvas.selected_ids:
                self.press = None
                return
            self.press = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.editor and self.press is not None and event.buttons() & Qt.LeftButton:
            self.tooltip_timer.stop()
            self.metric_tip.hide()
            pos = self.pos() + event.position().toPoint() - self.press
            self.canvas.move_selected_by(self, pos.x(), pos.y())
        else:
            self.hover_pos = event.position().toPoint()
            if self.rect().contains(self.hover_pos):
                self.tooltip_timer.start()

    def show_metric_tooltip(self):
        if not self.isVisible() or (hasattr(self, "canvas") and not self.canvas.isVisible()):
            return
        if not self.rect().contains(self.hover_pos):
            return
        g = self.group
        pad = 10 if g.get("style") == "panel" else 3
        fm = QFontMetrics(self.hud_font())
        row_height = fm.height() + int(g.get("spacing", 1))
        row_index = (self.hover_pos.y() - pad) // max(1, row_height)
        lines = self.lines()
        if row_index < 0 or row_index >= len(lines):
            self.metric_tip.hide()
            return
        label, value, _tone, metric_id = lines[row_index]
        if metric_id == "__title__":
            self.metric_tip.hide()
            return
        title = metric_label(metric_id)
        if metric_id == "warning":
            title = "Предупреждения"
        detail = metric_help(metric_id)
        current = f"<br>Сейчас: {escape(value)}" if value and value != "—" else ""
        text = f"<b>{escape(title)}</b>{current}<br><br>{escape(detail)}"
        # A regular QToolTip disappears after a short platform timeout. Use a small,
        # non-interactive tool window and keep it visible for the entire hover instead.
        self.metric_tip.setText(text)
        self.metric_tip.setFixedHeight(self.metric_tip.heightForWidth(self.metric_tip.width()))
        row_y = pad + row_index * row_height + fm.height() // 2
        proxy = self.graphicsProxyWidget() if self.editor and hasattr(self, "canvas") else None
        if proxy is not None:
            scene_anchor = proxy.mapToScene(QPointF(self.width(), row_y))
            viewport_anchor = self.canvas.mapFromScene(scene_anchor)
            anchor = self.canvas.viewport().mapToGlobal(viewport_anchor)
            left_anchor = self.canvas.viewport().mapToGlobal(
                self.canvas.mapFromScene(proxy.mapToScene(QPointF(0, row_y))))
        else:
            anchor = self.mapToGlobal(QPoint(self.width(), row_y))
            left_anchor = self.mapToGlobal(QPoint(0, row_y))
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        x, y = anchor.x() + 12, anchor.y() - self.metric_tip.height() // 2
        if x + self.metric_tip.width() > bounds.right() + 1:
            x = left_anchor.x() - self.metric_tip.width() - 12
        x = max(bounds.left(), min(x, bounds.right() + 1 - self.metric_tip.width()))
        y = max(bounds.top(), min(y, bounds.bottom() + 1 - self.metric_tip.height()))
        self.metric_tip.move(max(bounds.left(), x), max(bounds.top(), y))
        self.metric_tip.show()

    def leaveEvent(self, event):
        self.tooltip_timer.stop()
        self.metric_tip.hide()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.tooltip_timer.stop()
        self.metric_tip.hide()
        super().hideEvent(event)

    def mouseReleaseEvent(self, _event):
        if self.editor and self.press is not None:
            self.press = None
            self.setCursor(Qt.OpenHandCursor)
            self.moved.emit()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        elif event.mimeData().hasUrls() and hasattr(self.parentWidget(), "image_dropped"):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls() and hasattr(self.parentWidget(), "image_dropped"):
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    self.parentWidget().image_dropped.emit(url.toLocalFile())
                    event.acceptProposedAction()
                    return
            return
        metric_id = bytes(event.mimeData().data(MIME)).decode("utf-8")
        self.added.emit(self.group["id"], metric_id)
        event.acceptProposedAction()
