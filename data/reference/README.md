# Static reference data

`data/reference/sector_map.csv` is an **optional, user-supplied** file that fills
the ICB sector gap when no keyless provider is used. It is never generated from
memory or invented: copy every row from a real, cited source and keep the
`source` / `as_of` columns truthful.

## `sector_map.csv`

UTF-8 (a BOM is tolerated), comma-separated, with exactly these header columns
(extra columns are ignored):

| Column | Required | Meaning |
| --- | --- | --- |
| `ticker` | yes | Exchange code, e.g. `VCB` (matched case-insensitively). |
| `icb_level1` | yes | ICB level-1 industry name, e.g. `Banks`. |
| `icb_level2` | yes | ICB level-2 supersector name, e.g. `Banks`. |
| `source` | yes | Where the row came from (a URL or the source's name). |
| `as_of` | yes | ISO date (`YYYY-MM-DD`) the classification is valid for. |

Example:

```csv
ticker,icb_level1,icb_level2,source,as_of
VCB,Banks,Banks,https://example.com/icb,2026-11-01
```

## How it is validated

`data.v2.static_sector.load_sector_map_csv` is a pure function. It validates the
file against the **KBS symbol list** (`GET /stock/search/data`) and:

- fails loudly, listing **every** unknown ticker, when a `ticker` is not in the
  KBS list;
- fails on missing columns, blank required cells, duplicate tickers and a
  non-ISO `as_of`;
- fills `SectorMap.exchange` from the KBS list (the CSV has no exchange column);
- reports coverage with `sector_coverage` (covered / known / missing) without
  failing on a deliberately partial file.

A ticker missing from the CSV is allowed (partial coverage is reported); a ticker
in the CSV that KBS does not list is a hard error, so a typo cannot silently drop
a sector.

No fabricated fallback is used for a missing sector: the feature is hidden or
disabled instead (see `docs/V2_DATA_GAPS.md`).
