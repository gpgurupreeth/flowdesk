
import re


FIELD_ALIASES = {
    "name": {
        "name",
        "full name",
        "contact name",
        "lead name",
        "customer name",
        "person name",
    },
    "email": {
        "email",
        "email address",
        "e mail",
        "contact email",
    },
    "company": {
        "company",
        "company name",
        "organization",
        "organisation",
        "business name",
    },
    "phone": {
        "phone",
        "phone number",
        "mobile",
        "mobile number",
        "contact number",
        "phone no",
    },
    "location": {
        "location",
        "city",
        "region",
        "address",
    },
}

REQUIRED_FIELDS = {"name", "email", "company"}

# Sentinel value used to auto-map any column that does not match a standard
# field to a custom field created from the column header itself.
CUSTOM_FIELD = "__custom__"


def normalize_header(header: str) -> str:
    header = header.casefold().strip()
    header = re.sub(r"[^a-z0-9]+", " ", header)
    return " ".join(header.split())


def detect_column_mapping(
    headers: list[str],
) -> dict[str, str | None]:
    """Map spreadsheet headers to standard fields or custom fields.

    Every column receives a destination:
    - Known standard-field aliases are mapped to their field (name, email,
      company, phone, location), each used only once.
    - All other columns are mapped to ``__custom__`` so the frontend can
      auto-create a custom field from the column header. This keeps large
      spreadsheets fully automated with no per-column manual work.
    """
    mapping: dict[str, str | None] = {}
    used_fields: set[str] = set()

    for header in headers:
        normalized = normalize_header(header)
        matched_field = None

        for field, aliases in FIELD_ALIASES.items():
            if normalized in aliases:
                matched_field = field
                break

        if matched_field and matched_field not in used_fields:
            mapping[header] = matched_field
            used_fields.add(matched_field)
        else:
            # Auto-map to a custom field created from the column header.
            mapping[header] = CUSTOM_FIELD

    return mapping


def build_custom_field_configs(
    headers: list[str],
    mapping: dict[str, str | None],
) -> dict[str, dict[str, str]]:
    """Auto-generate custom field configuration for every __custom__ column.

    Returns a dict keyed by source column header, with name derived from the
    header and type defaulting to ``text``.
    """
    configs: dict[str, dict[str, str]] = {}
    seen_names: set[str] = set()

    for header in headers:
        destination = mapping.get(header)
        if destination != CUSTOM_FIELD:
            continue

        name = header.strip()
        base_name = name
        suffix = 1
        # Ensure custom field names are unique (case-insensitive).
        while name.lower() in seen_names:
            suffix += 1
            name = f"{base_name} ({suffix})"
        seen_names.add(name.lower())

        configs[header] = {
            "name": name,
            "type": "text",
        }

    return configs
