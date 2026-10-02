"""Screen-sized scene: the same logical coordinates and fonts as the real HUD."""
from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView, QRubberBand


class FlightCanvas(QGraphicsView):
    group_selected = Signal(str)
    group_added = Signal(str, str)
    group_created = Signal(str, float, float)
    group_moved = Signal()
    image_dropped = Signal(str)
    selection_changed = Signal(object)

    def __init__(self, view_factory, mime):
        super().__init__()
        self.view_factory, self.mime = view_factory, mime
        self.virtual_size = QApplication.primaryScreen().geometry().size()
        self.zoom = 0
        self.snap_enabled = True
        self.views, self.groups = [], []
        self.sample = ("offline", {}, {})
        self.limits = {}
        self.selected_id = None
        self.selected_ids = set()
        self.rubber_band = QRubberBand(QRubberBand.Rectangle, self.viewport())
        self.selection_origin = None
        self.background = QPixmap()
        self.background_cache = QPixmap()
        self.dimming, self.show_grid = 15, False
        self.setScene(QGraphicsScene(self))
        self.setSceneRect(QRectF(0, 0, self.virtual_size.width(), self.virtual_size.height()))
        self.setMinimumSize(260, 120)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAcceptDrops(True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setStyleSheet("QGraphicsView { border: 1px solid #31433b; background: #080d0e; }")

    def set_screen_size(self, size):
        self.virtual_size = QSize(size)
        self.setSceneRect(QRectF(0, 0, size.width(), size.height()))
        self.cache_background()
        self.position_views()
        self.apply_zoom()

    def apply_zoom(self):
        for view in self.views:
            view.tooltip_timer.stop()
            view.metric_tip.hide()
        self.resetTransform()
        if self.zoom:
            self.scale(self.zoom, self.zoom)
        else:
            self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)
        self.viewport().update()

    def set_zoom(self, value):
        self.zoom = value
        self.apply_zoom()

    def set_background(self, pixmap):
        self.background = pixmap
        self.cache_background()
        self.viewport().update()

    def cache_background(self):
        self.background_cache = (self.background.scaled(self.virtual_size, Qt.KeepAspectRatioByExpanding,
                                                        Qt.SmoothTransformation)
                                 if not self.background.isNull() else QPixmap())

    def set_groups(self, groups):
        for view in self.views:
            proxy = view.graphicsProxyWidget()
            if proxy:
                self.scene().removeItem(proxy)
                proxy.setWidget(None)
                proxy.deleteLater()
            view.hide()
            view.deleteLater()
        self.views = []
        self.groups = groups
        valid_ids = {group["id"] for group in groups}
        self.selected_ids.intersection_update(valid_ids)
        if self.selected_id not in valid_ids:
            self.selected_id = None
        for group in groups:
            view = self.view_factory(group, True)
            view.canvas = self
            view.selected.connect(self.group_selected)
            view.added.connect(self.group_added)
            view.moved.connect(self.group_moved)
            view.set_sample(self.sample, self.limits)
            view.is_selected = group["id"] in self.selected_ids or group["id"] == self.selected_id
            self.scene().addWidget(view)
            view.show()
            self.views.append(view)
        self.position_views()

    def position_views(self):
        for view in self.views:
            view.adjustSize()
            view.move(round(min(max(0, self.virtual_size.width() - view.width()), view.group.get("x", 0) * self.virtual_size.width())),
                      round(min(max(0, self.virtual_size.height() - view.height()), view.group.get("y", 0) * self.virtual_size.height())))

    def set_sample(self, sample, limits):
        self.sample, self.limits = sample, limits
        for view in self.views:
            view.set_sample(sample, limits)
        self.position_views()

    def select(self, group_id):
        self.selected_id = group_id
        self.selected_ids = {group_id} if group_id else set()
        for view in self.views:
            view.is_selected = view.group["id"] in self.selected_ids
            view.update()

    def set_selection(self, group_ids, primary=None):
        valid = {view.group["id"] for view in self.views}
        self.selected_ids = set(group_ids) & valid
        if primary in self.selected_ids:
            self.selected_id = primary
        elif self.selected_ids:
            self.selected_id = next(view.group["id"] for view in self.views
                                     if view.group["id"] in self.selected_ids)
        else:
            self.selected_id = None
        for view in self.views:
            view.is_selected = view.group["id"] in self.selected_ids
            view.update()
        self.selection_changed.emit(set(self.selected_ids))

    def move_selected_by(self, active_view, x, y, snap=True):
        selected = [view for view in self.views if view.group["id"] in self.selected_ids]
        if active_view not in selected:
            selected = [active_view]
        target_x, target_y = self.snap_position(active_view, x, y, set(selected)) if snap else (x, y)
        dx, dy = target_x - active_view.x(), target_y - active_view.y()
        if not (dx or dy):
            return
        width, height = self.virtual_size.width(), self.virtual_size.height()
        # Clamp the whole selection, keeping the distances between groups intact.
        dx = max(-min(v.x() for v in selected),
                 min(dx, width - max(v.x() + v.width() for v in selected)))
        dy = max(-min(v.y() for v in selected),
                 min(dy, height - max(v.y() + v.height() for v in selected)))
        for view in selected:
            nx, ny = view.x() + dx, view.y() + dy
            view.move(nx, ny)
            view.group["x"], view.group["y"] = nx / width, ny / height

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.itemAt(event.position().toPoint()) is None:
            self.selection_origin = event.position().toPoint()
            self.rubber_band.setGeometry(QRect(self.selection_origin, QSize()))
            self.rubber_band.show()
            if not event.modifiers() & Qt.ControlModifier:
                self.set_selection(set())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.selection_origin is not None:
            rect = QRect(self.selection_origin, event.position().toPoint()).normalized()
            self.rubber_band.setGeometry(rect)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.selection_origin is not None:
            rect = QRect(self.selection_origin, event.position().toPoint()).normalized()
            scene_rect = QRectF(self.mapToScene(rect.topLeft()), self.mapToScene(rect.bottomRight())).normalized()
            found = {view.group["id"] for view in self.views
                     if view.graphicsProxyWidget().sceneBoundingRect().intersects(scene_rect)}
            if event.modifiers() & Qt.ControlModifier:
                found |= self.selected_ids
            self.rubber_band.hide()
            self.selection_origin = None
            self.set_selection(found)
            self.group_selected.emit(self.selected_id or "")
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def snap_position(self, view, x, y, exclude=None):
        width, height = self.virtual_size.width(), self.virtual_size.height()
        x, y = max(0, min(width - view.width(), x)), max(0, min(height - view.height(), y))
        if self.snap_enabled:
            xs = [0, width - view.width(), (width - view.width()) / 2]
            ys = [0, height - view.height(), (height - view.height()) / 2]
            for other in self.views:
                if other != view and other not in (exclude or set()):
                    xs.extend([other.x(), other.x() + other.width() - view.width()])
                    ys.extend([other.y(), other.y() + other.height() - view.height()])
            x = min(xs, key=lambda v: abs(v - x)) if min(abs(v - x) for v in xs) <= 8 else x
            y = min(ys, key=lambda v: abs(v - y)) if min(abs(v - y) for v in ys) <= 8 else y
        return round(max(0, min(width - view.width(), x))), round(max(0, min(height - view.height(), y)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.apply_zoom()

    def hideEvent(self, event):
        for view in self.views:
            view.tooltip_timer.stop()
            view.metric_tip.hide()
        super().hideEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(self.mime) or event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(self.mime) or event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    self.image_dropped.emit(url.toLocalFile())
                    event.acceptProposedAction()
                    return
            return
        if not event.mimeData().hasFormat(self.mime):
            return
        metric = bytes(event.mimeData().data(self.mime)).decode("utf-8")
        point = self.mapToScene(event.position().toPoint())
        if not self.sceneRect().contains(point):
            return
        for view in reversed(self.views):
            if view.graphicsProxyWidget().sceneBoundingRect().contains(point):
                self.group_added.emit(view.group["id"], metric)
                event.acceptProposedAction()
                return
        self.group_created.emit(metric, point.x() / self.virtual_size.width(), point.y() / self.virtual_size.height())
        event.acceptProposedAction()

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor("#080d0e"))
        screen = self.sceneRect()
        painter.fillRect(screen, QColor("#111819"))
        if not self.background_cache.isNull():
            painter.save()
            painter.setClipRect(screen)
            painter.drawPixmap(round((screen.width() - self.background_cache.width()) / 2),
                               round((screen.height() - self.background_cache.height()) / 2), self.background_cache)
            painter.fillRect(screen, QColor(0, 0, 0, round(255 * self.dimming / 100)))
            painter.restore()
        if self.show_grid:
            pen = QPen(QColor(130, 160, 150, 45))
            pen.setCosmetic(True)
            painter.setPen(pen)
            for x in range(0, self.virtual_size.width(), 100):
                painter.drawLine(x, 0, x, self.virtual_size.height())
            for y in range(0, self.virtual_size.height(), 100):
                painter.drawLine(0, y, self.virtual_size.width(), y)
        if self.background.isNull():
            painter.setPen(QColor("#65746e"))
            font = QFont("Segoe UI")
            font.setPixelSize(round(11 / max(.1, self.transform().m11())))
            painter.setFont(font)
            english = QApplication.instance().property("language") == "en"
            painter.drawText(screen, Qt.AlignCenter,
                             "Exact screen layout\nBackground → battle screenshot" if english else
                             "Точный макет экрана\nФон → скриншот боя")
