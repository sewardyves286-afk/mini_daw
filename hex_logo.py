import sys
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtGui  import QPainter, QPainterPath, QPixmap, QPen
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

class LogoWindow(QWidget):

    def __init__(self):
        super().__init__()

        self.pixmap = QPixmap("assets/logo.png")

        self.setWindowTitle("mini_daw")
        self.resize(400, 400)

        # fond transparent
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # fenêtre sans bordure
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

    def paintEvent(self, event):

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        size = min(self.width(), self.height())

        margin = 5  # espace pour le contour

        # cercle
        path = QPainterPath()
        path.addEllipse(margin, margin, size - margin*2, size - margin*2)

        # découpe circulaire
        painter.setClipPath(path)

        scaled = self.pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )

        painter.drawPixmap(self.rect(), scaled)

        # enlever le clip pour dessiner le contour
        painter.setClipping(False)

        # 🎨 contour raffiné
        pen = QPen()
        pen.setWidth(1)              # épaisseur fine
        pen.setColor(QColor(255,255,255,120))
        painter.setPen(pen)

        painter.drawEllipse(margin, margin, size - margin*2, size - margin*2)


if __name__ == "__main__":

    app = QApplication(sys.argv)

    window = LogoWindow()
    window.show()

    sys.exit(app.exec())