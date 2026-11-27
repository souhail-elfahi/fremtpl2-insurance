-- Une ligne par contrat : stg_policies enrichi des montants de sinistres.

with seuil as (
    -- V1 PROVISOIRE : plafond = p99 de tous les montants (orphelins inclus), recalculé à chaque run
    select quantile_cont(ClaimAmount, 0.99) as plafond
    from {{ ref('stg_claims') }}
),

claims as (
    -- écrêtage sinistre par sinistre ; CASE plutôt que LEAST pour ne pas remplacer un NULL par le plafond
    select
        c.IDpol,
        c.ClaimAmount,
        case when c.ClaimAmount > s.plafond then s.plafond else c.ClaimAmount end as amount_capped
    from {{ ref('stg_claims') }} as c
    cross join seuil as s
),

claims_by_policy as (
    -- agrégation AVANT la jointure : au plus une ligne par IDpol
    select
        IDpol,
        count(*) as n_amount_lines,
        sum(ClaimAmount) as total_amount,
        sum(amount_capped) as total_amount_capped
    from claims
    group by IDpol
)

select
    p.*,
    coalesce(c.n_amount_lines, 0) as n_amount_lines,
    c.total_amount,         -- NULL = aucun montant observé (pas un coût de 0)
    c.total_amount_capped,
    p.ClaimNb > 0 and c.IDpol is not null as has_amount
from {{ ref('stg_policies') }} as p
left join claims_by_policy as c
    on p.IDpol = c.IDpol
