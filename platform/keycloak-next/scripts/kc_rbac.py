"""Common, stdlib-only helpers for the realm RBAC verifiers (INFRA-219).

Used by verify-role-catalog.py (P1) and by the later verify-principals.py /
verify-route-roles.py and the keycloak-role-drift CronJob. Read-only: nothing
here creates, grants or deletes anything in Keycloak.

Two ways to authenticate, chosen by the environment:

* in-cluster: KC_CLIENT_ID_FILE and KC_CLIENT_SECRET_FILE point at mounted
  files; client_credentials against KEYCLOAK_URL/realms/KC_TOKEN_REALM
  (default: the audited realm).
* local (operator workstation): the keycloak-admin skill flow. The
  master-realm service account admin-keycloack-server is read from the
  Kubernetes secret keycloak/keycloak-automation into a 0600 netrc that is
  deleted before the token request returns; the token is requested from
  /realms/master. KC_NETRC=<path> reuses an existing netrc instead (it is not
  deleted). The secret never travels through argv.

Never reads keycloak-bootstrap.
"""

import base64
import json
import netrc
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_PUBLIC_URL = "https://auth-next.e-dani.com"
DEFAULT_REALM = "edani"
DEFAULT_PAGE_SIZE = 100
LOCAL_SECRET_NAMESPACE = "keycloak"
LOCAL_SECRET_NAME = "keycloak-automation"
LOCAL_TOKEN_REALM = "master"
TIMEOUT_SECONDS = 30
USER_AGENT = "kc-rbac/1 (k8s-infra-pocharlies INFRA-219)"

CATALOG_STATUSES = ("active", "deprecated")
CATALOG_ROLE_FIELDS = ("name", "meaning", "grantees", "privilege", "origin", "status")


class KcError(Exception):
    """Authentication, network or protocol failure (verifiers exit 2).

    `status` is the HTTP status when the server answered with an error, else None.
    """

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class CatalogError(Exception):
    """A catalog or embedded json block that breaks its own contract."""


def _request(url, data=None, headers=None):
    # The public edge answers 403 to the default Python-urllib user agent
    # (measured 2026-09-24), so every request names itself.
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        # The body of a token error is safe (error/error_description), but
        # it is not echoed: the status and URL are enough to diagnose.
        raise KcError(f"HTTP {exc.code} en {url}", status=exc.code) from None
    except (urllib.error.URLError, OSError) as exc:
        raise KcError(f"sin respuesta de {url}: {exc}") from None
    try:
        return json.loads(body) if body else None
    except ValueError:
        raise KcError(f"respuesta no JSON de {url}") from None


def request_token(base_url, token_realm, client_id, client_secret):
    """client_credentials with client auth in the Basic header, as curl --netrc does."""
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    url = f"{base_url.rstrip('/')}/realms/{urllib.parse.quote(token_realm, safe='')}/protocol/openid-connect/token"
    payload = _request(
        url,
        data=b"grant_type=client_credentials",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    token = (payload or {}).get("access_token")
    if not token:
        raise KcError(f"el token de {url} no trae access_token")
    return token


def _read_file(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError as exc:
        raise KcError(f"no se puede leer {path}: {exc.strerror}") from None


def _netrc_credentials(path, host):
    try:
        entry = netrc.netrc(path).authenticators(host)
    except (OSError, netrc.NetrcParseError) as exc:
        raise KcError(f"netrc ilegible: {exc}") from None
    if not entry or not entry[0] or not entry[2]:
        raise KcError(f"el netrc no tiene credenciales para {host}")
    return entry[0], entry[2]


def _write_netrc_from_secret(host):
    """Dump keycloak-automation to a fresh 0600 netrc; the caller deletes it."""
    try:
        completed = subprocess.run(
            ["kubectl", "-n", LOCAL_SECRET_NAMESPACE, "get", "secret", LOCAL_SECRET_NAME, "-o", "json"],
            check=False,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise KcError(f"kubectl no disponible: {exc}") from None
    if completed.returncode != 0:
        raise KcError(f"kubectl get secret {LOCAL_SECRET_NAMESPACE}/{LOCAL_SECRET_NAME} falló (exit {completed.returncode})")
    try:
        data = json.loads(completed.stdout)["data"]
        login = base64.b64decode(data["client_id"]).decode()
        password = base64.b64decode(data["client_secret"]).decode()
    except (ValueError, KeyError, TypeError):
        raise KcError(f"el secret {LOCAL_SECRET_NAME} no tiene client_id/client_secret") from None
    old_umask = os.umask(0o077)
    try:
        fd, path = tempfile.mkstemp(prefix="kc-rbac-", suffix=".netrc")
    finally:
        os.umask(old_umask)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"machine {host}\nlogin {login}\npassword {password}\n")
    del login, password, data
    return path


class Client:
    """Read-only Keycloak admin API client for one realm."""

    def __init__(self, base_url, realm, token, page_size=None):
        self.base_url = base_url.rstrip("/")
        self.realm = realm
        self._token = token
        self.page_size = page_size or DEFAULT_PAGE_SIZE

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        realm = env.get("KC_REALM", DEFAULT_REALM)
        id_file = env.get("KC_CLIENT_ID_FILE")
        secret_file = env.get("KC_CLIENT_SECRET_FILE")
        if id_file or secret_file:
            if not (id_file and secret_file):
                raise KcError("KC_CLIENT_ID_FILE y KC_CLIENT_SECRET_FILE van juntos")
            base_url = env.get("KEYCLOAK_URL")
            if not base_url:
                raise KcError("KEYCLOAK_URL es obligatorio en modo in-cluster")
            token = request_token(
                base_url,
                env.get("KC_TOKEN_REALM", realm),
                _read_file(id_file),
                _read_file(secret_file),
            )
            return cls(base_url, realm, token)
        base_url = env.get("KEYCLOAK_URL", DEFAULT_PUBLIC_URL)
        host = urllib.parse.urlsplit(base_url).hostname
        own_netrc = env.get("KC_NETRC")
        path = own_netrc or _write_netrc_from_secret(host)
        try:
            login, password = _netrc_credentials(path, host)
            token = request_token(base_url, env.get("KC_TOKEN_REALM", LOCAL_TOKEN_REALM), login, password)
            del password
        finally:
            if not own_netrc:
                os.unlink(path)
        return cls(base_url, realm, token)

    def get(self, path, params=None):
        url = f"{self.base_url}/admin/realms/{urllib.parse.quote(self.realm, safe='')}/{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        return _request(url, headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"})

    def paged(self, path, params=None):
        """Follow first/max until a short page; Keycloak list endpoints cap at max."""
        items, first = [], 0
        while True:
            page = self.get(path, {**(params or {}), "first": first, "max": self.page_size})
            if not isinstance(page, list):
                raise KcError(f"{path} no devuelve una lista")
            items.extend(page)
            if len(page) < self.page_size:
                return items
            first += self.page_size

    @staticmethod
    def _role(name):
        return f"roles/{urllib.parse.quote(name, safe='')}"

    def realm_roles(self):
        return self.paged("roles", {"briefRepresentation": "true"})

    def users(self):
        return self.paged("users", {"briefRepresentation": "true"})

    def service_account_users(self):
        return [
            user
            for user in self.paged("users", {"username": "service-account", "exact": "false", "briefRepresentation": "true"})
            if user.get("username", "").startswith("service-account-")
        ]

    def users_with_role(self, role_name):
        """Direct holders only (Keycloak does not expand composites here)."""
        return self.paged(f"{self._role(role_name)}/users", {"briefRepresentation": "true"})

    def groups_with_role(self, role_name):
        return self.paged(f"{self._role(role_name)}/groups", {"briefRepresentation": "true"})

    def _composites(self, role_name):
        """Not paged: /roles/{name}/composites returns the whole list and ignores
        first/max, so paged() would never see a short page."""
        composites = self.get(f"{self._role(role_name)}/composites")
        if not isinstance(composites, list):
            raise KcError(f"{self._role(role_name)}/composites no devuelve una lista")
        return composites

    def realm_composites(self, role_name):
        """Names of the realm roles a role contains (its client-role composites are left out)."""
        return sorted(role["name"] for role in self._composites(role_name) if not role.get("clientRole"))

    def client_id(self, client_uuid):
        """clientId of a client by its internal id, or None if the realm has no such client.

        Privileged: GET clients/{id} needs realm-management view-clients, which
        also reads every client secret. Only the check of the catalog's
        client_uuids calls it; the role auditor never does.
        """
        try:
            client = self.get(f"clients/{urllib.parse.quote(client_uuid, safe='')}")
        except KcError as exc:
            if exc.status == 404:
                return None
            raise
        if not isinstance(client, dict) or not client.get("clientId"):
            raise KcError(f"clients/{client_uuid} no devuelve un clientId")
        return client["clientId"]

    def client_composites(self, role_name, client_uuids):
        """{clientId: sorted client-role names} a role contains (empty clients left out).

        Composites carry only the client's internal id (containerId); it is
        translated with the catalog's client_uuids ({clientId: id}), never with
        GET clients. An id the map does not know comes out as `uuid:<id>`, so it
        never matches a declared clientId.
        """
        by_uuid = {uuid: client for client, uuid in client_uuids.items()}
        grouped = {}
        for role in self._composites(role_name):
            if role.get("clientRole"):
                container = role["containerId"]
                grouped.setdefault(by_uuid.get(container, f"uuid:{container}"), []).append(role["name"])
        return {client: sorted(names) for client, names in grouped.items()}


_JSON_FENCE = re.compile(r"^```json[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)


def load_json_block(md_path):
    """The single json fenced block of a markdown contract (PRINCIPALS.md, ROUTE-ROLES.md)."""
    try:
        with open(md_path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise CatalogError(f"no se puede leer {md_path}: {exc.strerror}") from None
    blocks = _JSON_FENCE.findall(text)
    if len(blocks) != 1:
        raise CatalogError(f"{md_path} debe tener exactamente un bloque ```json (tiene {len(blocks)})")
    try:
        return json.loads(blocks[0])
    except ValueError as exc:
        raise CatalogError(f"el bloque json de {md_path} no es JSON válido: {exc}") from None


def load_role_catalog(path):
    """ROLES.yaml (JSON, which is YAML 1.2), validated against its own contract.

    `composites` is optional: the exact realm roles a composite role contains
    (absent = none), each of them a catalogued role. `client_composites` is
    optional too: {clientId: exact client roles} the role contains (absent =
    none); client roles are not catalogued here, so only the shape is checked.
    The top-level `client_uuids` ({clientId: internal id}) names exactly the
    clientIds some `client_composites` uses, no more and no less.

    Returns {name: entry}. Raises CatalogError on any shape violation.
    """
    return load_catalog(path)[0]


def load_client_uuids(path):
    """The validated top-level client_uuids of ROLES.yaml ({clientId: internal id})."""
    return load_catalog(path)[1]


def load_catalog(path):
    """(roles {name: entry}, client_uuids {clientId: id}) of ROLES.yaml; see load_role_catalog."""
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise CatalogError(f"no se puede leer {path}: {exc.strerror}") from None
    except ValueError as exc:
        raise CatalogError(f"{path} no es JSON válido: {exc}") from None
    roles = document.get("roles") if isinstance(document, dict) else None
    if not isinstance(roles, list) or not roles:
        raise CatalogError(f"{path}: falta la lista roles")
    catalog = {}
    for index, entry in enumerate(roles):
        where = f"{path}: roles[{index}]"
        if not isinstance(entry, dict):
            raise CatalogError(f"{where} no es un objeto")
        missing = [field for field in CATALOG_ROLE_FIELDS if field not in entry]
        if missing:
            raise CatalogError(f"{where} sin {', '.join(missing)}")
        name = entry["name"]
        if not isinstance(name, str) or not name:
            raise CatalogError(f"{where}: name vacío")
        if name in catalog:
            raise CatalogError(f"{where}: {name} duplicado")
        if entry["status"] not in CATALOG_STATUSES:
            raise CatalogError(f"{where}: status de {name} debe ser active o deprecated")
        grantees = entry["grantees"]
        if not isinstance(grantees, list) or not all(isinstance(g, str) and g for g in grantees):
            raise CatalogError(f"{where}: grantees de {name} debe ser una lista de usernames")
        if len(set(grantees)) != len(grantees):
            raise CatalogError(f"{where}: grantees de {name} repetidos")
        privilege = entry["privilege"]
        if not isinstance(privilege, dict) or not privilege.get("allows") or not privilege.get("denies"):
            raise CatalogError(f"{where}: privilege de {name} necesita allows y denies")
        for field in ("meaning", "origin"):
            if not isinstance(entry[field], str) or not entry[field].strip():
                raise CatalogError(f"{where}: {field} de {name} vacío")
        composites = entry.get("composites", [])
        if not isinstance(composites, list) or not all(isinstance(c, str) and c for c in composites):
            raise CatalogError(f"{where}: composites de {name} debe ser una lista de nombres de rol de realm")
        if composites != sorted(set(composites)):
            raise CatalogError(f"{where}: composites de {name} debe ir ordenado y sin repetidos")
        client_composites = entry.get("client_composites", {})
        if not isinstance(client_composites, dict) or not all(
            isinstance(client, str) and client and isinstance(names, list) and names
            and all(isinstance(n, str) and n for n in names)
            for client, names in client_composites.items()
        ):
            raise CatalogError(f"{where}: client_composites de {name} debe ser un objeto clientId → lista no vacía de roles de cliente")
        for client, names in client_composites.items():
            if names != sorted(set(names)):
                raise CatalogError(f"{where}: client_composites de {name} ({client}) debe ir ordenado y sin repetidos")
        catalog[name] = entry
    for name, entry in catalog.items():
        unknown = [c for c in entry.get("composites", []) if c not in catalog or c == name]
        if unknown:
            raise CatalogError(f"{path}: composites de {name} nombra roles no catalogados: {', '.join(unknown)}")
    client_uuids = document.get("client_uuids", {})
    if not isinstance(client_uuids, dict) or not all(
        isinstance(client, str) and client and isinstance(uuid, str) and uuid for client, uuid in client_uuids.items()
    ):
        raise CatalogError(f"{path}: client_uuids debe ser un objeto clientId → id interno")
    if len(set(client_uuids.values())) != len(client_uuids):
        raise CatalogError(f"{path}: client_uuids repite un id interno")
    used = {client for entry in catalog.values() for client in entry.get("client_composites", {})}
    unmapped = sorted(used - set(client_uuids))
    if unmapped:
        raise CatalogError(f"{path}: client_uuids no tiene el id de {', '.join(unmapped)} (usado en client_composites)")
    unused = sorted(set(client_uuids) - used)
    if unused:
        raise CatalogError(f"{path}: client_uuids sobra {', '.join(unused)} (ningún client_composites lo usa)")
    return catalog, client_uuids
