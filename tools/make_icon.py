"""Create the application icon using the same mark as the tray."""
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication([])
image = QPixmap(256, 256)
image.fill(Qt.transparent)
p = QPainter(image)
p.setRenderHint(QPainter.Antialiasing)
p.setBrush(QColor('#8fbca5'))
p.setPen(Qt.NoPen)
p.drawRoundedRect(8, 8, 240, 240, 54, 54)
p.setPen(QColor('#14241c'))
p.setFont(QFont('Segoe UI', 100, QFont.Bold))
p.drawText(QRect(0, 0, 256, 250), Qt.AlignCenter, 'W')
p.end()
assert image.save(str(Path(__file__).resolve().parents[1] / 'wtflight' / 'resources' / 'wt-flight.ico'))
