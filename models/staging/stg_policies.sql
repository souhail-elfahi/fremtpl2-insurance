-- Une ligne par contrat, comme raw_freq : on type et on signale, sans filtrer, joindre ni agréger.
select
    cast(IDpol as bigint) as IDpol,
    ClaimNb,

    -- CASE plutôt que LEAST : LEAST(NULL, 1) vaut 1 dans DuckDB
    Exposure as exposure,
    case when Exposure > 1 then 1.0 else Exposure end as exposure_capped,
    Exposure > 1 as exposure_flag,  -- vrai si l'exposition a été plafonnée

    Area,
    VehPower,
    VehAge,
    DrivAge,
    BonusMalus,
    VehBrand,
    VehGas,
    Density,
    Region
from {{ source('raw', 'raw_freq') }}
