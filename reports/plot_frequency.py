"""Fréquence des sinistres par tranche d'âge du conducteur. Lit le mart en lecture seule."""
import sys
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")  # écrit un fichier image, sans ouvrir de fenêtre

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MultipleLocator

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "fremtpl2.duckdb"
OUT_PATH = ROOT / "reports" / "frequency_by_driver_age.png"

SQL = """
SELECT
    CASE
        WHEN DrivAge BETWEEN 18 AND 25 THEN '18-25'
        WHEN DrivAge BETWEEN 26 AND 35 THEN '26-35'
        WHEN DrivAge BETWEEN 36 AND 50 THEN '36-50'
        WHEN DrivAge BETWEEN 51 AND 65 THEN '51-65'
        WHEN DrivAge >= 66 THEN '66+'
    END AS tranche,
    COUNT(*) AS contrats,
    SUM(ClaimNb)::BIGINT AS sinistres,
    SUM(exposure_capped) AS exposition,
    SUM(ClaimNb) / SUM(exposure_capped) AS frequence
FROM mart_policy_claims
GROUP BY tranche
ORDER BY MIN(DrivAge)
"""


def nombre(valeur: float, decimales: int = 0) -> str:
    """Format français : espace pour les milliers, virgule décimale."""
    return f"{valeur:,.{decimales}f}".replace(",", " ").replace(".", ",")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute(SQL).df()
    con.close()

    # un âge nul ou inférieur à 18 ans tomberait hors des tranches : on s'arrête plutôt que de l'ignorer
    if df["tranche"].isna().any():
        raise ValueError("Des contrats ont un âge hors des tranches prévues.")

    # moyenne du portefeuille : rapport des totaux, et non moyenne des cinq fréquences
    moyenne = df["sinistres"].sum() / df["exposition"].sum()

    fig, ax = plt.subplots(figsize=(9, 5.5))
    barres = ax.bar(df["tranche"], df["frequence"], color="#6b8299", width=0.65)
    ax.axhline(
        moyenne,
        color="#333333",
        linestyle="--",
        linewidth=1.2,
        label=f"Moyenne du portefeuille : {nombre(moyenne, 4)}",
    )
    # valeurs écrites dans les barres, pour ne pas croiser la ligne de moyenne
    ax.bar_label(
        barres,
        labels=[nombre(f, 3) for f in df["frequence"]],
        label_type="center",
        color="white",
        fontweight="bold",
    )

    # l'exposition de chaque tranche est écrite sous l'axe
    ax.set_xticks(
        range(len(df)),
        [f"{t} ans\nExposition :\n{nombre(e)}" for t, e in zip(df["tranche"], df["exposition"])],
    )
    ax.set_xlabel("Âge du conducteur (exposition en années d'assurance)", labelpad=10)
    ax.set_ylabel("Sinistres par année d'assurance")
    ax.set_title("Fréquence des sinistres selon l'âge du conducteur", pad=12)
    ax.yaxis.set_major_locator(MultipleLocator(0.02))  # graduations exactes à 2 décimales
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: nombre(v, 2)))
    ax.set_ylim(0, df["frequence"].max() * 1.15)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)

    fig.tight_layout()
    fig.savefig(OUT_PATH, dpi=150)
    plt.close(fig)

    print(df.to_string(index=False))
    print(f"\nMoyenne du portefeuille : {moyenne:.4f}")
    print(
        f"Totaux : {df['contrats'].sum()} contrats, {df['sinistres'].sum()} sinistres, "
        f"exposition {df['exposition'].sum():.2f}"
    )
    print(f"Graphique : {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
