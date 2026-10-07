# Asset code picker

The asset form separates selection of a classification prefix from allocation of a per-item sequence. Manual registration and previously saved series retain their existing formats and numbers.

## Reference data

`app/data/asset_catalog.json` contains 907 rows extracted from all populated tables in PDF pages 7–68 of the user-supplied [คู่มือการกำหนดรหัสครุภัณฑ์](https://www.napang-nan.go.th/index/add_file/2kHQo7CThu91152.pdf). The file records the source SHA-256 and the PDF page for each row. Names retain source wording, with whitespace joined and decomposed Thai sara am normalized.

The introduction describes 4–3–4 FSN codes, but the actual appended tables have two four-digit columns, `ประเภท` and `ชนิด`. These columns are preserved as `NNNN-NNNN`; they are not silently shortened, expanded, or converted to the introductory scheme. The app appends its own individual-asset sequence and optional year. For example the table's `7110-0204` (four-drawer steel cabinet) stays fixed while `7110-0204-0001/2570` becomes `7110-0204-0002/2570` for the next item. This appended format is the application's numbering convention, not a format mandated by the source.

Four codes occur against different descriptions: `6650-0201`, `7195-0901`, `7440-0120`, `7440-0121`. Their eight rows remain searchable with source links, but cannot be selected for automatic allocation. Users may consult their own register and explicitly supply a school-defined code; the system does not invent corrections to the reference.

## Storage and safety

- Built-in lookup is local JSON; the source website is not needed to register assets.
- New `AssetNumberLabel` records store school-local names for prefixes, in the same transaction as the first successful asset allocation. The table is created through existing `init_school_db` metadata initialization.
- Preview and search never reserve numbers or create labels.
- Server-side selection uses the catalogue ID, never a client-supplied prefix for built-in rows. Existing series retain their saved width/reset/year format.
- Existing `lock_numbers`, counters and used-number reservations continue to handle concurrency, rollback, deleted assets, and duplicate protection.
- No historical asset number is modified and no classification is inferred automatically from a free-text asset name.

## Validation

Run `pytest tests/test_asset_catalog.py tests/test_asset_numbering.py tests/test_asset_split.py` with the project's dependencies. Browser checks cover search, selection, live preview, custom and manual modes, existing-series reuse, and mobile layout.
