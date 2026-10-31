import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Option:
    id: str
    title: str
    description: str = ""
    price: int = 0
    multiplier: float = 1.0
    needs_address: bool = False


class Catalog:
    def __init__(self, path: Path):
        self.path = path
        self.reload()

    def reload(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.currency: str = data.get("currency", "تومان")
        self.max_reference_photos: int = int(data.get("max_reference_photos", 5))
        self.styles = [self._opt(o) for o in data["styles"]]
        self.sizes = [self._opt(o) for o in data["sizes"]]
        self.faces = [self._opt(o) for o in data["faces"]]
        self.deliveries = [self._opt(o) for o in data["deliveries"]]

    @staticmethod
    def _opt(raw: dict) -> Option:
        return Option(
            id=str(raw["id"]),
            title=raw["title"],
            description=raw.get("description", ""),
            price=int(raw.get("price", 0)),
            multiplier=float(raw.get("multiplier", 1.0)),
            needs_address=bool(raw.get("needs_address", False)),
        )

    @staticmethod
    def find(options: list[Option], option_id: str) -> Option | None:
        return next((o for o in options if o.id == option_id), None)

    def style(self, i: str) -> Option | None:
        return self.find(self.styles, i)

    def size(self, i: str) -> Option | None:
        return self.find(self.sizes, i)

    def face(self, i: str) -> Option | None:
        return self.find(self.faces, i)

    def delivery(self, i: str) -> Option | None:
        return self.find(self.deliveries, i)

    def price(self, style_id: str, size_id: str, faces_id: str, delivery_id: str) -> int:
        style, size = self.style(style_id), self.size(size_id)
        faces, delivery = self.face(faces_id), self.delivery(delivery_id)
        if not all((style, size, faces, delivery)):
            raise ValueError("invalid catalog selection")
        raw = style.price * size.multiplier * faces.multiplier + delivery.price
        return int(round(raw / 1000.0)) * 1000  # round to nearest 1000
