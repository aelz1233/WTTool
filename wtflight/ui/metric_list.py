"""Metric catalogue tree: sections, search and drag source."""

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import QApplication, QHeaderView, QTreeWidget, QTreeWidgetItem

from wtflight.core.metrics import METRICS, engine_metric_parts, metric_help, metric_label
from wtflight.core.profiles import hud_label
from wtflight.ui.group_view import MIME
from wtflight.ui.theme import THEMES


class MetricList(QTreeWidget):
    metric_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setIndentation(12)
        self.setUniformRowHeights(True)
        self.setExpandsOnDoubleClick(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self.setColumnWidth(1, 28)
        self.setObjectName("metricList")
        self.expanded_sections = {"Полёт"}
        self.populating = False
        self.itemExpanded.connect(self.remember_sections)
        self.itemCollapsed.connect(self.remember_sections)
        self.itemClicked.connect(self.click_item)
        self.itemDoubleClicked.connect(self.double_click_item)

    def remember_sections(self, item):
        if self.populating:
            return
        section = item.data(0, Qt.UserRole + 1)
        if item.isExpanded():
            self.expanded_sections.add(section)
        else:
            self.expanded_sections.discard(section)

    def populate(self, ids, query):
        self.populating = True
        self.clear()
        sections = {}
        theme = THEMES.get(QApplication.instance().property("theme"), THEMES["graphite"])
        english = QApplication.instance().property("language") == "en"
        section_en = {"Полёт": "Flight", "Двигатель": "Engine", "Механизация": "Configuration",
                      "Навигация": "Navigation", "Предупреждения": "Warnings", "Пределы самолёта": "Aircraft limits",
                      "Другие данные": "Other data"}
        label_en = {"ias": "IAS · Indicated", "tas": "TAS · True airspeed", "g": "LDF · G-load",
                    "mach": "MACH · Mach number", "altitude": "ALT · Altitude", "climb": "CLMB · Climb rate",
                    "aoa": "AOA · Angle of attack", "aos": "AOS · Sideslip", "fuel": "FUEL · Fuel",
                    "rpm": "RPM · All engines", "throttle": "THR · All engines", "power": "PWR · All engines",
                    "oil_temp": "OIL · All engines", "water_temp": "WTR · Cooling", "fuel_time": "FUEL · Remaining",
                    "fuel_flow": "FUEL · Flow", "ias_margin": "IAS · Margin", "mach_margin": "MACH · Margin",
                    "g_margin_pos": "G · Positive margin", "g_margin_neg": "G · Negative margin",
                    "limit_ias": "IAS · Limit", "limit_mach": "MACH · Limit", "limit_pos_g": "G · Positive limit",
                    "limit_neg_g": "G · Negative limit", "limit_gear": "GEAR · Limit", "limit_flaps": "FLAPS · Limit"}
        for metric_id in ids:
            label = metric_label(metric_id)
            code = hud_label(metric_id)
            if query and not any(query in text.casefold() for text in (label, metric_id, code)):
                continue
            section = (METRICS[metric_id][0] if metric_id in METRICS else
                       "Топливо и двигатель" if engine_metric_parts(metric_id) else "Другие данные")
            section = {"Топливо и двигатель": "Двигатель", "Конфигурация": "Механизация",
                       "Система": "Предупреждения"}.get(section, section)
            section_display = section_en.get(section, section) if english else section
            if section not in sections:
                parent = QTreeWidgetItem(self, [section_display])
                parent.setData(0, Qt.UserRole + 1, section)
                parent.setFlags(Qt.ItemIsEnabled)
                parent.setFirstColumnSpanned(True)
                parent.setForeground(0, QColor(theme["muted"]))
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                sections[section] = parent
            display = {"ias": "IAS · Приборная", "tas": "TAS · Истинная", "g": "LDF · Перегрузка",
                       "mach": "MACH · Число Маха", "altitude": "ALT · Высота", "climb": "CLMB · Набор",
                       "aoa": "AOA · Угол атаки", "aos": "AOS · Скольжение", "fuel": "FUEL · Топливо",
                       "rpm": "RPM · Все двигатели", "throttle": "THR · Все двигатели", "power": "PWR · Все двигатели",
                       "oil_temp": "OIL · Масло", "water_temp": "WTR · Охлаждение",
                       "fuel_time": "FUEL · Остаток", "fuel_flow": "FUEL · Расход",
                       "ias_margin": "IAS · Запас", "mach_margin": "MACH · Запас",
                       "g_margin_pos": "G · Запас +", "g_margin_neg": "G · Запас −",
                       "limit_ias": "IAS · Предел", "limit_mach": "MACH · Предел",
                       "limit_pos_g": "G · Предел +", "limit_neg_g": "G · Предел −",
                       "limit_gear": "GEAR · Предел", "limit_flaps": "FLAPS · Предел"}.get(metric_id,
                                                                                                  f"{code} · {label}" if engine_metric_parts(metric_id) else label)
            if english:
                display = label_en.get(metric_id, display)
                label = label_en.get(metric_id, label)
            item = QTreeWidgetItem(sections[section], [display, "+"])
            item.setToolTip(0, label)
            item.setData(0, Qt.UserRole, metric_id)
            item.setTextAlignment(1, Qt.AlignCenter)
            item.setForeground(1, QColor(theme["accent"]))
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
            item.setToolTip(0, f"{label}\n\n{metric_help(metric_id)}\n\n" +
                             ("Drag to the layout or an existing group." if english else "Перетащите на макет или на существующую группу."))
            item.setToolTip(1, "Add metric" if english else "Добавить отдельный показатель")
        for section, parent in sections.items():
            parent.setText(0, f"{section}  ·  {parent.childCount()}")
            parent.setExpanded(bool(query) or section in self.expanded_sections)
        self.populating = False
        return sum(p.childCount() for p in sections.values())

    def click_item(self, item, column):
        metric_id = item.data(0, Qt.UserRole)
        if metric_id and column == 1:
            self.metric_requested.emit(metric_id)
        elif not metric_id:
            item.setExpanded(not item.isExpanded())

    def double_click_item(self, item, column):
        metric_id = item.data(0, Qt.UserRole)
        if metric_id and column == 0:
            self.metric_requested.emit(metric_id)

    def keyPressEvent(self, event):
        item = self.currentItem()
        if item and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            metric_id = item.data(0, Qt.UserRole)
            if metric_id:
                self.metric_requested.emit(metric_id)
                return
        super().keyPressEvent(event)

    def startDrag(self, _actions):
        item = self.currentItem()
        if not item:
            return
        metric_id = item.data(0, Qt.UserRole)
        if not metric_id:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME, str(metric_id).encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)
