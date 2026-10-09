import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from simple_auction.constants import APP_NAME
from simple_auction.services.config import CONFIG_PATH, Config, ConfigFileError
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


def _use_system_certificates() -> None:
    """Check HTTPS certificates the way Windows/macOS (and browsers) do.

    Python 3.13+ is stricter than the OS about some certificates, notably the
    ones antivirus "web shields" add, which made every connection to GitHub
    (updates) and Gemini (research) fail on such PCs.
    """
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:  # the app still works with Python's own checks
        log.warning("Couldn't switch to system certificate checking", exc_info=True)


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


def _load_config(path: Path = CONFIG_PATH) -> Config | None:
    """Recover only with consent; never silently point at an empty catalogue."""
    while True:
        try:
            return Config.load(path)
        except ConfigFileError as e:
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(strings.CONFIG_RECOVERY_TITLE)
            box.setText(strings.CONFIG_RECOVERY_BODY.format(error=e))
            retry = box.addButton(QMessageBox.StandardButton.Retry)
            restore = box.addButton(
                strings.CONFIG_RESTORE, QMessageBox.ButtonRole.ActionRole
            )
            restore.setEnabled(path.with_suffix(".json.bak").exists())
            reset = box.addButton(
                strings.CONFIG_RESET, QMessageBox.ButtonRole.ActionRole
            )
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() is retry:
                continue
            try:
                if box.clickedButton() is restore:
                    return Config.recover(path)
                if box.clickedButton() is reset:
                    base = QFileDialog.getExistingDirectory(
                        None, strings.CONFIG_PICK_BASE
                    )
                    if not base:
                        return None
                    photos = QFileDialog.getExistingDirectory(
                        None, strings.CONFIG_PICK_PHOTOS, base
                    )
                    if not photos:
                        return None
                    return Config.recover(
                        path, Config(base_dir=Path(base), photos_dir=Path(photos))
                    )
            except (ValueError, TypeError, OSError) as recovery_error:
                QMessageBox.critical(
                    None, strings.CONFIG_RECOVERY_TITLE, str(recovery_error)
                )
                continue
            return None


def main() -> int:
    load_dotenv()  # API keys from .env in the project folder
    _setup_logging()
    _use_system_certificates()
    sys.excepthook = _report_unexpected_error
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    theme.apply(app)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    instance_lock = QLockFile(str(CONFIG_PATH.with_suffix(".lock")))
    instance_lock.setStaleLockTime(0)
    if not instance_lock.tryLock(0):
        QMessageBox.warning(None, strings.ERROR_TITLE, strings.ALREADY_RUNNING)
        return 1

    config = _load_config()
    if config is None:
        return 1
    theme.apply(app, dark_mode=config.dark_mode)
    app.styleHints().colorSchemeChanged.connect(
        lambda _: theme.apply(app, dark_mode=config.dark_mode)
    )
    config.move_old_files()  # older versions kept everything in one folder
    window = MainPage(config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
