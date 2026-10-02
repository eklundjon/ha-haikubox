# Bundled data

## `ebird_species_codes.json`

`ebird_species_codes.json` maps each bird's common name to its eBird species code and scientific name. It's derived from the eBird/Clements taxonomy. It isn't the original checklist file. The integration uses it to find a species' photo (photos are stored by species code) and scientific name when Haikubox hasn't provided them yet.

### Source and citation

> Clements, J. F., P. C. Rasmussen, T. S. Schulenberg, M. J. Iliff,
> T. A. Fredericks, J. A. Gerbracht, D. Lepage, A. Spencer, S. M. Billerman,
> B. L. Sullivan, and C. L. Wood. 2025. The eBird/Clements checklist of birds
> of the world: v2025. Downloaded from
> <https://www.birds.cornell.edu/clementschecklist/download/>

© Cornell Lab of Ornithology.

### Terms

Under the eBird/Clements terms of use:

- This is a derived product, not a copy of the checklist in its original format.
- **Non-commercial use only.** Commercial use of eBird/Clements data requires permission from eBird.
- Cornell asks authors of derived products to send eBird an electronic copy. Anyone distributing this integration commercially, or wanting to honor that request, should contact eBird.

To update it, download the current eBird Taxonomy CSV from the link above and rebuild the `common name → { SPECIES_CODE, SCI_NAME }` map from the rows where `CATEGORY == "species"`.

## `bat_species.json`

`bat_species.json` lists the 46 North American bat species with their common names, scientific names and NABat six-letter codes, which are the codes Haikubox reports for bats. The integration uses it to tell bats from birds in the daily counts, which give common names only.

It comes from Table 3 of the USGS *Guide to Processing Bat Acoustic Data for the North American Bat Monitoring Program (NABat)*, Open-File Report 2018-1068 (<https://pubs.usgs.gov/publication/ofr20181068>). USGS publications are U.S. Government works in the public domain. One code is corrected: the table prints Townsend's big-eared bat as `CORTO`, and the file uses NABat's `CORTOW`.

To update it, run `scripts/extract_bat_species.py` against the report's PDF.

---

This file only covers the bundled eBird map and bat list. The Haikubox data the integration shows (detections, counts and photos) is licensed separately by Haikubox under **CC BY-NC-SA 4.0**, and Haikubox asks that research use cite BirdNET (Kahl et al. 2021). See **Attribution & data licensing** in the project README.
