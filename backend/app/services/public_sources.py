"""Bounded read-only retrieval of public HTTPS evidence pages.

Connect to a validated public IP with the original TLS hostname, so redirects
and DNS changes cannot redirect contact evidence checks into a private network.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx


def public_page(url: str, allowed_domains: list[str] | None = None) -> str:
    with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
        for _ in range(4):
            parts = urlsplit(url)
            host = parts.hostname
            if parts.scheme != "https" or not host or parts.username or parts.password or parts.port not in (None, 443):
                raise ValueError("Evidence must use public HTTPS URLs")
            if allowed_domains is not None and not any(
                host == domain or host.endswith("." + domain) for domain in allowed_domains
            ):
                raise ValueError("Page is outside the allowed company domains")
            addresses = list(dict.fromkeys(
                result[4][0] for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            ))
            if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
                raise ValueError("Evidence host must resolve only to public addresses")
            address = addresses[0]
            authority = f"[{address}]" if ":" in address else address
            target = urlunsplit(("https", authority, parts.path or "/", parts.query, ""))
            with client.stream("GET", target, headers={"Host": host, "User-Agent": "Tailored/1.0"},
                               extensions={"sni_hostname": host}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                if not any(kind in response.headers.get("content-type", "") for kind in ("text/html", "text/plain")):
                    raise ValueError("Evidence page must contain text")
                chunks = []
                size = 0
                for chunk in response.iter_bytes(chunk_size=65536):
                    size += len(chunk)
                    if size > 2_000_000:
                        raise ValueError("Evidence page exceeds size limit")
                    chunks.append(chunk)
                return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
        raise ValueError("Evidence page redirects too many times")
