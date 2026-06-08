"""HTTP helper functions for signup and connectivity checks."""

from __future__ import annotations

import httpx

from .constants import ALLOWED_MVIEW_FQNS, ANTHROPIC_BASE_URL, SIGNUP_API_URL


def signup(email: str, insecure_tls: bool) -> str:
    """Send signup request and return a user-friendly response string."""

    signup_url = SIGNUP_API_URL
    with httpx.Client(verify=not insecure_tls, timeout=20.0) as client:
        try:
            response = client.post(signup_url, json={"email": email.strip()})
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Signup request failed for `{signup_url}`: {exc}") from exc

    if response.status_code != 200:
        detail = _extract_error(response)
        raise RuntimeError(f"Signup failed ({response.status_code}): {detail}")

    payload = response.json() if response.content else {}
    message = payload.get("message")
    if not isinstance(message, str) or not message:
        return "Signup succeeded. Check your email to confirm your address."
    return message


def probe_anthropic(api_token: str, insecure_tls: bool) -> None:
    """Validate shared token against Anthropic proxy endpoint."""

    anthropic_models_url = f"{ANTHROPIC_BASE_URL.rstrip('/')}/v1/models"
    with httpx.Client(
        headers={
            "Authorization": f"Bearer {api_token}",
            "x-api-key": api_token,
        },
        verify=not insecure_tls,
        timeout=20.0,
    ) as client:
        try:
            response = client.get(anthropic_models_url)
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Anthropic endpoint request failed for `{anthropic_models_url}`: {exc}"
            ) from exc

    if response.status_code >= 400:
        detail = _extract_error(response)
        raise RuntimeError(f"Anthropic token check failed ({response.status_code}): {detail}")


def probe_mcp(api_token: str, mcp_url: str, insecure_tls: bool) -> None:
    """Validate shared token against DeltaStream MCP endpoint."""

    with httpx.Client(
        headers={"Authorization": f"Bearer {api_token}"},
        verify=not insecure_tls,
        timeout=20.0,
    ) as client:
        try:
            response = client.get(mcp_url)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"MCP endpoint request failed for `{mcp_url}`: {exc}") from exc

    if response.status_code == 404:
        raise RuntimeError(f"MCP endpoint not found (404): {mcp_url}")
    if response.status_code in (401, 403):
        detail = _extract_error(response)
        raise RuntimeError(f"MCP token check failed ({response.status_code}): {detail}")
    if response.status_code >= 500:
        detail = _extract_error(response)
        raise RuntimeError(f"MCP endpoint check failed ({response.status_code}): {detail}")


def allowed_relation_label() -> str:
    """Return formatted relation label for UI output."""

    return ", ".join(f"`{name}`" for name in ALLOWED_MVIEW_FQNS)


def _extract_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            for key in ("error", "message", "detail"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    except ValueError:
        pass

    text = response.text.strip()
    return text[:250] if text else "Unknown error"
