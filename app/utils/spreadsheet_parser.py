
from io import BytesIO
from pathlib import Path

import pandas as pd


ALLOWED_EXTENSIONS = {".csv", ".xlsx"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_ROWS = 10_000


def parse_spreadsheet(
    filename: str,
    content: bytes,
) -> list[dict[str, object]]:
    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Upload a CSV or XLSX file.")

    if not content:
        raise ValueError("The uploaded file is empty.")

    if len(content) > MAX_FILE_SIZE:
        raise ValueError("The file exceeds the 10 MB limit.")

    try:
        if extension == ".csv":
            dataframe = pd.read_csv(
                BytesIO(content),
                dtype=str,
                keep_default_na=False,
            )
        else:
            dataframe = pd.read_excel(
                BytesIO(content),
                dtype=str,
                keep_default_na=False,
                engine="openpyxl",
            )
    except Exception as exc:
        raise ValueError(
            "Unable to read this file. Check that it is a valid CSV or XLSX."
        ) from exc

    if dataframe.empty and len(dataframe.columns) == 0:
        raise ValueError("The spreadsheet has no column headers.")

    if len(dataframe) > MAX_ROWS:
        raise ValueError(f"The spreadsheet cannot exceed {MAX_ROWS} rows.")

    headers = [str(column).strip() for column in dataframe.columns]

    if any(not header for header in headers):
        raise ValueError("Every column must have a header.")

    # Pandas auto-names blank columns as "Unnamed: N". Treat those as blank.
    if any(header.lower().startswith("unnamed") for header in headers):
        raise ValueError("Every column must have a header.")

    normalized_headers = [header.casefold() for header in headers]

    if len(normalized_headers) != len(set(normalized_headers)):
        raise ValueError("The spreadsheet contains duplicate column headers.")

    dataframe.columns = headers
    dataframe = dataframe.fillna("")

    rows = dataframe.to_dict(orient="records")

    return [
        {
            str(key): str(value).strip()
            for key, value in row.items()
        }
        for row in rows
    ]
