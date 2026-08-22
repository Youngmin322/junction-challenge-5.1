from dataclasses import dataclass

from jellyguard.contracts import ClaimType, DataMode


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    source_class: str
    modes: tuple[DataMode, ...]
    claim_type: ClaimType | None
    optional: bool = False


SOURCE_REGISTRY = {
    item.source_id: item
    for item in (
        SourceDefinition(
            "historical_observation_fixture",
            "observation",
            (DataMode.CACHED,),
            ClaimType.DIRECT_OBSERVATION,
        ),
        SourceDefinition(
            "scenario_seed_synthetic",
            "scenario_seed",
            (DataMode.SYNTHETIC,),
            ClaimType.CONDITIONAL_SCENARIO,
        ),
        SourceDefinition(
            "nifs_jelly_catalog",
            "report_catalog",
            (DataMode.LIVE, DataMode.CACHED),
            ClaimType.REPORT_CATALOG,
        ),
        SourceDefinition(
            "khoa_tw_recent_hanul",
            "point_context",
            (DataMode.LIVE, DataMode.CACHED),
            ClaimType.CONTEXT,
        ),
        SourceDefinition("cached_field", "field", (DataMode.CACHED,), None),
        SourceDefinition("synthetic_field", "field", (DataMode.SYNTHETIC,), None),
        SourceDefinition("khoa_roms_blocked_fixture", "field", (DataMode.CACHED,), None),
        SourceDefinition(
            "nifs_redtide_list",
            "event_context",
            (DataMode.LIVE, DataMode.CACHED),
            ClaimType.CONTEXT,
            True,
        ),
        SourceDefinition(
            "nifs_soo_list",
            "profile_context",
            (DataMode.LIVE, DataMode.CACHED),
            ClaimType.CONTEXT,
            True,
        ),
        SourceDefinition(
            "khoa_hf_current_regression", "field_fixture", (DataMode.CACHED,), None, True
        ),
        SourceDefinition("khoa_roms_live", "field", (DataMode.LIVE,), None, True),
        SourceDefinition(
            "khoa_crnt_fcst_reference",
            "direction_reference",
            (DataMode.LIVE,),
            ClaimType.CONTEXT,
            True,
        ),
        # Genuinely 13 valid HF-radar stations, all south/west of Hanul (nearest ~120 km).
        # Distinct from khoa_hf_current_regression: that source was the rejected "treat
        # the HF grid as a Hanul field" path and is left untouched. This one never claims
        # Hanul coverage -- it is southern/western-coast context, informational only.
        SourceDefinition(
            "khoa_hf_current_reference",
            "direction_reference",
            (DataMode.LIVE,),
            ClaimType.CONTEXT,
            True,
        ),
        SourceDefinition(
            "nifs_jelly_detail2_unverified",
            "report_catalog",
            (DataMode.LIVE,),
            ClaimType.REPORT_CATALOG,
            True,
        ),
    )
}
