from __future__ import annotations

import httpx


def signup(email: str, signup_url: str, insecure_tls: bool) -> str:
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
    if isinstance(message, str) and message.strip():
        return message
    return "Signup succeeded. Check your email to confirm your address."


def probe_anthropic(api_token: str, anthropic_base_url: str, insecure_tls: bool) -> None:
    models_url = f"{anthropic_base_url.rstrip('/')}/v1/models"
    with httpx.Client(
        headers={
            "Authorization": f"Bearer {api_token}",
            "x-api-key": api_token,
            "anthropic-version": "2023-06-01",
        },
        verify=not insecure_tls,
        timeout=20.0,
    ) as client:
        try:
            response = client.get(models_url)
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Anthropic endpoint request failed for `{models_url}`: {exc}"
            ) from exc

    if response.status_code >= 400:
        detail = _extract_error(response)
        raise RuntimeError(f"Anthropic token check failed ({response.status_code}): {detail}")


def probe_gemini(
    api_token: str,
    gemini_base_url: str,
    model_name: str,
    insecure_tls: bool,
) -> None:
    # The demo /gemini gateway only proxies the `:generateContent` surface, not the
    # `/v1beta/models` listing, so validate the token with a minimal generation call.
    generate_url = (
        f"{gemini_base_url.rstrip('/')}/v1beta/models/{model_name}:generateContent"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
        "generationConfig": {"maxOutputTokens": 1},
    }
    with httpx.Client(
        headers={
            "Authorization": f"Bearer {api_token}",
            "content-type": "application/json",
        },
        verify=not insecure_tls,
        timeout=20.0,
    ) as client:
        try:
            response = client.post(generate_url, json=payload)
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Gemini endpoint request failed for `{generate_url}`: {exc}"
            ) from exc

    # 200 means the token works. 400 means the request reached the model but the tiny
    # probe body was rejected, which still proves auth succeeded. Only treat auth and
    # routing failures as fatal.
    if response.status_code in (401, 403):
        detail = _extract_error(response)
        raise RuntimeError(f"Gemini token check failed ({response.status_code}): {detail}")
    if response.status_code == 404:
        raise RuntimeError(
            f"Gemini endpoint not found (404) for `{generate_url}`. "
            "Check GEMINI_BASE_URL and the model name."
        )
    if response.status_code >= 500:
        detail = _extract_error(response)
        raise RuntimeError(f"Gemini endpoint check failed ({response.status_code}): {detail}")


def probe_mcp(api_token: str, mcp_url: str, insecure_tls: bool) -> None:
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
