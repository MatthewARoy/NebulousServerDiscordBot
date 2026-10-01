"""Bounded, non-executing reader for NEBULOUS fleet XML."""

import hashlib
import re
import xml.etree.ElementTree as ET

MAX_FLEET_BYTES = 2 * 1024 * 1024
MAX_XML_DEPTH = 64
MAX_XML_NODES = 60000
MAX_SHIPS = 128
MAX_SOCKETS = 32768
MAX_AMMUNITION_LOADS = 32768
MAX_NAME_LENGTH = 256
MAX_ID_LENGTH = 512


class FleetInputError(ValueError):
    """A fleet upload is malformed, unsupported, or exceeds bounded input limits."""


def _decode(data):
    if not isinstance(data, bytes):
        raise FleetInputError("Fleet input must be bytes.")
    if len(data) > MAX_FLEET_BYTES:
        raise FleetInputError("Fleet exceeds the 2 MiB size limit.")
    if not data:
        raise FleetInputError("Fleet file is empty.")
    # Decode before scanning: an ASCII byte scan misses UTF-16/32 DTDs.
    if data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        encoding = "utf-32"
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    elif data.startswith(b"\x00\x00\x00<"):
        encoding = "utf-32-be"
    elif data.startswith(b"<\x00\x00\x00"):
        encoding = "utf-32-le"
    elif data.startswith(b"\x00<"):
        encoding = "utf-16-be"
    elif data.startswith(b"<\x00"):
        encoding = "utf-16-le"
    else:
        encoding = "utf-8-sig"
    try:
        value = data.decode(encoding)
    except UnicodeError as exc:
        raise FleetInputError("Fleet XML must use UTF-8, UTF-16, or UTF-32 encoding.") from exc
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", value, re.IGNORECASE):
        raise FleetInputError("Fleet XML must not contain DTD or entity declarations.")
    declaration = re.match(r"<\?xml\b[^?]*\?>", value)
    if declaration:
        declared = re.search(r"\bencoding\s*=\s*['\"]([^'\"]+)['\"]", declaration[0])
        if declared and declared[1].lower().replace("-", "") not in {
            "utf8", "utf16", "utf16le", "utf16be", "utf32", "utf32le", "utf32be", "usascii", "ascii"
        }:
            raise FleetInputError("Unsupported fleet XML encoding declaration.")
        # Expat does not accept UTF-32 as bytes; the decoded document is safe to
        # pass as Unicode once its declaration has been checked and removed.
        value = value[len(declaration[0]):]
    return value


def _tree(value):
    parser = ET.XMLPullParser(events=("start", "end"))
    depth = nodes = 0
    root = None
    try:
        for offset in range(0, len(value), 4096):
            parser.feed(value[offset:offset + 4096])
            for event, element in parser.read_events():
                if event == "start":
                    depth += 1
                    nodes += 1
                    if depth > MAX_XML_DEPTH:
                        raise FleetInputError(f"Fleet XML exceeds the {MAX_XML_DEPTH}-level depth limit.")
                    if nodes > MAX_XML_NODES:
                        raise FleetInputError(f"Fleet XML exceeds the {MAX_XML_NODES}-node limit.")
                    if root is None:
                        root = element
                    element.tag = element.tag.rsplit("}", 1)[-1]
                else:
                    depth -= 1
        parser.close()
    except ET.ParseError as exc:
        raise FleetInputError(f"Malformed fleet XML: {exc}.") from exc
    if root is None or root.tag not in {"Fleet", "Ship"}:
        raise FleetInputError("Expected a Fleet or Ship XML document.")
    return root


def _text(element, name, default="", *, limit=MAX_ID_LENGTH):
    value = element.findtext(name) or default
    # Game registry/save identities use exact strings. Whitespace must not turn
    # an invalid/modded ID into an apparently supported stock fit.
    if name not in {"Key", "HullType", "ComponentName", "MunitionKey", "FactionKey", "SaveKey"}:
        value = value.strip()
    if len(value) > limit:
        raise FleetInputError(f"{name} exceeds the {limit}-character limit.")
    return value


def _integer(value, label, *, optional=False):
    if optional and not value:
        return None
    if not re.fullmatch(r"\d{1,10}", value):
        raise FleetInputError(f"{label} must be a nonnegative integer.")
    return int(value)


def parse_design(data: bytes) -> dict:
    """Read a fleet or individual ship template without interpreting descriptive prose."""
    root = _tree(_decode(data))
    if root.tag == "Fleet":
        ship_lists = root.findall("Ships")
        if len(ship_lists) != 1:
            raise FleetInputError("Fleet must have exactly one Ships element.")
        ship_elements = ship_lists[0].findall("Ship")
    else:
        ship_elements = [root]
    if not ship_elements:
        raise FleetInputError("Fleet has no ships to review.")
    if len(ship_elements) > MAX_SHIPS:
        raise FleetInputError(f"Fleet exceeds the {MAX_SHIPS}-ship limit.")
    custom_ids = set()
    templates = root.findall("MissileTypes/MissileTemplate")
    for ship_element in ship_elements:
        templates.extend(ship_element.findall("TemplateMissileTypes/MissileTemplate"))
    for template in templates:
        # Custom missile names are local template identities, not stock IDs.
        name = " ".join(filter(None, (_text(template, "Designation"), _text(template, "Nickname"))))
        if name:
            if len("$MODMIS$/" + name) > MAX_ID_LENGTH:
                raise FleetInputError("Custom missile identity exceeds the character limit.")
            custom_ids.add("$MODMIS$/" + name)
    result = {
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "kind": "fleet" if root.tag == "Fleet" else "ship",
        "name": _text(root, "Name", "Unnamed design", limit=MAX_NAME_LENGTH),
        "faction": _text(root, "FactionKey"),
        "declared_points": _integer(_text(root, "TotalPoints" if root.tag == "Fleet" else "Cost"),
                                    "Declared points", optional=True),
        "ships": [],
        "custom_template_ids": sorted(custom_ids),
    }
    sockets_seen = loads_seen = 0
    keys = set()
    for index, element in enumerate(ship_elements, 1):
        hull = _text(element, "HullType")
        if not hull:
            raise FleetInputError(f"Ship {index} is missing its HullType.")
        socket_maps = element.findall("SocketMap")
        if len(socket_maps) != 1:
            raise FleetInputError(f"Ship {index} must have exactly one SocketMap.")
        key = _text(element, "Key", f"ship-{index}")
        if key in keys:
            raise FleetInputError("Fleet contains duplicate ship keys.")
        keys.add(key)
        ship = {
            "key": key,
            "name": _text(element, "Name", f"Ship {index}", limit=MAX_NAME_LENGTH),
            "hull": hull,
            "components": [],
            "sockets": [],
            "ammunition": {},
            "declared_points": _integer(_text(element, "Cost"), "Ship Cost", optional=True),
            "hull_config": ET.tostring(element.find("HullConfig"), encoding="unicode")
                           if element.find("HullConfig") is not None else None,
            "formation_guide": _text(element, "FormationGuide") or _text(element, "InitialFormation/GuideKey") or None,
        }
        socket_keys = set()
        for socket in socket_maps[0].findall("HullSocket"):
            sockets_seen += 1
            if sockets_seen > MAX_SOCKETS:
                raise FleetInputError(f"Fleet exceeds the {MAX_SOCKETS}-socket limit.")
            component = _text(socket, "ComponentName")
            socket_key = _text(socket, "Key")
            if socket_key and socket_key in socket_keys:
                raise FleetInputError("Ship contains duplicate socket keys.")
            if socket_key:
                socket_keys.add(socket_key)
            ship["sockets"].append({"key": socket_key or None, "component": component or None})
            if not component:
                continue  # An empty hull socket is a valid observation.
            ship["components"].append(component)
            # Load is the actual inventory of magazine and cell-launcher data.
            # Do not descend into missile or spacecraft template definitions.
            for load in socket.findall("ComponentData/Load") + socket.findall("ComponentData/MissileLoad"):
                for item in load:
                    munition = _text(item, "MunitionKey")
                    if not munition:
                        continue
                    loads_seen += 1
                    if loads_seen > MAX_AMMUNITION_LOADS:
                        raise FleetInputError(f"Fleet exceeds the {MAX_AMMUNITION_LOADS}-ammunition-load limit.")
                    quantity = _integer(_text(item, "Quantity"), "Loaded ammunition Quantity")
                    if quantity > 0:
                        ship["ammunition"][munition] = ship["ammunition"].get(munition, 0) + quantity
        result["ships"].append(ship)
    return result


def parse_fleet(data: bytes) -> dict:
    """Compatibility entry point for consumers accepting only a fleet document."""
    result = parse_design(data)
    if result["kind"] != "fleet":
        raise FleetInputError("Expected a Fleet XML document.")
    return result
