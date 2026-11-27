"""GLM de fréquence : Poisson avec offset, surdispersion, comparaisons, relativités et calibration.

Écrit reports/freq_glm.md et reports/freq_calibration.png.
"""
import re
import sys

import matplotlib

matplotlib.use("Agg")

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from matplotlib.ticker import FuncFormatter
from sklearn.metrics import mean_poisson_deviance

from data import AUTRES, CATEGORIELLES, DB_PATH, EXPOSITION_MIN, ROOT, TRANCHES, construire

SEUIL_SURDISPERSION = 1.2  # au-delà, la surdispersion est jugée nette
Z95 = 1.959964
RAPPORT = ROOT / "reports" / "freq_glm.md"
GRAPHIQUE = ROOT / "reports" / "freq_calibration.png"
JEUNES = "DrivAge=18-25"


def fr(valeur: float, decimales: int = 0) -> str:
    """Format français : espace pour les milliers, virgule décimale."""
    return f"{valeur:,.{decimales}f}".replace(",", " ").replace(".", ",")


def matrice(x: pd.DataFrame, jeu, sans: tuple = ()) -> pd.DataFrame:
    """Une colonne 0/1 par modalité, sauf la référence, plus la constante et log(Density)."""
    colonnes = {"constante": np.ones(len(x)), "log_density": x["log_density"].to_numpy()}
    for nom in CATEGORIELLES:
        if nom in sans:
            continue
        for modalite in jeu.niveaux[nom]:
            if modalite != jeu.references[nom]:
                colonnes[f"{nom}={modalite}"] = (x[nom] == modalite).to_numpy(dtype=float)
    return pd.DataFrame(colonnes, index=x.index)


def relativite(coef: pd.Series, erreur: pd.Series, nom: str) -> tuple:
    c, e = coef[nom], erreur[nom]
    return np.exp(c), np.exp(c - Z95 * e), np.exp(c + Z95 * e)


def texte_rel(triplet: tuple) -> tuple:
    r, bas, haut = triplet
    return fr(r, 3), f"{fr(bas, 3)} à {fr(haut, 3)}"


def ordonner(nom: str, modalites: list) -> list:
    """Ordre de lecture : celui des tranches, sinon tri des nombres par valeur ; « autres » en dernier."""
    if nom in TRANCHES:
        rang = {libelle: i for i, libelle in enumerate(TRANCHES[nom][1])}
        return sorted(modalites, key=lambda m: (m == AUTRES, rang.get(m, 0)))
    return sorted(modalites, key=lambda m: (m == AUTRES, [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", m)]))


def deciles_exposition(prediction: np.ndarray, exposition: np.ndarray) -> np.ndarray:
    """Dix groupes d'exposition égale, rangés par fréquence prédite croissante."""
    ordre = np.argsort(prediction / exposition, kind="stable")
    milieu = (np.cumsum(exposition[ordre]) - exposition[ordre] / 2) / exposition.sum()
    decile = np.empty(len(ordre), dtype=int)
    decile[ordre] = np.clip((milieu * 10).astype(int) + 1, 1, 10)
    return decile


def tableau(entetes: list, lignes: list, texte: int = 1) -> str:
    alignement = ["---"] * texte + ["---:"] * (len(entetes) - texte)
    return "\n".join("| " + " | ".join(map(str, l)) + " |" for l in [entetes, alignement, *lignes])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    jeu = construire()
    train, test = jeu.train, jeu.test
    m_train, m_test = matrice(jeu.x_train, jeu), matrice(jeu.x_test, jeu)
    y_train, y_test = train["ClaimNb"].to_numpy(float), test["ClaimNb"].to_numpy(float)
    e_train, e_test = train["exposure_capped"].to_numpy(), test["exposure_capped"].to_numpy()
    off_train, off_test = np.log(e_train), np.log(e_test)

    # 1. Poisson
    poisson = sm.GLM(y_train, m_train, family=sm.families.Poisson(), offset=off_train).fit()
    if not poisson.converged:
        raise RuntimeError("Le GLM Poisson n'a pas convergé.")
    phi = poisson.pearson_chi2 / poisson.df_resid
    residus = (y_train - poisson.mu) ** 2 / poisson.mu
    part_top = np.sort(residus)[-100:].sum() / residus.sum()
    print(f"Poisson ajusté : {len(train)} contrats, {m_train.shape[1]} paramètres, phi = {phi:.4f}", flush=True)

    # 2. quasi-Poisson et binomiale négative si la surdispersion est nette
    quasi = nb = None
    if phi > SEUIL_SURDISPERSION:
        quasi = sm.GLM(y_train, m_train, family=sm.families.Poisson(), offset=off_train).fit(scale="X2")
        depart = np.r_[poisson.params.to_numpy(), 1.0]
        modele_nb = sm.NegativeBinomial(y_train, m_train, offset=off_train, loglike_method="nb2")
        nb = modele_nb.fit(start_params=depart, method="newton", maxiter=100, disp=False)
        if not nb.mle_retvals["converged"]:
            raise RuntimeError("La binomiale négative n'a pas convergé.")
        print(f"Binomiale négative ajustée : alpha = {nb.params['alpha']:.4f}", flush=True)

    # 3. déviance de Poisson sur le test, en nombres de sinistres
    predictions = {
        "Baseline (fréquence moyenne du train)": jeu.baseline["frequence"] * e_test,
        "GLM Poisson": np.exp(m_test.to_numpy() @ poisson.params.to_numpy() + off_test),
    }
    if nb is not None:
        predictions["GLM quasi-Poisson"] = np.exp(m_test.to_numpy() @ quasi.params.to_numpy() + off_test)
        predictions["GLM binomiale négative"] = np.exp(
            m_test.to_numpy() @ nb.params[m_train.columns].to_numpy() + off_test)
    deviances = {nom: mean_poisson_deviance(y_test, mu) for nom, mu in predictions.items()}
    base = deviances["Baseline (fréquence moyenne du train)"]

    ajustements = {"GLM Poisson": (poisson, poisson.aic)}
    if nb is not None:
        ajustements |= {"GLM quasi-Poisson": (quasi, None), "GLM binomiale négative": (nb, nb.aic)}
    comparaison = []
    for nom, mu in predictions.items():
        ligne = [nom, fr(deviances[nom], 6), "référence" if nom.startswith("Baseline") else f"{fr(100 * (1 - deviances[nom] / base), 2)} %",
                 fr(mu.sum())]
        modele, aic = ajustements.get(nom, (None, None))
        if modele is None:
            ligne += ["", ""]
        else:
            ligne += [" ".join(texte_rel(relativite(modele.params, modele.bse, JEUNES))[:1])
                      + f" ({texte_rel(relativite(modele.params, modele.bse, JEUNES))[1]})",
                      "non définie" if aic is None else fr(aic)]
        comparaison.append(ligne)

    # 4. relativités
    lignes_rel = []
    for nom in CATEGORIELLES:
        for modalite in ordonner(nom, jeu.niveaux[nom]):
            masque = (jeu.x_train[nom] == modalite).to_numpy()
            debut = [nom, modalite, fr(e_train[masque].sum()), fr(y_train[masque].sum())]
            if modalite == jeu.references[nom]:
                fin = ["1,000", "référence", "référence"] + (["1,000", "référence"] if nb is not None else [])
            else:
                col = f"{nom}={modalite}"
                r, ic = texte_rel(relativite(poisson.params, poisson.bse, col))
                fin = [r, ic, texte_rel(relativite(quasi.params, quasi.bse, col))[1] if quasi is not None else ""]
                if nb is not None:
                    fin += list(texte_rel(relativite(nb.params, nb.bse, col)))
            lignes_rel.append(debut + fin)
    r, ic = texte_rel(relativite(poisson.params, poisson.bse, "log_density"))
    fin = [r, ic, texte_rel(relativite(quasi.params, quasi.bse, "log_density"))[1] if quasi is not None else ""]
    if nb is not None:
        fin += list(texte_rel(relativite(nb.params, nb.bse, "log_density")))
    lignes_rel.append(["log(Density)", "par unité", fr(e_train.sum()), fr(y_train.sum())] + fin)

    # 5. calibration sur le test (Poisson)
    mu = predictions["GLM Poisson"]
    decile = deciles_exposition(mu, e_test)
    cal = pd.DataFrame({"decile": decile, "expo": e_test, "obs": y_test, "pred": mu}).groupby("decile").agg(
        contrats=("expo", "size"), expo=("expo", "sum"), obs=("obs", "sum"), pred=("pred", "sum"))
    cal["f_obs"], cal["f_pred"] = cal["obs"] / cal["expo"], cal["pred"] / cal["expo"]
    lignes_cal = [[d, fr(l.contrats), fr(l.expo), fr(l.obs), fr(l.pred), fr(l.f_obs, 4), fr(l.f_pred, 4), fr(l.obs / l.pred, 3)]
                  for d, l in zip(cal.index, cal.itertuples())]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(cal.index, cal["f_pred"], marker="o", color="#1F4E9C", label="Prédite")
    ax.plot(cal.index, cal["f_obs"], marker="s", color="#B3261E", linestyle="--", label="Observée")
    ax.set_title("Calibration du GLM Poisson sur le test", pad=12)
    ax.set_xlabel("Décile de fréquence prédite (exposition égale)")
    ax.set_ylabel("Sinistres par année d'exposition")
    ax.set_xticks(range(1, 11))
    ax.set_ylim(0, max(cal["f_obs"].max(), cal["f_pred"].max()) * 1.12)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fr(v, 2)))
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(GRAPHIQUE, dpi=150)
    plt.close(fig)

    # 6. effet « 18-25 ans » : GLM contre univarié, à référence identique
    ref_age = jeu.references["DrivAge"]
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        uni = {m: (f, r) for m, f, r in con.execute(
            "SELECT modalite, frequence, relativite_frequence FROM mart_segments WHERE variable = 'DrivAge'").fetchall()}
    uni_meme_ref = uni["18-25"][0] / uni[ref_age][0]
    glm_jeunes = texte_rel(relativite(poisson.params, poisson.bse, JEUNES))
    # diagnostic : le même GLM sans BonusMalus
    sans_bm = sm.GLM(y_train, matrice(jeu.x_train, jeu, sans=("BonusMalus",)), family=sm.families.Poisson(),
                     offset=off_train).fit()
    glm_sans_bm = texte_rel(relativite(sans_bm.params, sans_bm.bse, JEUNES))
    ligne_jeunes = (
        f"18-25 ans contre {ref_age} ans : GLM {glm_jeunes[0]} (IC Poisson {glm_jeunes[1]}), univarié {fr(uni_meme_ref, 3)} "
        f"({fr(uni['18-25'][1], 2)} par rapport au portefeuille) ; GLM sans BonusMalus : {glm_sans_bm[0]}.")

    entetes_rel = ["Variable", "Modalité", "Exposition train", "Sinistres train", "Relativité", "IC 95 % Poisson", "IC 95 % quasi-Poisson"]
    if nb is not None:
        entetes_rel += ["Relativité binomiale négative", "IC 95 % binomiale négative"]
    regroupees = " ; ".join(f"{k} : {', '.join(v)}" for k, v in jeu.regroupees.items()) or "aucune"

    rapport = f"""# GLM de fréquence

Fichier produit par `modeling/freq_glm.py`. Train : {fr(len(train))} contrats ; test : {fr(len(test))} contrats.
Découpage par profil tarifaire (graine 42). Offset : log de l'exposition plafonnée.

Modalités sous {fr(EXPOSITION_MIN)} années d'exposition dans le train, regroupées dans « autres » : {regroupees}.

## Surdispersion

Pearson chi2 / degrés de liberté = **{fr(phi, 3)}** (seuil retenu : {fr(SEUIL_SURDISPERSION, 1)}).
Les 100 plus grands résidus du train portent {fr(100 * part_top, 1)} % du chi2.
{"Quasi-Poisson : mêmes coefficients, erreurs types multipliées par " + fr(np.sqrt(phi), 3) + ". Binomiale négative (NB2) : alpha = " + fr(nb.params["alpha"], 3) + "." if nb is not None else "Surdispersion non nette : seule la Poisson est ajustée."}

## Comparaison sur le test

{tableau(["Modèle", "Déviance Poisson moyenne", "Gain face à la baseline", "Sinistres prédits", "Relativité 18-25 (IC 95 %)", "AIC (train)"], comparaison)}

Sinistres observés sur le test : {fr(y_test.sum())}.

## Effet de l'âge

{ligne_jeunes}

## Calibration par décile (GLM Poisson, test)

![Calibration](freq_calibration.png)

{tableau(["Décile", "Contrats", "Exposition", "Observés", "Prédits", "Fréquence observée", "Fréquence prédite", "Observé / prédit"], lignes_cal)}

## Relativités

Références : la modalité la plus exposée du train. `Area` et `log(Density)` sont très corrélées : leurs relativités
ne s'interprètent pas séparément. Les intervalles supposent des contrats indépendants.

{tableau(entetes_rel, lignes_rel, texte=2)}
"""
    RAPPORT.write_text(rapport, encoding="utf-8", newline="\n")
    print(rapport)
    print(f"Écrit : {RAPPORT.relative_to(ROOT)} et {GRAPHIQUE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
