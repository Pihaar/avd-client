# Security

## Threat Model (STRIDE)

| Boundary | Threat | Mitigation | Residual Risk |
|---|---|---|---|
| App → Broker (D-Bus) | Spoofing: fake broker on session bus | Broker unique-name pinning via `GetNameOwner`; `/proc/<pid>/exe` check (defence-in-depth) | Same-UID attacker can register name before real broker |
| App → Broker | Info Disclosure: token in memory | Token not persisted to disk; process exits after session | Python immutable strings not zeroable |
| App → Feed API (HTTPS) | Tampering: malicious feed response | Hostname allowlist (`*.wvd.microsoft.com`, `*.cloudpc.microsoft.com`); TLS verification; no redirects | Corporate MITM proxy could intercept |
| App → Feed API | SSRF: attacker-controlled URL | Feed URLs validated against allowlist before fetching; `AVD_FEED_URL` env override removed | N/A |
| App → xfreerdp (exec) | Info Disclosure: token in argv | **ACCEPTED**: FreeRDP only accepts bearer token via CLI argument. Visible in `/proc/PID/cmdline` to same-UID processes. Token lifetime ~1h. | Same-UID attacker can read token for session duration |
| App → xfreerdp | Injection: malicious session_host | Hostname regex validation (RFC 1035, allowlisted domains) | N/A |
| App → Browser (auth) | Phishing: malicious auth URL | URL regex validates `https://login.microsoftonline.com/` prefix | URL with `@` userinfo could redirect (low risk) |
| App → Browser (PKCE) | CSRF: forged callback | Random `state` compared with `secrets.compare_digest`; redirect URL limited to the Microsoft nativeclient path | N/A |
| App → Browser (PKCE) | Info Disclosure: authorization code | Code exchanged immediately; code verifier, code, and tokens never logged; redirect URL not echoed | Browser history may retain the code briefly |
| App → Headless browser | Info Disclosure: PRT cookie and auth code | Cookie kept in memory, scoped to login.microsoftonline.com; redirect validated; neither value logged | Headless browser process memory |
| Protocol Handler → App | Injection: malicious redirect URL | URL must start with `ms-appx-web://microsoft.aad.brokerplugin/`; no control characters; length capped at 8192 | Same-UID process can write callback file |
| Protocol Handler | Squatting: competing handler | Check `xdg-mime query default` before use; warn if not ours | Any same-UID process can re-register |
| xfreerdp → Gateway | MITM: cert:tofu | Gateway uses TLS + Bearer auth; inner RDP-TLS is defence-in-depth | First-connect TOFU = trust without prior verification |

## Residual Risks (Accepted)

| # | Risk | Acceptance Rationale |
|---|---|---|
| 1 | Bearer token visible in `/proc/<pid>/cmdline` | FreeRDP API constraint. Mitigated: single-user workstation, token 1h lifetime, Conditional Access device-bound. |
| 2 | Protocol handler can be squatted by same-UID process | `xdg-mime` has no integrity protection. Mitigated: check at launch, RPM install for production. |
| 3 | `/cert:tofu` on first session-host connect | AVD gateway authenticates via Bearer; session-host TLS is an additional layer. |
| 4 | 1h token lifetime without refresh | Sessions > 1h require reconnect. Phase 2: sso-mib integration for token refresh. |
| 5 | Token in Python heap memory (immutable string) | `prctl(PR_SET_DUMPABLE, 0)` recommended for production. Core dumps disabled. |

## Security Controls

| Control | Implementation |
|---|---|
| SEC-100 Input Validation | `security.py`: hostname, token shape, UPN, redirect URL, feed URL validators |
| SEC-215 Audit Logging | Python logging to stderr (structured); syslog integration planned Phase 2 |
| SEC-218 TLS | `ssl.create_default_context()` with TLS 1.2 minimum; system CA store |
| SEC-236 Info Disclosure | Token redaction filter on all loggers + sys.excepthook; error messages truncated to 200 chars |
| SEC-239 Fail Securely | All error paths exit with defined codes (2=auth, 3=feed, 4=launcher, 5=security) |
| SEC-278 URL Handling | Feed URLs validated against domain allowlist; no redirect following |
| SEC-309 Secret Management | Access token not persisted; PKCE refresh token in the OS keyring when available; PRT cookie in memory only; callback file mode 0600; atomic writes |
| SEC-375 SSRF Protection | No redirect handler in urllib opener; hostname allowlist on all fetched URLs |

## Broker-free PKCE Authentication

When the broker is unavailable, `auth.py` uses OAuth2 authorization code with
PKCE (S256). The flow opens the Microsoft sign-in page, validates the returned
`state`, and exchanges the code immediately. The redirect URL must use
`https://login.microsoftonline.com/common/oauth2/nativeclient`; `security.py`
parses the code and state without echoing either value.

The access token is kept in memory only and is never persisted. The refresh
token is written to the OS keyring (Secret Service) when `python3-keyring` is
available; it is never written to a plain file. Without a keyring, the refresh
token stays in memory only. The ID token is parsed for the UPN without signature
verification because it is read directly from the TLS token endpoint and is used
only as the FreeRDP username hint.

## Headless Session-Host Authentication

When Playwright and a Chromium build are available, the launcher requests a PRT
SSO cookie from the broker and injects it into a local headless browser. The
cookie is held in memory, scoped to `login.microsoftonline.com`, and never
logged. The captured `ms-appx-web://` redirect is validated before it is
written to FreeRDP. Without a broker the headless path is skipped and the normal
browser opens; private devices have no PRT, so the session-host login stays
interactive.

## Incident Response

If a token is suspected compromised:

1. Admin: `Revoke-MgUserSignInSession -UserId <user>` (invalidates all tokens)
2. Admin: Mark device non-compliant in Intune (blocks next PRT refresh)
3. Admin: Terminate AVD session via `Remove-AzWvdUserSession`
4. User: Restart `avd-client` (acquires fresh token with new CA evaluation)

## Frontend Security Invariant

The `Frontend` protocol (defined in `ui.py`) is an **untrusted output sink**. It MUST NOT perform any input validation. All validation happens in `security.py` and `launcher.py`. A `Frontend.prompt_url()` call returns raw user input; the caller always validates via `validate_redirect_url()` before use.

## i18n Trust Assumptions

Translation files (`.mo`) are shipped as part of the package and are NOT user-supplied at runtime. They are build-time artifacts compiled from `.po` source. A tampered `.mo` file would require write access to the installed package directory.

## Dependencies

| Dependency | Trust Level | Notes |
|---|---|---|
| `dbus-python` | System package | C extension, linked against system libdbus-1 |
| `microsoft-identity-broker` | Microsoft proprietary | Signed RPM from packages.microsoft.com |
| `xfreerdp3` | System package | Signed RPM from distro or OBS |
| Python stdlib | System | urllib.request, xml.etree, ssl, pty |
