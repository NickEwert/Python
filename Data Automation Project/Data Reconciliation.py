import pandas as pd
from pathlib import Path

data_dir = Path(__file__).resolve().parent / "data"

df_legacy = pd.read_csv(data_dir / "legacy_donations.csv", dtype="string")
df_migrated = pd.read_csv(data_dir / "migrated_donations.csv", dtype="string")

# Keeps a copy of the original dataframes for later use
df_migrated_raw = df_migrated.copy()
df_legacy_raw = df_legacy.copy()


# Removes trailing spaces on all columns in the dataframe
for column in df_migrated.select_dtypes(include=["string", "object"]).columns:
    df_migrated[column] = df_migrated[column].str.strip()

for column in df_legacy.select_dtypes(include=["string", "object"]).columns:
    df_legacy[column] = df_legacy[column].str.strip()

issue_table = []

# Makes all donation_id and donor_id uppercase to ensure consistency between the two datasets
for column in ["donation_id", "donor_id"]:
    df_migrated[column] = df_migrated[column].str.upper()
    df_legacy[column] = df_legacy[column].str.upper()


# Function to clean duplicates and flag issues in the dataframe
def clean_duplicates(df):
    business_columns = df.columns.drop("Flagged", errors="ignore").tolist()

    df = df.drop_duplicates(
        subset=business_columns,
        keep="first"
    ).copy()

    if "Flagged" not in df.columns:
        df["Flagged"] = ""

    df["Flagged"] = df["Flagged"].fillna("")

    missing_donation_id = (
        df["donation_id"].fillna("").str.strip().eq("")
    )

    missing_donor_id = (
        df["donor_id"].fillna("").str.strip().eq("")
    )

    conflicting_id = (
        df["donation_id"].duplicated(keep=False)
        & ~missing_donation_id
    )

    checks = [
        (missing_donation_id, "Missing donation ID"),
        (missing_donor_id, "Missing donor ID"),
        (conflicting_id, "Duplicate ID with different values"),
    ]

    for condition, reason in checks:
        df.loc[condition, "Flagged"] = df.loc[
            condition, "Flagged"
        ].apply(
            lambda flag: "; ".join(
                dict.fromkeys(
                    [item for item in flag.split("; ") if item] + [reason]
                )
            )
        )

    return df


df_legacy = clean_duplicates(df_legacy)
df_migrated = clean_duplicates(df_migrated)

def clean_amounts(df):
    df = df.copy()

    # Preserve original amounts without overwriting them on reruns
    if "amount_raw" not in df.columns:
        df["amount_raw"] = df["amount"]

    if "Flagged" not in df.columns:
        df["Flagged"] = ""

    # Remove formatting and convert to numeric
    df["amount"] = pd.to_numeric(
        df["amount_raw"]
            .astype("string")
            .str.replace("$", "", regex=False)
            .str.replace(",", "", regex=False)
            .str.strip(),
        errors="coerce"
    )

    invalid_amount = df["amount"].isna()
    reason = "Missing or invalid amount"

    # Append the reason without duplicating it on reruns
    df.loc[invalid_amount, "Flagged"] = (
        df.loc[invalid_amount, "Flagged"]
        .fillna("")
        .apply(
            lambda flag: flag
            if reason in flag.split("; ")
            else f"{flag}; {reason}" if flag else reason
        )
    )

    return df

df_legacy = clean_amounts(df_legacy)
df_migrated = clean_amounts(df_migrated)


def clean_dates(df):
    df = df.copy()

    # Preserve original dates
    if "donation_date_raw" not in df.columns:
        df["donation_date_raw"] = df["donation_date"]

    if "Flagged" not in df.columns:
        df["Flagged"] = ""

    dates = (
        df["donation_date_raw"]
        .astype("string")
        .str.strip()
    )

    # Try each expected format explicitly
    iso_dates = pd.to_datetime(
        dates,
        format="%Y-%m-%d",
        errors="coerce"
    )

    us_dates = pd.to_datetime(
        dates,
        format="%m/%d/%Y",
        errors="coerce"
    )

    # Use the US-format result where the ISO conversion failed
    df["donation_date"] = iso_dates.fillna(us_dates)

    missing_date = dates.fillna("").eq("")
    invalid_date = df["donation_date"].isna() & ~missing_date

    checks = [
        (missing_date, "Missing donation date"),
        (invalid_date, "Invalid donation date"),
    ]

    for condition, reason in checks:
        df.loc[condition, "Flagged"] = (
            df.loc[condition, "Flagged"]
            .fillna("")
            .apply(
                lambda flag: flag
                if reason in flag.split("; ")
                else f"{flag}; {reason}" if flag else reason
            )
        )

    return df


df_migrated = clean_dates(df_migrated)
df_legacy = clean_dates(df_legacy)


def category_standardize(df):
    df = df.copy()

    title_columns = [
        "donor_name",
        "fund",
        "payment_method",
        "donor_type",
        "record_status"
    ]   

    for column in title_columns:
        df[column] = df[column].str.strip().str.title()


    for column in ["donor_email"]:
        df[column] = df[column].str.strip().str.lower()

    for column in ["currency", "state"]:
        df[column] = df[column].str.strip().str.upper()

    df["payment_method"] = df["payment_method"].replace({
        "Ach": "ACH",
        "Cc": "Credit Card"
    })


    return df


df_migrated = category_standardize(df_migrated)
df_legacy = category_standardize(df_legacy)


def split_outputs(df):
    has_issue = df["Flagged"].fillna("").str.strip().ne("")

    # Preserve flags and raw values for investigation
    issues = df.loc[has_issue].copy()

    # Unflagged records for reporting
    cleaned = (
        df.loc[~has_issue]
        .drop(
            columns=["Flagged", "amount_raw", "donation_date_raw"],
            errors="ignore"
        )
        .copy()
    )

    return cleaned, issues

legacy_cleaned, legacy_flags = split_outputs(df_legacy)
migrated_cleaned, migrated_flags = split_outputs(df_migrated)

def prepare_for_reconciliation(df):
    # Missing IDs can't be matched, keeps them in the issues output
    missing_id = df["donation_id"].fillna("").str.strip().eq("")
    valid_ids = df.loc[~missing_id].copy()

    # One row per ID showing presence and data quality issues
    inventory = valid_ids.groupby("donation_id").agg(
        record_count=("donation_id", "size"),
        has_issue=(
            "Flagged",
            lambda flags: flags.fillna("").str.strip().ne("").any()
        )
    ).reset_index()

    # Only attach comparison values for IDs with exactly one record
    unique_records = valid_ids.loc[
        ~valid_ids["donation_id"].duplicated(keep=False),
        ["donation_id", "amount", "donation_date", "fund"]
    ]

    return inventory.merge(
        unique_records,
        on="donation_id",
        how="left",
        validate="one_to_one"
    )


legacy_compare = prepare_for_reconciliation(df_legacy)
migrated_compare = prepare_for_reconciliation(df_migrated)

reconciliation = legacy_compare.merge(
    migrated_compare,
    on="donation_id",
    how="outer",
    suffixes=("_legacy", "_migrated"),
    indicator=True,
    validate="one_to_one"
)


# Block comparisons for flagged records or repeated IDs
blocked = (
    reconciliation["has_issue_legacy"].eq(True)
    | reconciliation["has_issue_migrated"].eq(True)
    | reconciliation["record_count_legacy"].gt(1)
    | reconciliation["record_count_migrated"].gt(1)
).fillna(False)

comparable = reconciliation["_merge"].eq("both") & ~blocked

reconciliation["reconciliation_status"] = "Unable to compare"

reconciliation.loc[
    reconciliation["_merge"].eq("left_only") & ~blocked,
    "reconciliation_status"
] = "Missing from migrated"

reconciliation.loc[
    reconciliation["_merge"].eq("right_only") & ~blocked,
    "reconciliation_status"
] = "Missing from legacy"

# Separate comparison results so multiple differences remain visible
for field in ["amount", "donation_date", "fund"]:
    matches = reconciliation[f"{field}_legacy"].eq(
        reconciliation[f"{field}_migrated"]
    ).fillna(False)

    reconciliation[f"{field}_matches"] = matches.where(
        comparable, pd.NA
    )

all_match = (
    reconciliation["amount_matches"].fillna(False)
    & reconciliation["donation_date_matches"].fillna(False)
    & reconciliation["fund_matches"].fillna(False)
)

reconciliation.loc[
    comparable & all_match, "reconciliation_status"
] = "Matched"

reconciliation.loc[
    comparable & ~all_match, "reconciliation_status"
] = "Values differ"

reconciliation["amount_difference"] = (
    reconciliation["amount_migrated"]
    - reconciliation["amount_legacy"]
).where(comparable)


with pd.ExcelWriter("donation_reconciliation.xlsx", engine="openpyxl") as writer:
    reconciliation.to_excel(writer, sheet_name="Reconciliation", index=False)
    legacy_cleaned.to_excel(writer, sheet_name="Legacy Cleaned", index=False)
    migrated_cleaned.to_excel(writer, sheet_name="Migrated Cleaned", index=False)
    legacy_flags.to_excel(writer, sheet_name="Legacy Flagged", index=False)
    migrated_flags.to_excel(writer, sheet_name="Migrated Flagged", index=False)
