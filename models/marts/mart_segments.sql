-- Une ligne par variable de segmentation et par modalité.
-- Pour chaque variable, les modalités se partagent tout le portefeuille.

{% set variables = ['DrivAge', 'BonusMalus', 'VehAge', 'VehPower', 'Area', 'Region', 'VehGas', 'VehBrand'] %}

with contrats as (
    select
        case
            when DrivAge between 18 and 25 then '18-25'
            when DrivAge between 26 and 35 then '26-35'
            when DrivAge between 36 and 50 then '36-50'
            when DrivAge between 51 and 65 then '51-65'
            when DrivAge >= 66 then '66+'
        end as DrivAge,
        case
            when BonusMalus = 50 then '50'
            when BonusMalus between 51 and 75 then '51-75'
            when BonusMalus between 76 and 100 then '76-100'
            when BonusMalus > 100 then '>100'
        end as BonusMalus,
        case
            when VehAge = 0 then '0'
            when VehAge between 1 and 4 then '1-4'
            when VehAge between 5 and 9 then '5-9'
            when VehAge >= 10 then '10+'
        end as VehAge,
        cast(VehPower as varchar) as VehPower,
        cast(Area as varchar) as Area,
        cast(Region as varchar) as Region,
        trim(VehGas, '''') as VehGas,  -- la source entoure les valeurs d'apostrophes
        cast(VehBrand as varchar) as VehBrand,
        ClaimNb,
        exposure_capped,
        total_amount,
        n_amount_lines
    from {{ ref('mart_policy_claims') }}
),

-- format long : une copie du portefeuille par variable
modalites as (
    {% for v in variables %}
    select
        '{{ v }}' as variable,
        {{ v }} as modalite,
        ClaimNb, exposure_capped, total_amount, n_amount_lines
    from contrats
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),

-- on ne somme que des quantités ; les ratios sont calculés ensuite
sommes as (
    select
        variable,
        modalite,
        count(*) as n_contrats,
        sum(exposure_capped) as exposition,
        sum(ClaimNb)::bigint as n_sinistres,
        sum(n_amount_lines)::bigint as n_sinistres_chiffres,
        sum(total_amount) as montant  -- montants bruts, non écrêtés
    from modalites
    group by variable, modalite
),

portefeuille as (
    select sum(ClaimNb) / sum(exposure_capped) as frequence
    from {{ ref('mart_policy_claims') }}
)

select
    s.variable,
    s.modalite,
    s.n_contrats,
    s.exposition,
    s.n_sinistres,
    s.n_sinistres / s.exposition as frequence,
    s.n_sinistres_chiffres,
    s.montant / nullif(s.n_sinistres_chiffres, 0) as cout_moyen_observe,
    (s.n_sinistres / s.exposition)
        * (s.montant / nullif(s.n_sinistres_chiffres, 0)) as prime_pure,
    (s.n_sinistres / s.exposition) / p.frequence as relativite_frequence,
    s.exposition < 1000 as faible_exposition
from sommes as s
cross join portefeuille as p
