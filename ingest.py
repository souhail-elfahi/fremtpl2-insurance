"""Ingestion brute de freMTPL2 (OpenML) vers DuckDB. Aucun nettoyage ici : c'est le rôle de dbt."""
from pathlib import Path

import duckdb
from sklearn.datasets import fetch_openml

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "fremtpl2.duckdb"
SOURCES = {"raw_freq": 41214, "raw_sev": 41215}  # identifiants OpenML écrits en clair


def load(data_id: int):
    return fetch_openml(data_id=data_id, as_frame=True, parser="auto").frame


def main():
    DATA_DIR.mkdir(exist_ok=True)
    con = duckdb.connect(str(DB_PATH))

    for table, data_id in SOURCES.items():
        df = load(data_id)
        con.register("df_tmp", df)
        con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM df_tmp")
        con.unregister("df_tmp")

        n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchall()[0][0]
        print(f"\n=== {table} (OpenML {data_id}) : {n} lignes, {len(df.columns)} colonnes")
        print(df.dtypes.to_string())
        print("Valeurs manquantes :", int(df.isna().sum().sum()))

    n, n_distinct = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT IDpol) FROM raw_freq"
    ).fetchall()[0]
    print(f"\nIDpol unique dans raw_freq : {n == n_distinct} ({n} lignes, {n_distinct} distincts)")
    con.close()


if __name__ == "__main__":
    main()