"""Canonical primary sources for the application-security measurement layer."""

from application_security.models import ResearchReference


LOGIN_POLICIES_USENIX_2023 = ResearchReference(
    reference_id="al-roomi-login-policies-usenix23",
    title="A Large-Scale Measurement of Website Login Policies",
    venue="USENIX Security",
    year=2023,
    url="https://www.usenix.org/conference/usenixsecurity23/presentation/al-roomi",
)

MFA_RBA_USENIX_2023 = ResearchReference(
    reference_id="gavazzi-mfa-rba-usenix23",
    title="A Study of Multi-Factor and Risk-Based Authentication Availability",
    venue="USENIX Security",
    year=2023,
    url="https://www.usenix.org/conference/usenixsecurity23/presentation/gavazzi",
)

WPSE_USENIX_2018 = ResearchReference(
    reference_id="calzavara-wpse-usenix18",
    title="WPSE: Fortifying Web Protocols via Browser-Side Security Monitoring",
    venue="USENIX Security",
    year=2018,
    url="https://www.usenix.org/conference/usenixsecurity18/presentation/calzavara",
)

QR_LOGIN_USENIX_2025 = ResearchReference(
    reference_id="zhang-qrlogin-usenix25",
    title="Demystifying the (In)Security of QR Code-based Login in Real-world Deployments",
    venue="USENIX Security",
    year=2025,
    url="https://www.usenix.org/conference/usenixsecurity25/presentation/zhang-xin",
)

PASSKEYS_USENIX_2026 = ResearchReference(
    reference_id="jannett-passkeys-usenix26",
    title="The State of Passkeys: Studying the Adoption and Security of Passkeys on the Web",
    venue="USENIX Security",
    year=2026,
    url="https://www.usenix.org/system/files/conference/usenixsecurity26/sec26_prepub_jannett.pdf",
)

FIDO2_IEEE_SP_2023 = ResearchReference(
    reference_id="bindel-fido2-webauthn-ieeesp23",
    title="FIDO2, CTAP 2.1, and WebAuthn 2: Provable Security and Post-Quantum Instantiation",
    venue="IEEE Symposium on Security and Privacy",
    year=2023,
    url="https://ieeexplore.ieee.org/document/10179454/",
)

PASSWORD_METERS_USENIX_2023 = ResearchReference(
    reference_id="wang-password-meters-usenix23",
    title="No Single Silver Bullet: Measuring the Accuracy of Password Strength Meters",
    venue="USENIX Security",
    year=2023,
    url="https://www.usenix.org/conference/usenixsecurity23/presentation/wang-ding-silver-bullet",
)

LEAKY_FORMS_USENIX_2022 = ResearchReference(
    reference_id="senol-leaky-forms-usenix22",
    title="Leaky Forms: A Study of Email and Password Exfiltration Before Form Submission",
    venue="USENIX Security",
    year=2022,
    url="https://www.usenix.org/conference/usenixsecurity22/presentation/senol",
)

PRIVATE_RECOVERY_USENIX_2024 = ResearchReference(
    reference_id="little-private-recovery-usenix24",
    title="Secure Account Recovery for a Privacy-Preserving Web Service",
    venue="USENIX Security",
    year=2024,
    url="https://www.usenix.org/conference/usenixsecurity24/presentation/little",
)

FAPI_IEEE_SP_2019 = ResearchReference(
    reference_id="fett-fapi-ieee-sp19",
    title="An Extensive Formal Security Analysis of the OpenID Financial-Grade API",
    venue="IEEE Symposium on Security and Privacy",
    year=2019,
    url="https://ieeexplore.ieee.org/document/8835218/",
)


NIST_SP_800_63B = ResearchReference(
    reference_id="nist-sp-800-63b",
    title="Digital Identity Guidelines: Authentication and Authenticator Management",
    venue="NIST SP 800-63B",
    year=2025,
    url="https://pages.nist.gov/800-63-4/sp800-63b/authenticators/",
    kind="standard",
)

OAUTH_SECURITY_BCP_RFC9700 = ResearchReference(
    reference_id="oauth-security-bcp-rfc9700",
    title="Best Current Practice for OAuth 2.0 Security",
    venue="RFC 9700",
    year=2025,
    url="https://www.rfc-editor.org/info/rfc9700/",
    kind="standard",
)

OIDC_DISCOVERY_1_0 = ResearchReference(
    reference_id="openid-connect-discovery-1.0-errata2",
    title="OpenID Connect Discovery 1.0 incorporating errata set 2",
    venue="OpenID Final Specification",
    year=2023,
    url="https://openid.net/specs/openid-connect-discovery-1_0.html",
    kind="standard",
)

OAUTH_AS_METADATA_RFC8414 = ResearchReference(
    reference_id="oauth-authorization-server-metadata-rfc8414",
    title="OAuth 2.0 Authorization Server Metadata",
    venue="RFC 8414",
    year=2018,
    url="https://www.rfc-editor.org/rfc/rfc8414.html",
    kind="standard",
)

JWT_BCP_RFC8725 = ResearchReference(
    reference_id="jwt-bcp-rfc8725",
    title="JSON Web Token Best Current Practices",
    venue="RFC 8725",
    year=2020,
    url="https://www.rfc-editor.org/rfc/rfc8725.html",
    kind="standard",
)

JWS_RFC7515 = ResearchReference(
    reference_id="jws-rfc7515",
    title="JSON Web Signature (JWS)",
    venue="RFC 7515",
    year=2015,
    url="https://www.rfc-editor.org/rfc/rfc7515.html",
    kind="standard",
)

JWK_RFC7517 = ResearchReference(
    reference_id="jwk-rfc7517",
    title="JSON Web Key (JWK)",
    venue="RFC 7517",
    year=2015,
    url="https://www.rfc-editor.org/rfc/rfc7517.html",
    kind="standard",
)

JWT_RFC7519 = ResearchReference(
    reference_id="jwt-rfc7519",
    title="JSON Web Token (JWT)",
    venue="RFC 7519",
    year=2015,
    url="https://www.rfc-editor.org/rfc/rfc7519.html",
    kind="standard",
)

NIST_SP_800_131A_R2 = ResearchReference(
    reference_id="nist-sp-800-131a-r2",
    title="Transitioning the Use of Cryptographic Algorithms and Key Lengths",
    venue="NIST SP 800-131A Rev. 2",
    year=2019,
    url="https://csrc.nist.gov/pubs/sp/800/131/a/r2/final",
    kind="standard",
)

WEBAUTHN_LEVEL_3 = ResearchReference(
    reference_id="webauthn-level-3",
    title="Web Authentication: An API for Accessing Public Key Credentials Level 3",
    venue="W3C Recommendation",
    year=2026,
    url="https://www.w3.org/TR/webauthn-3/",
    kind="standard",
)

PASSKEY_ENDPOINTS_W3C = ResearchReference(
    reference_id="passkey-endpoints-w3c",
    title="A Well-Known URL for Relying Party Passkey Endpoints",
    venue="W3C Web Application Security Working Group Draft",
    year=2026,
    url="https://w3c.github.io/webappsec-passkey-endpoints/passkey-endpoints.html",
    kind="standard",
)

IANA_COSE_ALGORITHMS = ResearchReference(
    reference_id="iana-cose-algorithms-2026-08-25",
    title="CBOR Object Signing and Encryption (COSE) Algorithms Registry",
    venue="IANA COSE Registry",
    year=2026,
    url="https://www.iana.org/assignments/cose/cose.xhtml#algorithms",
    kind="standard",
)
