# TPC-DS Starter Ontology

A modular OWL/Turtle ontology covering the TPC-DS retail data warehouse,
designed as a starting point for semantic-layer experiments alongside
the Parquet data produced by `scripts/load_tpcds.py`.

## Files

| File                       | Purpose                                                                                  |
| -------------------------- | ---------------------------------------------------------------------------------------- |
| `tpcds-core.ttl`           | Namespaces, abstract roots, the **sales channel** code list, shared object properties.   |
| `tpcds-dimensions.ttl`     | The 17 conformed dimensions (Customer, Item, Store, CalendarDay, …) and their attributes.|
| `tpcds-facts.ttl`          | The 7 fact tables as **RDF Data Cube** observations with shared measures and DSDs.       |
| `tpcds-mappings.ttl`       | Table-and-column → ontology bindings for every Parquet file under `data/raw/tpcds_sf*`.  |

Load order (each file imports the previous via `owl:imports`):

```
tpcds-core  ⇐  tpcds-dimensions  ⇐  tpcds-facts  ⇐  tpcds-mappings
```

## Vocabularies reused

| Prefix     | Vocabulary                                             | Used for                                   |
| ---------- | ------------------------------------------------------ | ------------------------------------------ |
| `qb:`      | [RDF Data Cube](https://www.w3.org/TR/vocab-data-cube/)| Facts as observations, DSDs, measures      |
| `schema:`  | [schema.org](https://schema.org)                       | Person, PostalAddress, Product, Place, …   |
| `skos:`    | SKOS                                                   | Code lists (channels, ship modes, reasons) |
| `time:`    | OWL Time                                               | Calendar day and time-of-day               |
| `dct:`     | Dublin Core Terms                                      | Ontology metadata                          |
| `sdmx-*:`  | SDMX Content-Oriented Guidelines                       | Standard observation attribute slots       |

## Design choices

1. **Three sales channels, one shape.** `StoreSale`, `CatalogSale`, and `WebSale` all
   subclass `tpcds:SalesTransaction` and share the `SalesDSD`, so cross-channel
   roll-ups are well-defined out of the box. Same pattern for returns.
2. **SCD-2 friendly.** Any dimension can carry `tpcds:validFrom` / `tpcds:validTo`,
   matching the `*_rec_start_date` / `*_rec_end_date` columns in TPC-DS.
3. **Stable IRIs from business keys.** The mapping file mints IRIs from
   `*_id` business keys (not `*_sk` surrogates) so identity is portable across
   reloads. Surrogate keys are preserved as `tpcds:surrogateKey` for lineage.
4. **Lookup tables as SKOS.** Small enumerations (ship mode, reason, income band,
   item category) are `skos:Concept` instances inside named concept schemes —
   ready for hierarchical browsing and external linking.
5. **Mapping vocab is intentionally tiny.** `tpcds-mappings.ttl` uses an inline
   `map:` vocabulary instead of full R2RML/RML so the file is readable and
   easy to extend. Any ETL (DuckDB SQL → RDF, RML processor, custom Spark job)
   can consume it.

## Validating the TTL

Any RDF tool will do. Quick option with the existing venv:

```powershell
.\.venv\Scripts\python.exe -m pip install rdflib
.\.venv\Scripts\python.exe -c "from rdflib import Graph; import glob; g=Graph(); [g.parse(f, format='turtle') for f in glob.glob('ontology/*.ttl')]; print('triples:', len(g))"
```

## What's deliberately *not* in here yet

- SHACL shapes for data-quality checks
- Concrete `skos:Concept` instances for the lookup tables (those should be
  generated from the data, not hand-curated)
- Full RML mapping with `rml:logicalSource` / `rml:referenceFormulation` for
  Parquet (the `map:` vocab is a stepping stone — convert when needed)
- VoID / DCAT dataset descriptions
