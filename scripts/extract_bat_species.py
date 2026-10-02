"""Regenerate custom_components/haikubox/data/bat_species.json.

The bundled bat list lets the integration tell bat rows from bird rows in
/daily-count, which gives common names only (no species code). Its source is
Table 3 of the USGS "Guide to Processing Bat Acoustic Data for the North
American Bat Monitoring Program (NABat)", Open-File Report 2018-1068: the 46
North American bat species with their NABat 6-letter codes, which are the codes
Haikubox reports for bats. USGS publications are U.S. Government works in the
public domain.

This is a one-off maintenance script, not part of the integration. It needs
pypdf, which isn't a project dependency:

    pip install pypdf
    curl -LO https://pubs.usgs.gov/of/2018/1068/ofr20181068.pdf
    python scripts/extract_bat_species.py ofr20181068.pdf
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

SOURCE = (
    "USGS Open-File Report 2018-1068, Table 3 "
    "(https://pubs.usgs.gov/publication/ofr20181068); public domain"
)
OUT = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "haikubox" / "data" / "bat_species.json"
)

# Table 3 prints Townsend's big-eared bat as "CORTO", one letter short; NABat's
# own species-code list uses CORTOW.
CORRECTIONS = {"CORTO": "CORTOW"}

# "<common name> <Genus species> <4-letter> <6-letter>", one species per line.
ROW = re.compile(r"^(?P<common>.+?) (?P<sci>[A-Z][a-z]+ [a-z]+) [A-Z]{4} (?P<code>[A-Z]{5,6})$")


def extract(pdf_path: str) -> list[dict[str, str]]:
    text = next(
        page.extract_text()
        for page in PdfReader(pdf_path).pages
        if "Table 3." in (page.extract_text() or "")
    )
    species = []
    for line in text.splitlines():
        if m := ROW.match(line.strip()):
            code = CORRECTIONS.get(m["code"], m["code"])
            species.append({
                "common": m["common"].replace("’", "'"),
                "scientific": m["sci"],
                "code": code,
            })
    return species


def main() -> None:
    species = extract(sys.argv[1])
    if len(species) != 46:
        sys.exit(f"Expected 46 species in Table 3, found {len(species)}")
    OUT.write_text(
        json.dumps({"source": SOURCE, "species": species}, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(species)} species to {OUT}")


if __name__ == "__main__":
    main()
