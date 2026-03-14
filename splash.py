
import sys
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtGui import QPainter, QPainterPath, QPixmap, QPen
from PyQt6.QtCore import Qt, QPropertyAnimation, pyqtProperty, QTimer


class SplashScreen(QWidget):

    def __init__(self):
        super().__init__()

        self.pixmap = QPixmap("assets/logo.png")

        self.opacity = 0.0

        self.resize(400, 400)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        # animation fade-in
        self.anim = QPropertyAnimation (self, b"windowOpacity")
        self.anim.setDuration(2000)
        self.anim.setStartValue(0)
        self.anim.setEndValue(1)
        self.anim.start()

        # durée affichage
        QTimer.singleShot(4000, self.close)

    def paintEvent(self, event):

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        size = min(self.width(), self.height())
        margin = 10

        path = QPainterPath()
        path.addEllipse(margin, margin, size - margin*2, size - margin*2)

        painter.setClipPath(path)

        scaled = self.pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )

        painter.drawPixmap(self.rect(), scaled)

        painter.setClipping(False)

        pen = QPen(Qt.GlobalColor.white)
        pen.setWidth(2)

        painter.setPen(pen)
        painter.drawEllipse(margin, margin, size - margin*2, size - margin*2)


if __name__ == "__main__":

    app = QApplication(sys.argv)

    splash = SplashScreen()
    splash.show()

    sys.exit(app.exec())