"""Shared credential screening for asset-neutral M1a provenance references."""

from urllib.parse import parse_qsl, urlsplit

from drift.domain.artifacts import ArtifactReference

_CREDENTIAL_PARAMETER_NAMES = frozenset(
    {
        "apikey",
        "key",
        "token",
        "accesstoken",
        "authtoken",
        "signature",
        "sig",
        "signed",
        "signedurl",
        "credential",
        "credentials",
        "xamzsignature",
        "xamzcredential",
        "xgoogsignature",
        "xgoogcredential",
    }
)


def validate_safe_provenance_reference(
    reference: ArtifactReference,
) -> ArtifactReference:
    """Reject credential-bearing user info, query parameters, and fragments."""
    try:
        location = urlsplit(reference.location)
    except ValueError as error:
        msg = "provenance reference location must not contain credentials"
        raise ValueError(msg) from error
    if location.username is not None or location.password is not None:
        msg = "provenance reference location must not contain credentials"
        raise ValueError(msg)
    parameters = (
        *parse_qsl(location.query, keep_blank_values=True),
        *parse_qsl(location.fragment.lstrip("?"), keep_blank_values=True),
    )
    if any(
        _normalized_parameter_name(name) in _CREDENTIAL_PARAMETER_NAMES
        for name, _ in parameters
    ):
        msg = "provenance reference location must not contain credentials"
        raise ValueError(msg)
    return reference


def _normalized_parameter_name(name: str) -> str:
    """Normalize common credential parameter spellings before comparison."""
    return name.casefold().replace("-", "").replace("_", "")
