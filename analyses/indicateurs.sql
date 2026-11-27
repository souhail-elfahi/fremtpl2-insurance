-- Indicateurs de synthèse. Analyse dbt : compilée, mais aucune table ni vue n'est créée.
-- Lancer : .venv\Scripts\dbt.exe show --select indicateurs --limit 20 --output json

with mart as (
    select
        *,
        has_amount or ClaimNb = 0 as montant_connu  -- exclut les sinistrés sans montant
    from {{ ref('mart_policy_claims') }}
),

a as (
    select
        count(*) as lignes_mart,
        sum(ClaimNb) as claimnb,
        sum(exposure_capped) as expo,
        sum(total_amount) as brut,
        sum(total_amount_capped) as ecrete,
        sum(n_amount_lines) as lignes_montant,
        sum(total_amount) filter (where montant_connu) as brut_connu,
        sum(exposure_capped) filter (where montant_connu) as expo_connu
    from mart
),

primes as (
    select
        (claimnb / expo) * (brut / lignes_montant) as prime_tous,
        brut_connu / expo_connu as prime_connu
    from a
),

-- même population que le seuil du mart : toutes les lignes de stg_claims
seuil as (
    select quantile_cont(ClaimAmount, 0.99) as p99, count(*) as lignes
    from {{ ref('stg_claims') }}
),

orphelins as (
    select count(distinct c.IDpol) as idpol
    from {{ ref('stg_claims') }} as c
    where not exists (
        select 1 from {{ ref('stg_policies') }} as p where p.IDpol = c.IDpol
    )
),

-- médiane par sinistre, orphelins exclus (même population que les coûts moyens)
mediane as (
    select median(c.ClaimAmount) as montant
    from {{ ref('stg_claims') }} as c
    where exists (
        select 1 from mart as m where m.IDpol = c.IDpol
    )
),

resultats as (
    select 1 as ordre, 'seuil p99' as indicateur, p99 as valeur from seuil
    union all select 2, 'population du p99 (lignes)', lignes from seuil
    union all select 3, 'cout moyen brut', brut / lignes_montant from a
    union all select 4, 'cout moyen ecrete p99', ecrete / lignes_montant from a
    union all select 5, 'cout moyen, sans montant = 0', brut / claimnb from a
    union all select 6, 'prime pure : frequence x cout observe', prime_tous from primes
    union all select 7, 'prime pure : has_amount ou sans sinistre', prime_connu from primes
    union all select 8, 'ecart 7 vs 6 (%)', 100 * (prime_connu / prime_tous - 1) from primes
    union all select 9, 'lignes du mart', lignes_mart from a
    union all select 10, 'IDpol orphelins', idpol from orphelins
    union all select 11, 'sinistres declares', claimnb from a
    union all select 12, 'sinistres declares sans montant', claimnb - lignes_montant from a
    union all select 13, 'frequence', claimnb / expo from a
    union all select 14, 'cout median par sinistre', montant from mediane
    union all select 15, 'prime pure, sans montant = 0', brut / expo from a
    union all select 16, 'montant retire par ecretement (%)', 100 * (brut - ecrete) / brut from a
)

select ordre, indicateur, round(valeur, 4) as valeur
from resultats
order by ordre
