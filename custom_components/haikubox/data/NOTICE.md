# Bundled data attribution — `ebird_species_codes.json`

`ebird_species_codes.json` is a **derived** dataset: a transformed, two-column
mapping of `common name → eBird species_code`, extracted from the eBird/Clements
taxonomy. It is **not** the original checklist file. The integration uses it
only to resolve a species' photo (the image CDN is keyed by species code) when
that code wasn't already learned from the live Haikubox API.

## Source & citation

> Clements, J. F., P. C. Rasmussen, T. S. Schulenberg, M. J. Iliff,
> T. A. Fredericks, J. A. Gerbracht, D. Lepage, A. Spencer, S. M. Billerman,
> B. L. Sullivan, and C. L. Wood. 2025. The eBird/Clements checklist of birds
> of the world: v2025. Downloaded from
> <https://www.birds.cornell.edu/clementschecklist/download/>

© Cornell Lab of Ornithology.

## Terms

Per the eBird/Clements terms of use:

- This is a **derived product**, not a redistribution of the checklist in its
  original format.
- **Non-commercial use.** Any commercial use of eBird/Clements data requires
  explicit permission from eBird.
- Cornell requests that authors of derived products send eBird an electronic
  copy; a maintainer distributing this integration commercially, or wishing to
  honor that request, should contact eBird.

To refresh: download the current eBird Taxonomy CSV from the link above and
regenerate the `common name → SPECIES_CODE` map for `CATEGORY == "species"`.

---

This file covers only the bundled eBird-derived map. The **Haikubox API data**
the integration surfaces at runtime (detections, counts, photos) is separately
licensed by Haikubox under **CC BY-NC-SA 4.0** and asks that research use cite
BirdNET (Kahl et al. 2021) — see the **Attribution & data licensing** section
of the project README.
