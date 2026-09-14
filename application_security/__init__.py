"""Application-layer cryptographic and authentication measurements.

This package is deliberately additive: legacy ``reports/`` records keep their
existing schema while new evidence and authentication-graph views are derived
at read time.
"""

from application_security.auth_graph import build_auth_graph
from application_security.authentication_surface import analyze_authentication_surface
from application_security.passive_protocol_probe import collect_passive_protocol_metadata
from application_security.password_meter_evaluation import (
    analyze_site_meter_consistency,
    evaluate_paper_metrics,
    kl_divergence,
    offline_kl_by_strategy,
)
from application_security.jose_validation import (
    analyze_jose_metadata,
    inspect_compact_jwt,
    inspect_jwks,
    verify_compact_jwt,
)
from application_security.webauthn_observer import (
    analyze_webauthn_observations,
    collect_webauthn_observations,
    install_webauthn_observer,
)
from application_security.webauthn_safe_interaction import (
    analyze_safe_interaction,
)
from application_security.oidc_discovery import (
    probe_oidc_discovery,
    safe_fetch_json,
    validate_public_https_url,
)
from application_security.recovery_analysis import (
    analyze_recovery_observation,
    collect_recovery_surface,
)
from application_security.qr_lifecycle import (
    analyze_qr_observations,
    collect_qr_lifecycle_sample,
)
from application_security.leaky_forms import (
    analyze_leaky_form_observation,
    run_leaky_forms_safe_interaction,
)
from application_security.experiment_metrics import (
    classification_metrics,
    compare_module_rounds,
    summarize_module_round,
    wilson_interval,
)
from application_security.models import (
    AuthGraph,
    Claim,
    Evidence,
    EvidenceLevel,
    ModuleManifest,
    ModuleResult,
    ResearchReference,
    ScanMode,
    Verdict,
)

__all__ = [
    "AuthGraph",
    "Claim",
    "Evidence",
    "EvidenceLevel",
    "ModuleManifest",
    "ModuleResult",
    "ResearchReference",
    "ScanMode",
    "Verdict",
    "build_auth_graph",
    "analyze_authentication_surface",
    "collect_passive_protocol_metadata",
    "analyze_site_meter_consistency",
    "evaluate_paper_metrics",
    "kl_divergence",
    "offline_kl_by_strategy",
    "analyze_jose_metadata",
    "inspect_compact_jwt",
    "inspect_jwks",
    "verify_compact_jwt",
    "analyze_webauthn_observations",
    "collect_webauthn_observations",
    "install_webauthn_observer",
    "analyze_safe_interaction",
    "probe_oidc_discovery",
    "safe_fetch_json",
    "validate_public_https_url",
    "analyze_recovery_observation",
    "collect_recovery_surface",
    "analyze_qr_observations",
    "collect_qr_lifecycle_sample",
    "analyze_leaky_form_observation",
    "run_leaky_forms_safe_interaction",
    "classification_metrics",
    "compare_module_rounds",
    "summarize_module_round",
    "wilson_interval",
]
