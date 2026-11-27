-- Une ligne par sinistre, comme raw_sev. Les sinistres orphelins sont conservés.
select
    cast(IDpol as bigint) as IDpol,
    ClaimAmount
from {{ source('raw', 'raw_sev') }}
