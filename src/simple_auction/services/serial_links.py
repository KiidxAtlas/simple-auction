"""Links shown under the Serial # field, e.g. a serial lookup website.

Each link is a URL template. These placeholders are filled in, URL-encoded:
  {serial}  the lot's serial number
  {make}    the Make field, else the maker recognised in the title
            (see makers.py), else empty
  {title}   the lot title
Query parameters that end up empty are dropped, so one template works
whether or not the maker is known.
"""

from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from simple_auction.services.makers import guess_maker

PLACEHOLDERS = ("{serial}", "{make}", "{title}")


@dataclass(frozen=True)
class SerialLink:
    name: str
    url: str


DEFAULT_LINKS = [
    SerialLink(
        "Lindcott Armory",
        "https://lindcottarmory.com/serial-lookup?make={make}&serial={serial}",
    ),
]


def build_url(template: str, serial: str, title: str = "", make: str = "") -> str:
    values = {
        "{serial}": serial.strip(),
        "{make}": make.strip() or guess_maker(title) or "",
        "{title}": title.strip(),
    }
    url = template
    for placeholder, value in values.items():
        url = url.replace(placeholder, quote(value, safe=""))
    parts = urlsplit(url)
    if not parts.query:
        return url
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if v]
    return urlunsplit(parts._replace(query=urlencode(query, quote_via=quote)))


def is_valid(link: SerialLink) -> bool:
    return bool(link.name.strip()) and link.url.strip().startswith(
        ("http://", "https://")
    )


def to_json(links: list[SerialLink]) -> list[dict]:
    return [{"name": link.name, "url": link.url} for link in links]


def from_json(data: object) -> list[SerialLink]:
    if not isinstance(data, list):
        return list(DEFAULT_LINKS)
    links = [
        SerialLink(str(d.get("name", "")), str(d.get("url", "")))
        for d in data
        if isinstance(d, dict)
    ]
    return [link for link in links if is_valid(link)]
