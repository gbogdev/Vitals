import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow
    from .ui.widgets import DARK_QSS

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)
    from .ui.icon import make_icon
    app.setWindowIcon(make_icon())
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
