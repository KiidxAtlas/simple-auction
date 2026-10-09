import logging
import sys
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
from PySide6.QtWidgets import QApplication, QMessageBox

from simple_auction.constants import APP_NAME
from simple_auction.services.config import CONFIG_PATH, Config
from simple_auction.ui import strings, theme
from simple_auction.ui.main_page import MainPage

LOG_PATH = CONFIG_PATH.parent / "simple-auction.log"

log = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Log to the terminal and to a file (the installed app has no terminal)."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
            )
        )
    except OSError:
        pass  # logging to a file is a convenience; the app still runs
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def _report_unexpected_error(exc_type, exc, tb) -> None:
    """Show errors that would otherwise vanish (a button that does nothing)."""
    log.error("Unexpected error", exc_info=(exc_type, exc, tb))
    if QApplication.instance() is not None:
        QMessageBox.critical(
            None,
            strings.ERROR_TITLE,
            strings.ERROR_BODY.format(
                error=f"{exc_type.__name__}: {exc}", log=LOG_PATH
            ),
        )


def main() -> int:
    load_dotenv()  # API keys from .env in the project folder
    _setup_logging()
    sys.excepthook = _report_unexpected_error
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
