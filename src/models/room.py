from pydantic import BaseModel
from typing import Any

class Room(BaseModel):
    room_id: str
    building: str = ""
    capacity: int = 0
    available: bool = True
    availability: dict[str, list[tuple[str, str]]] = {}
    room_type: str = "Lecture"   # CLIENT-CONFIG: "Lecture" | "Laboratory" |
    attributes: dict[str, Any] = {}   # CLIENT-CONFIG: future room properties
