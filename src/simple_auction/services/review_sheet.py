"""Read-only consignor review PDFs, using Qt's existing text/PDF support."""

import html
import os
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSize, Qt, QUrl
from PySide6.QtGui import (
    QFont,
    QGuiApplication,
    QImageReader,
    QPageLayout,
    QPageSize,
    QPdfWriter,
    QTextDocument,
)

from simple_auction.models import Lot


class ReviewSheetError(ValueError):
    pass


def owners(lots: list[Lot]) -> list[str]:
    """Owner labels are exact saved values, including the unassigned empty label."""
    return sorted(
        {lot.owner for lot in lots}, key=lambda value: (value.casefold(), value)
    )


def grouped_lots(
    lots: list[Lot], owner: str | None = None
) -> list[tuple[str, list[Lot]]]:
    groups = defaultdict(list)
    for lot in lots:
        if owner is None or lot.owner == owner:
            groups[lot.owner].append(lot)
    return [
        (name, sorted(groups[name], key=lambda lot: lot.lot_number))
        for name in owners(lots)
        if name in groups
    ]


def _text(value) -> str:
    return html.escape(str(value if value is not None else "")).replace("\n", "<br>")


def unresolved_questions(lot: Lot) -> list[str]:
    """Research packet questions without a recorded answer need consignor review."""
    dossier = getattr(lot, "dossier", {})
    if not isinstance(dossier, dict):
        return []
    research = dossier.get("research", [])
    if not isinstance(research, list):
        return []
    return [
        record["question"]
        for record in research
        if isinstance(record, dict)
        and isinstance(record.get("question"), str)
        and record["question"].strip()
        and not str(record.get("answer", "")).strip()
    ]


def build_document(
    auction_no: int,
    lots: list[Lot],
    *,
    owner: str | None = None,
    screen_font: QFont | None = None,
) -> QTextDocument:
    """Build an escaped document with embedded local image resources (no network URLs)."""
    if QGuiApplication.instance() is None:
        raise ReviewSheetError("PDF export requires the running Qt application.")
    groups = grouped_lots(lots, owner)
    if not groups:
        raise ReviewSheetError("There are no lots for this owner selection.")
    document = QTextDocument()
    if screen_font is None:
        type_style = "body {font-family: sans-serif; font-size: 10pt;} h1 {font-size: 18pt;} h2 {font-size: 14pt;}"
    else:
        document.setDefaultFont(screen_font)
        family = screen_font.family().replace('"', '\\"')
        size = screen_font.pixelSize() if screen_font.pixelSize() > 0 else 13
        type_style = f'body {{font-family: "{family}";font-size:{size}px;}} h1 {{font-size:{round(size * 1.7)}px;}} h2 {{font-size:{round(size * 1.3)}px;}}'
    document.setDefaultStyleSheet(
        type_style + " td {padding: 4px;} .note {color: #555;}"
    )
    pages = []
    image_number = 0
    for name, items in groups:
        for lot in items:
            sections = [
                f"<h1>Auction {_text(auction_no)} — Consignor review</h1>",
                f"<p><b>Owner:</b> {_text(name or 'Unassigned')}</p>",
                f"<h2>Lot {_text(lot.lot_number)}: {_text(lot.title or 'Untitled')}</h2>",
                '<p class="note">Draft for review — please confirm details or note corrections below.</p>',
                "<p>"
                + " &nbsp; | &nbsp; ".join(
                    f"<b>{label}:</b> {_text(value)}"
                    for label, value in (
                        ("Serial", lot.serial),
                        ("Condition", lot.condition),
                        ("Year", lot.year),
                        ("Make", lot.make),
                        ("Model", lot.model),
                        ("Caliber", lot.caliber),
                    )
                    if value not in ("", None)
                )
                + "</p>",
                f"<h3>Description</h3><p>{_text(lot.desc) or 'No description recorded.'}</p>",
            ]
            pictures = []
            for path in lot.photos:
                reader = QImageReader(str(path))
                size = reader.size()
                if not size.isValid() or size.width() * size.height() > 100_000_000:
                    pictures.append(
                        '<p class="note">Photo unavailable or too large.</p>'
                    )
                    continue
                reader.setAutoTransform(True)
                reader.setScaledSize(
                    size.scaled(QSize(800, 600), Qt.AspectRatioMode.KeepAspectRatio)
                )
                image = reader.read()
                if image.isNull():
                    pictures.append('<p class="note">Photo unavailable.</p>')
                    continue
                image_number += 1
                url = QUrl(f"review-image:{image_number}")
                document.addResource(
                    QTextDocument.ResourceType.ImageResource, url, image
                )
                display = image.size().scaled(
                    QSize(230, 175), Qt.AspectRatioMode.KeepAspectRatio
                )
                pictures.append(
                    f'<img src="{url.toString()}" width="{display.width()}" height="{display.height()}">'
                )
            if pictures:
                rows = [
                    "<tr>"
                    + "".join(f"<td>{picture}</td>" for picture in pictures[i : i + 2])
                    + "</tr>"
                    for i in range(0, len(pictures), 2)
                ]
                sections.append("<h3>Photos</h3><table>" + "".join(rows) + "</table>")
            questions = unresolved_questions(lot)
            sections.append("<h3>Unresolved questions</h3>")
            sections.append(
                "<ul>" + "".join(f"<li>{_text(q)}</li>" for q in questions) + "</ul>"
                if questions
                else "<p>No unresolved questions recorded.</p>"
            )
            sections.append(
                "<h3>Consignor corrections / approval</h3><p>____________________________________________________________</p><p>____________________________________________________________</p><p>Approved by: __________________________ &nbsp; Date: ______________</p>"
            )
            pages.append("".join(sections))
    document.setHtml(
        "<html><body>"
        + '<div style="page-break-before: always;"></div>'.join(pages)
        + "</body></html>"
    )
    return document


def export_pdf(
    auction_no: int, lots: list[Lot], destination: Path, *, owner: str | None = None
) -> Path:
    """Write a new PDF; failures never replace an existing review sheet."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ReviewSheetError(
            "Choose a new PDF filename; existing files are not replaced."
        )
    document = build_document(auction_no, lots, owner=owner)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=".review-sheet-", suffix=".pdf", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(name)
    try:
        writer = QPdfWriter(str(temporary))
        writer.setTitle(f"Auction {auction_no} — Consignor review")
        writer.setCreator("Simple Auction")
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
        writer.setResolution(144)
        document.print_(writer)
        del writer  # Close the file before publishing, including on Windows.
        if temporary.stat().st_size < 100 or not temporary.read_bytes().startswith(
            b"%PDF-"
        ):
            raise ReviewSheetError("Qt did not produce a valid PDF.")
        with destination.open("xb") as target, temporary.open("rb") as source:
            try:
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
            except BaseException:
                destination.unlink(missing_ok=True)
                raise
    finally:
        temporary.unlink(missing_ok=True)
    return destination
