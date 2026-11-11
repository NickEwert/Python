# Donation Migration Reconciliation

This Python project audits a simulated donation data migration. It cleans
and validates two CSV exports, then matches records by donation ID
and compares the donation amount, date, and fund.

The script identifies records missing from either system and flags data
quality issues that prevent a reliable comparison.

## Run the project

From the project folder, run:

```bash
python3 -m pip install -r requirements.txt
python3 Data Reconciliation.py
```

## Inputs and output

The source files are `data/legacy_donations.csv` and
`data/migrated_donations.csv`.

The script produces `donation_reconciliation.xlsx`, with one tab for the
reconciliation results, two for cleaned data, and two for flagged records.

## How duplicates are handled

The script removes exact duplicate rows. When multiple rows share a
donation ID but contain different values, it flags them for review.
