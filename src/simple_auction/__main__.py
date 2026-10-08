import logging
import sys

from dotenv import load_dotenv
from PySide6.QtWidgets import QApplication

from simple_auction.constants import APP_NAME
from simple_auction.services.config import Config
from simple_auction.ui import theme
from simple_auction.ui.main_page import MainPage


def main() -> int:
    load_dotenv()  # API keys from .env in the project folder
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    theme.apply(app)
    app.styleHints().colorSchemeChanged.connect(lambda _: theme.apply(app))

    config = Config.load()
    config.move_old_files()  # older versions kept everything in one folder
    window = MainPage(config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
