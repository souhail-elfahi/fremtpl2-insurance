"""Contrôles de qualité sur les données brutes freMTPL2. Lecture seule : on mesure, on ne corrige rien."""
import sys
from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parent / "data" / "fremtpl2.duckdb"

# Rapprochement à la maille contrat : sinistres déclarés (freq) contre lignes de sinistres (sev).
# raw_sev est agrégée AVANT la jointure, sinon un contrat à 3 sinistres compterait 3 fois son ClaimNb.
RAPPROCHEMENT = """
WITH sev AS (
    SELECT IDpol, COUNT(*) AS n_lignes, SUM(ClaimAmount) AS montant
    FROM raw_sev
    GROUP BY IDpol
),
r AS (
    SELECT
        f.IDpol AS idpol_freq,
        COALESCE(f.ClaimNb, 0) AS claim_nb,
        COALESCE(s.n_lignes, 0) AS n_lignes,
        s.montant
    FROM raw_freq f
    FULL OUTER JOIN sev s ON f.IDpol = s.IDpol
)
"""


def show(con, titre: str, sql: str):
    df = con.execute(sql).df()
    print(f"\n--- {titre}")
    print("(aucune ligne)" if df.empty else df.to_string(index=False))


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # accents lisibles même si la sortie est redirigée
    con = duckdb.connect(str(DB_PATH), read_only=True)

    print("\n=== 0. Clé de jointure et valeurs manquantes")
    show(con, "raw_freq", """
        SELECT
            COUNT(*) AS lignes,
            COUNT(*) - COUNT(DISTINCT IDpol) AS idpol_en_double_ou_nuls,
            COUNT(*) FILTER (WHERE IDpol <> FLOOR(IDpol)) AS idpol_non_entiers,
            COUNT(*) FILTER (WHERE ClaimNb IS NULL) AS claimnb_nuls,
            COUNT(*) FILTER (WHERE ClaimNb < 0) AS claimnb_negatifs
        FROM raw_freq
    """)
    show(con, "raw_sev", """
        SELECT
            COUNT(*) AS lignes,
            COUNT(*) FILTER (WHERE IDpol IS NULL) AS idpol_nuls
        FROM raw_sev
    """)

    print("\n=== 1. Sinistres orphelins (IDpol de raw_sev absent de raw_freq)")
    show(con, "volume et montant", """
        WITH orphelins AS (
            SELECT s.* FROM raw_sev s ANTI JOIN raw_freq f ON s.IDpol = f.IDpol
        )
        SELECT
            COUNT(*) AS lignes,
            COUNT(DISTINCT IDpol) AS idpol_distincts,
            ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM raw_sev), 3) AS pct_lignes,
            ROUND(COALESCE(SUM(ClaimAmount), 0), 2) AS montant,
            ROUND(100.0 * COALESCE(SUM(ClaimAmount), 0)
                  / (SELECT SUM(ClaimAmount) FROM raw_sev), 3) AS pct_montant
        FROM orphelins
    """)

    print("\n=== 2. Écart entre SUM(ClaimNb) et le nombre de lignes de sinistres")
    show(con, "total", """
        SELECT
            declares AS somme_claimnb,
            lignes AS lignes_raw_sev,
            declares - lignes AS ecart
        FROM (
            SELECT
                (SELECT SUM(ClaimNb)::BIGINT FROM raw_freq) AS declares,
                (SELECT COUNT(*) FROM raw_sev) AS lignes
        )
    """)
    show(con, "décomposition de l'écart par situation (la colonne ecart se somme au total)",
         RAPPROCHEMENT + """
        SELECT
            CASE
                WHEN idpol_freq IS NULL THEN 'orphelin'
                WHEN claim_nb = n_lignes AND claim_nb = 0 THEN 'cohérent : aucun sinistre'
                WHEN claim_nb = n_lignes THEN 'cohérent : avec sinistres'
                WHEN n_lignes = 0 THEN 'ClaimNb > 0, aucune ligne'
                WHEN claim_nb = 0 THEN 'ClaimNb = 0, mais des lignes'
                WHEN claim_nb > n_lignes THEN 'ClaimNb > lignes (lignes > 0)'
                ELSE 'lignes > ClaimNb (ClaimNb > 0)'
            END AS situation,
            COUNT(*) AS contrats,
            SUM(claim_nb)::BIGINT AS somme_claimnb,
            SUM(n_lignes)::BIGINT AS lignes_sev,
            SUM(claim_nb - n_lignes)::BIGINT AS ecart
        FROM r
        GROUP BY situation
        ORDER BY contrats DESC
    """)

    print("\n=== 3. Contrats avec ClaimNb > 0 mais sans montant")
    show(con, "volume", RAPPROCHEMENT + """
        SELECT
            COUNT(*) AS contrats_claimnb_positif,
            COUNT(*) FILTER (WHERE montant IS NULL) AS sans_montant,
            ROUND(100.0 * COUNT(*) FILTER (WHERE montant IS NULL) / COUNT(*), 2) AS pct
        FROM r
        WHERE idpol_freq IS NOT NULL AND claim_nb > 0
    """)
    show(con, "répartition par ClaimNb", RAPPROCHEMENT + """
        SELECT
            claim_nb,
            COUNT(*) AS contrats,
            COUNT(*) FILTER (WHERE montant IS NULL) AS sans_montant,
            ROUND(100.0 * COUNT(*) FILTER (WHERE montant IS NULL) / COUNT(*), 2) AS pct
        FROM r
        WHERE idpol_freq IS NOT NULL AND claim_nb > 0
        GROUP BY claim_nb
        ORDER BY claim_nb
    """)

    print("\n=== 4. Exposition hors de ]0, 1]")
    show(con, "volume", """
        SELECT
            COUNT(*) FILTER (WHERE Exposure IS NULL) AS nulles,
            COUNT(*) FILTER (WHERE Exposure <= 0) AS inf_ou_egale_0,
            COUNT(*) FILTER (WHERE Exposure > 1) AS sup_1,
            ROUND(100.0 * COUNT(*) FILTER (WHERE Exposure > 1) / COUNT(*), 3) AS pct_sup_1,
            MIN(Exposure) AS minimum,
            MAX(Exposure) AS maximum
        FROM raw_freq
    """)
    show(con, "répartition des valeurs hors intervalle", """
        SELECT
            CASE
                WHEN Exposure <= 0 THEN 'a) <= 0'
                WHEN Exposure <= 1.1 THEN 'b) ]1 ; 1,1]'
                WHEN Exposure <= 1.5 THEN 'c) ]1,1 ; 1,5]'
                WHEN Exposure <= 2 THEN 'd) ]1,5 ; 2]'
                ELSE 'e) > 2'
            END AS tranche,
            COUNT(*) AS contrats,
            SUM(ClaimNb)::BIGINT AS somme_claimnb,
            MIN(Exposure) AS minimum,
            MAX(Exposure) AS maximum
        FROM raw_freq
        WHERE Exposure <= 0 OR Exposure > 1
        GROUP BY tranche
        ORDER BY tranche
    """)

    print("\n=== 5. Montants de sinistres <= 0")
    show(con, "volume", """
        SELECT
            COUNT(*) FILTER (WHERE ClaimAmount IS NULL) AS nuls,
            COUNT(*) FILTER (WHERE ClaimAmount < 0) AS negatifs,
            COUNT(*) FILTER (WHERE ClaimAmount = 0) AS egaux_a_0,
            COUNT(*) FILTER (WHERE ClaimAmount > 0) AS positifs
        FROM raw_sev
    """)
    show(con, "distribution des montants <= 0 (valeur par valeur)", """
        SELECT ClaimAmount AS montant, COUNT(*) AS lignes
        FROM raw_sev
        WHERE ClaimAmount <= 0
        GROUP BY ClaimAmount
        ORDER BY ClaimAmount
    """)
    show(con, "pour comparaison : distribution de tous les montants", """
        SELECT
            MIN(ClaimAmount) AS minimum,
            quantile_cont(ClaimAmount, 0.01) AS p01,
            quantile_cont(ClaimAmount, 0.25) AS p25,
            median(ClaimAmount) AS mediane,
            ROUND(AVG(ClaimAmount), 2) AS moyenne,
            quantile_cont(ClaimAmount, 0.75) AS p75,
            quantile_cont(ClaimAmount, 0.99) AS p99,
            MAX(ClaimAmount) AS maximum
        FROM raw_sev
    """)

    con.close()


if __name__ == "__main__":
    main()
