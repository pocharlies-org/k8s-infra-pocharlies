"""SC-4304: additive GitOps grants for verified Leila identities; no credential rotation."""
import json
import urllib.error
import urllib.parse
import urllib.request

from kc_rbac import Client, KcError, USER_AGENT

ROLE = 'agentgateway-read:hindsight-leila'
HUMAN = ('66ec6f4f-5f2c-44f6-a3db-0dccba6e1748', 'lays84.mv@gmail.com')
HERMES = ('70961dcd-06a2-471a-ac39-c69d28137331', 'service-account-hermes-secretaria-leila')
CLIENT = 'agentgateway-chat-hindsight-leila-mcp'
REDIRECT = 'https://chat.e-dani.com/oauth/clients/mcp:hindsight-leila/callback'
AUDIENCE = 'mcp.lan.e-dani.com'


class Admin(Client):
    def write(self, method, path, body):
        url = f'{self.base_url}/admin/realms/{urllib.parse.quote(self.realm, safe="")}/{path}'
        req = urllib.request.Request(url, method=method, data=json.dumps(body).encode(), headers={
            'Authorization': 'Bearer ' + self._token, 'Content-Type': 'application/json', 'User-Agent': USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                require(response.status in (201, 204), 'unexpected Keycloak write status')
        except urllib.error.HTTPError as exc:
            raise KcError(f'Keycloak write failed: HTTP {exc.code}') from None


def optional(admin, path):
    try:
        return admin.get(path)
    except KcError as exc:
        if exc.status != 404:
            raise
        return None


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reconcile(admin):
    require(admin.realm == 'edani', 'realm must be edani')
    # Resolve immutable subjects before any mutation; names in prompts never select a user.
    for uid, username in (HUMAN, HERMES):
        user = admin.get('users/' + uid)
        require(user.get('id') == uid and user.get('username') == username and user.get('enabled'),
                'pinned subject mismatch or disabled')
        if uid == HUMAN[0]:
            require(not user.get('serviceAccountClientId'), 'expected human')
    hermes = admin.get('clients', {'clientId': 'hermes-secretaria-leila'})
    require(len(hermes) == 1 and hermes[0]['clientId'] == 'hermes-secretaria-leila'
            and hermes[0].get('enabled') and hermes[0].get('serviceAccountsEnabled'), 'dedicated Hermes client missing')
    require(admin.get('clients/' + hermes[0]['id'] + '/service-account-user')['id'] == HERMES[0],
            'Hermes service account mismatch')
    role_path = 'roles/' + urllib.parse.quote(ROLE, safe='')
    role = optional(admin, role_path)
    if role is not None:
        require(not role.get('composite'), 'Leila role must not be composite')
        require(not admin.get(role_path + '/groups', {'first': 0, 'max': 1}), 'group grant forbidden')
        holders = admin.get(role_path + '/users', {'first': 0, 'max': 3})
        require({u['id'] for u in holders} <= {HUMAN[0], HERMES[0]}, 'unreviewed holder; no automatic revocation')
    clients = admin.get('clients', {'clientId': CLIENT})
    require(len(clients) <= 1, 'duplicate OAuth client')
    if clients:
        scopes = admin.get('clients/' + clients[0]['id'] + '/scope-mappings/realm')
        require({r['name'] for r in scopes} <= {ROLE}, 'OAuth scope contains unrelated role')
    if role is None:
        admin.write('POST', 'roles', {'name': ROLE, 'description': 'SC-4304: private Leila bank reads only', 'composite': False})
        role = admin.get(role_path)
    for uid, _ in (HUMAN, HERMES):
        path = 'users/' + uid + '/role-mappings/realm'
        if ROLE not in {r['name'] for r in admin.get(path)}:
            admin.write('POST', path, [role])
        require(ROLE in {r['name'] for r in admin.get(path)}, 'grant not confirmed')
    # Existing Hermes credential and other scopes stay intact; only make this read role emittable.
    path = 'clients/' + hermes[0]['id'] + '/scope-mappings/realm'
    if ROLE not in {r['name'] for r in admin.get(path)}:
        admin.write('POST', path, [role])
    require(ROLE in {r['name'] for r in admin.get(path)}, 'Hermes scope not confirmed')
    client = {'clientId': CLIENT, 'enabled': True, 'protocol': 'openid-connect',
              'publicClient': True, 'standardFlowEnabled': True, 'directAccessGrantsEnabled': False,
              'implicitFlowEnabled': False, 'serviceAccountsEnabled': False, 'fullScopeAllowed': False,
              'redirectUris': [REDIRECT], 'webOrigins': [], 'attributes': {'pkce.code.challenge.method': 'S256'}}
    admin.write('PUT' if clients else 'POST', 'clients/' + clients[0]['id'] if clients else 'clients', client)
    found = admin.get('clients', {'clientId': CLIENT})
    require(len(found) == 1, 'OAuth client creation not confirmed')
    path = 'clients/' + found[0]['id']
    if ROLE not in {r['name'] for r in admin.get(path + '/scope-mappings/realm')}:
        admin.write('POST', path + '/scope-mappings/realm', [role])
    mappers = admin.get(path + '/protocol-mappers/models')
    audience = [m for m in mappers if m['name'] == 'aud-mcp']
    require(len(audience) <= 1, 'duplicate audience mapper')
    mapper = {'name': 'aud-mcp', 'protocol': 'openid-connect', 'protocolMapper': 'oidc-audience-mapper',
              'config': {'included.custom.audience': AUDIENCE, 'access.token.claim': 'true',
                         'id.token.claim': 'false', 'introspection.token.claim': 'true', 'userinfo.token.claim': 'false'}}
    admin.write('PUT' if audience else 'POST', path + '/protocol-mappers/models' +
                ('/' + audience[0]['id'] if audience else ''), mapper)
    current = admin.get(path)
    require(all(current.get(k) == v for k, v in client.items() if k != 'attributes')
            and current.get('attributes', {}).get('pkce.code.challenge.method') == 'S256', 'OAuth settings not confirmed')
    require({r['name'] for r in admin.get(path + '/scope-mappings/realm')} == {ROLE}, 'OAuth scope not exact')
    require({u['id'] for u in admin.get(role_path + '/users', {'first': 0, 'max': 3})} == {HUMAN[0], HERMES[0]},
            'role holders not exact')
    require(not admin.get(role_path + '/groups', {'first': 0, 'max': 1}), 'group grant forbidden')
    verified = [m for m in admin.get(path + '/protocol-mappers/models') if m['name'] == 'aud-mcp']
    require(len(verified) == 1 and verified[0].get('protocolMapper') == mapper['protocolMapper']
            and all(verified[0].get('config', {}).get(k) == v for k, v in mapper['config'].items()),
            'audience mapper not confirmed')
    print(json.dumps({'role': ROLE, 'verified_holders': 2, 'oauth_client': CLIENT, 'personal_grants_added': 0}))


SHOPIFY_ROLE = 'agentgateway-read:hindsight-shopify-contenido'
SHOPIFY_SUB = 'd04d5d3c-1ae6-4d49-93a4-668f79148467'


def reconcile_shopify(admin):
    require(admin.realm == 'edani', 'realm must be edani')
    client = admin.get('clients', {'clientId': 'hermes-secretaria-skirmshop'})
    require(len(client) == 1 and client[0]['clientId'] == 'hermes-secretaria-skirmshop'
            and client[0].get('enabled') and client[0].get('serviceAccountsEnabled'), 'shopify reader client missing')
    path = 'clients/' + client[0]['id']
    user = admin.get(path + '/service-account-user')
    require(user.get('id') == SHOPIFY_SUB and user.get('username') == 'service-account-hermes-secretaria-skirmshop'
            and user.get('enabled'), 'shopify reader subject mismatch')
    role_path = 'roles/' + urllib.parse.quote(SHOPIFY_ROLE, safe='')
    role = admin.get(role_path)  # Created by the wave-20 read-grants hook, never here.
    require(not role.get('composite'), 'shopify role must not be composite')
    require(not admin.get(role_path + '/groups', {'first': 0, 'max': 1}), 'shopify group grant forbidden')
    allowed = {'service-account-agentgateway-mcp', 'service-account-hermes-secretaria-skirmshop'}
    require({u['username'] for u in admin.get(role_path + '/users', {'first': 0, 'max': 3})} <= allowed,
            'unreviewed shopify holder')
    for collection in ('users/' + SHOPIFY_SUB + '/role-mappings/realm', path + '/scope-mappings/realm'):
        if SHOPIFY_ROLE not in {r['name'] for r in admin.get(collection)}:
            admin.write('POST', collection, [role])
        require(SHOPIFY_ROLE in {r['name'] for r in admin.get(collection)}, 'shopify grant not confirmed')
    print(json.dumps({'role': SHOPIFY_ROLE, 'dedicated_shopify_reader': True, 'personal_grants_added': 0}))


if __name__ == '__main__':
    try:
        admin = Admin.from_env()
        reconcile(admin)
        reconcile_shopify(admin)
    except (KcError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
