-- Indicateurs de synthèse. Analyse dbt : compilée, mais aucune table ni vue n'est créée.
-- Lancer : .venv\Scripts\dbt.exe show --select indicateurs --limit 50 --output json

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

-- sinistres au-dessus du seuil, limités aux contrats du mart
ecretes as (
    select count(*) as n
    from {{ ref('stg_claims') }} as c
    where c.ClaimAmount > (select p99 from seuil)
      and exists (
          select 1 from mart as m where m.IDpol = c.IDpol
      )
),

-- fréquence par âge : mêmes tranches que reports/plot_frequency.py
ages as (
    select
        case
            when DrivAge between 18 and 25 then 1
            when DrivAge between 26 and 35 then 2
            when DrivAge between 36 and 50 then 3
            when DrivAge between 51 and 65 then 4
            when DrivAge >= 66 then 5
        end as rang,
        sum(ClaimNb) / sum(exposure_capped) as frequence,
        sum(exposure_capped) as expo
    from mart
    group by rang
),

tranches (rang, libelle) as (
    values (1, '18-25'), (2, '26-35'), (3, '36-50'), (4, '51-65'), (5, '66+')
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
    union all select 17, 'sinistres avec montant', lignes_montant from a
    union all select 18, 'sinistres ecretes au p99', n from ecretes
    union all select 19, 'sinistres avec montant non ecretes', a.lignes_montant - ecretes.n from a, ecretes
    union all select 20, 'annees d exposition (plafonnee)', expo from a
    union all select 20 + rang, 'frequence ' || libelle, frequence from ages join tranches using (rang)
    union all select 30 + rang, 'exposition ' || libelle, expo from ages join tranches using (rang)
    union all select 41, 'part de sinistres chiffres, minimum par segment (%)',
        min(100.0 * n_sinistres_chiffres / n_sinistres) from {{ ref('mart_segments') }}
    union all select 42, 'part de sinistres chiffres, maximum par segment (%)',
        max(100.0 * n_sinistres_chiffres / n_sinistres) from {{ ref('mart_segments') }}
    -- sinistres sans montant supposés semblables aux autres À L'INTÉRIEUR de chaque modalité, une variable à la fois
    union all select 43, 'prime pure, manque au hasard par segment, minimum', min(prime) from (
        select sum(n_sinistres * cout_moyen_observe) / sum(exposition) as prime
        from {{ ref('mart_segments') }} group by variable) as p
    union all select 44, 'prime pure, manque au hasard par segment, maximum', max(prime) from (
        select sum(n_sinistres * cout_moyen_observe) / sum(exposition) as prime
        from {{ ref('mart_segments') }} group by variable) as p
)

select ordre, indicateur, round(valeur, 4) as valeur
from resultats
order by ordre
