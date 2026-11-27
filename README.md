# Assurance auto : sinistralité freMTPL2

Registre des décisions du projet : ce qui a été constaté dans les données, ce qui a été décidé, et les limites des résultats.

## Question métier

Quelle prime pure, c'est-à-dire quel coût attendu des sinistres par année d'exposition, ressort du portefeuille ?

**Prime pure = fréquence × coût moyen**

- Fréquence : sinistres déclarés / années d'exposition.
- Coût moyen : montant des sinistres / nombre de sinistres chiffrés.

Le calcul porte sur le portefeuille entier, sans segmentation ni modèle statistique à ce stade.

## Stack

| Outil | Rôle |
|---|---|
| Python | Chargement des données (`ingest.py`, avec scikit-learn) et audit (`checks.py`) |
| DuckDB | Base locale `data/fremtpl2.duckdb` |
| dbt (`dbt-duckdb`) | Transformations, tests et requête d'indicateurs |
| SQL | Modèles, tests et contrôles |

Versions figées dans `requirements.txt`. Développé avec Python 3.13.2.

## Chaîne de traitement

```
OpenML (41214 : contrats, 41215 : sinistres)
  │  ingest.py
  ▼
DuckDB : raw_freq, raw_sev                      ◄── checks.py (audit en lecture seule)
  │  dbt run
  ▼
Staging (vues) : stg_policies, stg_claims
  │
  ▼
Mart (table) : mart_policy_claims, une ligne par contrat
  │
  ▼
Indicateurs : analyses/indicateurs.sql
```

Le staging type et signale, sans jointure ni agrégation. Le mart agrège les sinistres par `IDpol`, puis fait un `LEFT JOIN` depuis les contrats : il compte 678 013 lignes.

## Audit qualité

Les données brutes contiennent 678 013 contrats et 26 639 lignes de sinistres.

| Constat | Décision | Impact |
|---|---|---|
| **6 polices orphelines** : 195 sinistres sans contrat, soit 1,3 % des montants | Conservés dans le staging, absents du mart. Signalés par un test en avertissement. | Exclus de la fréquence, du coût moyen et de la prime pure. Inclus dans le calcul du seuil d'écrêtement. |
| **9 116 contrats sinistrés sur 34 060 sans montant** (26,8 %). Avec un sinistre non chiffré sur un autre contrat, **9 658 sinistres sur 36 102** n'ont pas de montant. | Montant `NULL` (inconnu) pour ces 9 116 contrats et 0 pour les contrats sans sinistre. `has_amount` signale les contrats sinistrés chiffrés. | Les sinistres restent comptés dans la fréquence. La prime pure dépend de l'hypothèse faite sur leur coût. |
| **1 224 expositions > 1** | Contrats conservés. Valeur brute gardée (`exposure`), version plafonnée à 1 à part (`exposure_capped`), signalement (`exposure_flag`). | La fréquence et la prime pure utilisent `exposure_capped`. |

## Résultats

Note : montants dans l'unité monétaire de la source (non précisée par OpenML).

| Indicateur | Valeur |
|---|---|
| Fréquence (sinistres par année d'exposition) | **0,1007** |
| Coût moyen observé par sinistre chiffré | **2 265,51** |
| Coût médian par sinistre chiffré | **1 172** |
| Prime pure par année d'exposition | **de 167 à 228** |

### Lire la fourchette de prime pure

| Scénario | Hypothèse sur les sinistres sans montant | Prime pure |
|---|---|---|
| Manquants à 0 | Ils ne coûtent rien. | 167 |
| Manquants au hasard | Ils coûtent en moyenne autant que les sinistres chiffrés. | 228 |

**L'hypothèse « manquants au hasard » n'est pas démontrée.** La fourchette compare deux scénarios, ce n'est pas un intervalle de confiance. Sur ce périmètre, 167 est un plancher puisqu'un montant ne peut pas être négatif. En revanche, 228 n'est pas un plafond : des sinistres manquants plus coûteux que la moyenne donneraient davantage.

### Écrêtement des gros sinistres

Plafonner chaque sinistre au p99 (16 793,70) **retire 30,6 % du montant** du mart. Cet excédent **n'est pas encore mutualisé**, c'est-à-dire pas réparti sur l'ensemble des contrats. La fourchette ci-dessus est donc calculée sur les montants bruts.

Le seuil est **provisoire** : il est calculé sur les 26 639 lignes de sinistres, orphelines comprises, et recalculé à chaque `dbt run`.

### Origine des chiffres

- Audit : `checks.py`.
- Résultats : `analyses/indicateurs.sql`, après `dbt run` :

```powershell
.venv\Scripts\dbt.exe show --select indicateurs --limit 20 --output json
```

## Tests dbt

10 tests. Un test dbt passe quand sa requête ne renvoie aucune ligne.

| Test | Vérifie | Résultat attendu |
|---|---|---|
| `unique_stg_policies_IDpol` | `IDpol` unique dans les contrats | Succès |
| `not_null_stg_policies_IDpol` | `IDpol` renseigné dans les contrats | Succès |
| `strictly_positive_stg_policies_exposure` | Exposition renseignée et > 0 | Succès |
| `not_null_stg_claims_IDpol` | `IDpol` renseigné dans les sinistres | Succès |
| `strictly_positive_stg_claims_ClaimAmount` | Montant renseigné et > 0 | Succès |
| `relationships_stg_claims_IDpol__IDpol__ref_stg_policies_` | Chaque sinistre a un contrat | **Avertissement** : 195 lignes, 6 `IDpol` |
| `unique_mart_policy_claims_IDpol` | Une ligne par contrat dans le mart | Succès |
| `not_null_mart_policy_claims_IDpol` | `IDpol` renseigné dans le mart | Succès |
| `assert_total_amount_null_ssi_sinistre_sans_montant` | Montants `NULL` si et seulement si contrat sinistré sans ligne de montant | Succès |
| `assert_claimnb_matches_amount_lines` | `ClaimNb` égal au nombre de lignes pour les contrats avec `has_amount` | **Avertissement** : 1 contrat |

Bilan attendu : `PASS=8 WARN=2 ERROR=0`.

## Reproduire

Dans PowerShell, depuis la racine du projet. Le chargement des données demande un accès à internet.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe ingest.py
.venv\Scripts\python.exe checks.py
.venv\Scripts\dbt.exe run
.venv\Scripts\dbt.exe test
```

La connexion dbt est décrite dans `profiles.yml`, à la racine. Son chemin vers la base est relatif : lancer les commandes depuis ce dossier.

## Prochaines étapes (V1)

Rien de ce qui suit n'est réalisé.

- **Modèles :** GLM Poisson pour la fréquence (avec le logarithme de l'exposition en offset) et GLM Gamma pour le coût.
- **Données manquantes :** tester l'hypothèse de manque par une régression logistique (logit). Ce test peut montrer que le manque dépend des variables observées, mais pas prouver qu'il est indépendant du montant inconnu.
- **Gros sinistres :** justifier le seuil d'écrêtement et mutualiser l'excédent.
- **Restitution :** tableau de bord Power BI.
