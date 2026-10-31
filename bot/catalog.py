"""Service catalog (types of work, number of people, price range).

Stored in the database so admins can change everything from the bot.
`catalog.json` is only used to seed the database on first run."""
import json
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Option:
    id: str
    title: str
    description: str = ""
    hidden: bool = False   # hidden options stay readable for old orders


class Catalog:
    def __init__(self, seed_path: Path):
        self.seed_path = seed_path
        self.load(seed_path.read_text(encoding="utf-8"))

    # ---------- (de)serialisation ----------
    def load(self, raw: str) -> None:
        data = json.loads(raw)
        styles = [self._opt(o) for o in data["styles"]]
        faces = [self._opt(o) for o in data["faces"]]
        price_min, price_max = int(data["price_min"]), int(data["price_max"])
        quick = [int(p) for p in data.get("quick_prices", [])]
        if not any(not o.hidden for o in styles) or not any(not o.hidden for o in faces):
            raise ValueError("at least one visible style and one visible faces option are required")
        if price_min <= 0 or price_max < price_min or any(p <= 0 for p in quick):
            raise ValueError("invalid prices")
        # assign only after full validation, so a broken file never half-applies
        self.currency: str = data.get("currency", "تومان")
        self.price_min, self.price_max, self.quick_prices = price_min, price_max, quick
        self.max_reference_photos: int = max(1, min(10, int(data.get("max_reference_photos", 5))))
        self._styles, self._faces = styles, faces

    def dump(self) -> str:
        return json.dumps(
            {
                "currency": self.currency,
                "price_min": self.price_min,
                "price_max": self.price_max,
                "quick_prices": self.quick_prices,
                "max_reference_photos": self.max_reference_photos,
                "styles": [asdict(o) for o in self._styles],
                "faces": [asdict(o) for o in self._faces],
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _opt(raw: dict) -> Option:
        return Option(
            id=str(raw["id"]),
            title=raw["title"],
            description=raw.get("description", ""),
            hidden=bool(raw.get("hidden", False)),
        )

    # ---------- reading ----------
    @property
    def styles(self) -> list[Option]:
        return [o for o in self._styles if not o.hidden]

    @property
    def faces(self) -> list[Option]:
        return [o for o in self._faces if not o.hidden]

    def all_options(self, kind: str) -> list[Option]:
        return self._styles if kind == "style" else self._faces

    @staticmethod
    def _find(options: list[Option], option_id: str) -> Option | None:
        return next((o for o in options if o.id == option_id), None)

    def style(self, i: str, include_hidden: bool = False) -> Option | None:
        o = self._find(self._styles, i)
        return o if o and (include_hidden or not o.hidden) else None

    def face(self, i: str, include_hidden: bool = False) -> Option | None:
        o = self._find(self._faces, i)
        return o if o and (include_hidden or not o.hidden) else None

    # ---------- editing (call context.save_catalog() afterwards) ----------
    def add_option(self, kind: str, title: str, description: str = "") -> Option:
        opt = Option(id=secrets.token_hex(3), title=title, description=description)
        self.all_options(kind).append(opt)
        return opt

    def toggle_option(self, kind: str, option_id: str) -> Option | None:
        opt = self._find(self.all_options(kind), option_id)
        if not opt:
            return None
        visible = [o for o in self.all_options(kind) if not o.hidden]
        if not opt.hidden and len(visible) <= 1:
            raise ValueError("last visible option")
        opt.hidden = not opt.hidden
        return opt

    def edit_option(self, kind: str, option_id: str, title: str, description: str) -> Option | None:
        opt = self._find(self.all_options(kind), option_id)
        if opt:
            opt.title, opt.description = title, description
        return opt
