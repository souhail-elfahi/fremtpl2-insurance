"""Socle de modélisation : lecture du mart, découpage train/test, variables tarifaires et références.

Lecture seule : rien n'est écrit dans la base.
"""
import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "fremtpl2.duckdb"

GRAINE = 42
PART_TEST = 0.2
EXPOSITION_MIN = 1000.0  # années d'exposition dans le train, sous lesquelles une modalité va dans « autres »
QUANTILE_ECRETEMENT = 0.99
AUTRES = "autres"

# profil : toutes les variables tarifaires, en valeurs brutes (avant tout découpage en tranches)
PROFIL = ["Area", "VehPower", "VehAge", "DrivAge", "BonusMalus", "VehBrand", "VehGas", "Density", "Region"]
CATEGORIELLES = ["DrivAge", "VehAge", "BonusMalus", "VehPower", "Area", "VehGas", "VehBrand", "Region"]

# mêmes tranches que models/marts/mart_segments.sql ; bornes (a, b] sur des valeurs entières
TRANCHES = {
    "DrivAge": ([17, 25, 35, 50, 65, np.inf], ["18-25", "26-35", "36-50", "51-65", "66+"]),
    "VehAge": ([-1, 0, 4, 9, np.inf], ["0", "1-4", "5-9", "10+"]),
    "BonusMalus": ([49, 50, 75, 100, np.inf], ["50", "51-75", "76-100", ">100"]),
}


@dataclass
class Jeu:
    train: pd.DataFrame    # colonnes brutes du mart
    test: pd.DataFrame
    x_train: pd.DataFrame  # variables préparées, mêmes lignes que train
    x_test: pd.DataFrame
    niveaux: dict          # variable -> modalités présentes dans le train
    references: dict       # variable -> modalité la plus exposée du train
    regroupees: dict       # variable -> modalités envoyées dans « autres »
    seuil: float           # p99 des montants du train
    baseline: dict
    profils: dict


def charger() -> tuple[pd.DataFrame, pd.DataFrame]:
    # ORDER BY indispensable : sans ordre fixe, le tirage avec la même graine pourrait changer
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        contrats = con.execute("""
            SELECT IDpol, ClaimNb, exposure_capped, n_amount_lines, total_amount,
                   Area::VARCHAR AS Area, VehPower, VehAge, DrivAge, BonusMalus,
                   VehBrand::VARCHAR AS VehBrand, trim(VehGas, '''') AS VehGas,
                   Density, Region::VARCHAR AS Region
            FROM mart_policy_claims
            ORDER BY IDpol
        """).df()
        # le mart ne contient que des totaux : le p99 exige le détail sinistre par sinistre
        sinistres = con.execute(
            "SELECT IDpol, ClaimAmount FROM stg_claims ORDER BY IDpol, ClaimAmount"
        ).df()
    return contrats, sinistres


def preparer_variables(contrats: pd.DataFrame) -> pd.DataFrame:
    x = pd.DataFrame(index=contrats.index)
    for nom in CATEGORIELLES:
        if nom in TRANCHES:
            bornes, libelles = TRANCHES[nom]
            x[nom] = pd.cut(contrats[nom], bins=bornes, labels=libelles).astype(object)
        else:
            x[nom] = contrats[nom].astype(str).astype(object)
    if x.isna().any().any():
        raise ValueError("Une valeur tombe hors des tranches prévues.")
    x["log_density"] = np.log(contrats["Density"])
    return x


def decouper(contrats: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    groupes = contrats.groupby(PROFIL, sort=True).ngroup().to_numpy()
    separateur = GroupShuffleSplit(n_splits=1, test_size=PART_TEST, random_state=GRAINE)
    i_train, i_test = next(separateur.split(contrats, groups=groupes))
    if np.intersect1d(groupes[i_train], groupes[i_test]).size:
        raise AssertionError("Un profil se retrouve des deux côtés.")
    return i_train, i_test, groupes


def regrouper_rares(x_train, x_test, exposition_train):
    """Décide à partir du train seul, puis applique la même règle au test."""
    niveaux, references, regroupees = {}, {}, {}
    for nom in CATEGORIELLES:
        expo = exposition_train.groupby(x_train[nom]).sum()
        rares = sorted(expo.index[expo < EXPOSITION_MIN])
        gardees = set(expo.index) - set(rares)
        inconnues = set(x_test[nom]) - set(expo.index)
        if inconnues and not rares:
            raise ValueError(f"{nom} : modalités du test absentes du train : {inconnues}")
        for x in (x_train, x_test):
            x[nom] = x[nom].where(x[nom].isin(gardees), AUTRES)
        expo = exposition_train.groupby(x_train[nom]).sum()
        niveaux[nom] = list(expo.index)
        references[nom] = expo.idxmax()
        if rares:
            regroupees[nom] = rares
    return niveaux, references, regroupees


def construire() -> Jeu:
    contrats, sinistres = charger()
    i_train, i_test, groupes = decouper(contrats)
    x = preparer_variables(contrats)

    train, test = contrats.iloc[i_train].copy(), contrats.iloc[i_test].copy()
    x_train, x_test = x.iloc[i_train].copy(), x.iloc[i_test].copy()
    niveaux, references, regroupees = regrouper_rares(x_train, x_test, train["exposure_capped"])

    # seuil appris sur les sinistres des contrats du train : ni test, ni orphelins (absents du mart)
    montants_train = sinistres.loc[sinistres["IDpol"].isin(train["IDpol"]), "ClaimAmount"]
    seuil = float(montants_train.quantile(QUANTILE_ECRETEMENT))

    # total écrêté au seuil du train : 0 sans sinistre, NaN pour un sinistré sans montant
    ecretes = sinistres.assign(montant=sinistres["ClaimAmount"].clip(upper=seuil))
    totaux = ecretes.groupby("IDpol")["montant"].sum()
    for df in (train, test):
        df["total_ecrete_train"] = df["IDpol"].map(totaux)
        df.loc[df["ClaimNb"] == 0, "total_ecrete_train"] = df["total_ecrete_train"].fillna(0.0)

    frequence = train["ClaimNb"].sum() / train["exposure_capped"].sum()
    lignes = train["n_amount_lines"].sum()
    cout = train["total_amount"].sum() / lignes
    cout_ecrete = train["total_ecrete_train"].sum() / lignes
    baseline = {
        "frequence": frequence,
        "cout_moyen": cout,
        "cout_moyen_ecrete": cout_ecrete,
        "prime_pure": frequence * cout,
        "prime_pure_ecretee": frequence * cout_ecrete,
        "sinistres": int(train["ClaimNb"].sum()),
        "sinistres_chiffres": int(lignes),
        "lignes_ecretees": int((montants_train > seuil).sum()),
    }

    tailles = np.bincount(groupes)
    profils = {
        "total": len(tailles),
        "partages": int((tailles > 1).sum()),
        "contrats_partages": int(tailles[tailles > 1].sum()),
        "plus_grand": int(tailles.max()),
        "train": len(np.unique(groupes[i_train])),
        "test": len(np.unique(groupes[i_test])),
    }
    return Jeu(train, test, x_train, x_test, niveaux, references, regroupees, seuil, baseline, profils)


def verifier_tranches() -> int:
    """Compare les effectifs par modalité (portefeuille entier) à ceux de mart_segments."""
    contrats, _ = charger()
    x = preparer_variables(contrats)
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        mart = con.execute("SELECT variable, modalite, n_contrats FROM mart_segments").df()
    attendu = {(l.variable, l.modalite): l.n_contrats for l in mart.itertuples()}
    obtenu = {(nom, m): n for nom in CATEGORIELLES for m, n in x[nom].value_counts().items()}
    if attendu != obtenu:
        raise AssertionError("Les tranches diffèrent de celles de mart_segments.")
    return len(obtenu)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"Tranches identiques à mart_segments : {verifier_tranches()} couples (variable, modalité)")
    jeu = construire()
    p, b = jeu.profils, jeu.baseline
    n = len(jeu.train) + len(jeu.test)

    print(f"\nProfils distincts : {p['total']} pour {n} contrats")
    print(f"Profils partagés par plusieurs contrats : {p['partages']} ({p['partages'] / p['total']:.1%} des profils)")
    print(f"Contrats dans ces profils : {p['contrats_partages']} ({p['contrats_partages'] / n:.1%}) ; plus grand profil : {p['plus_grand']}")
    print(f"Profils train / test : {p['train']} / {p['test']} ; en commun : 0")

    print("\nDécoupage       contrats     exposition   sinistres   fréquence")
    for nom, df in (("train", jeu.train), ("test", jeu.test)):
        e, s = df["exposure_capped"].sum(), df["ClaimNb"].sum()
        print(f"{nom:10}  {len(df):9} ({len(df) / n:.1%})  {e:10.1f}  {s:9}   {s / e:.5f}")

    print("\nModalités regroupées dans « autres » :", jeu.regroupees or "aucune")
    for nom in jeu.regroupees:
        masque = jeu.x_train[nom] == AUTRES
        print(f"  {nom} : « autres » = {jeu.train.loc[masque, 'exposure_capped'].sum():.1f} années dans le train")
    print("Références :", jeu.references)

    code_zone = jeu.x_train["Area"].map({m: i for i, m in enumerate("ABCDEF")})
    print(f"Corrélation entre Area (codée de A à F) et log(Density), train : {np.corrcoef(code_zone, jeu.x_train['log_density'])[0, 1]:.3f}")

    print(f"\nSeuil p99 du train (sans orphelins) : {jeu.seuil:.2f} ; lignes écrêtées : {b['lignes_ecretees']}")
    print(f"Baseline fréquence : {b['frequence']:.6f} ({b['sinistres']} sinistres, {b['sinistres_chiffres']} chiffrés)")
    print(f"Coût moyen observé : brut {b['cout_moyen']:.2f} ; écrêté {b['cout_moyen_ecrete']:.2f}")
    print(f"Baseline prime pure : brute {b['prime_pure']:.2f} ; écrêtée {b['prime_pure_ecretee']:.2f}")


if __name__ == "__main__":
    main()
