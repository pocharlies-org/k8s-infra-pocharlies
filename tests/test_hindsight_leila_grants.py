"""SC-4304: exercise the same reconciler interface as the GitOps hook, without live writes."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'platform/keycloak-next'
sys.path.insert(0, str(BASE / 'scripts'))
import kc_rbac

spec = importlib.util.spec_from_file_location('leila_grants', BASE / 'scripts/hindsight-leila-grants.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Fake:
    realm = 'edani'

    def __init__(self):
        self.calls = []
        self.role = None
        self.users = {uid: {'id': uid, 'username': name, 'enabled': True} for uid, name in (module.HUMAN, module.HERMES)}
        self.grants = {uid: [] for uid in self.users}
        self.clients = {'hermes': {'id': 'hermes', 'clientId': 'hermes-secretaria-leila',
                                  'enabled': True, 'serviceAccountsEnabled': True, 'fullScopeAllowed': True}}
        self.scopes = {'hermes': [{'name': 'agentgateway-read:workspace'}]}
        self.mappers = []
        self.groups = []
        self.extra_holders = []

    def get(self, path, params=None):
        path = unquote(path)
        if path == 'clients':
            return [copy.deepcopy(c) for c in self.clients.values() if c['clientId'] == params['clientId']]
        if path.startswith('roles/'):
            if self.role is None:
                raise kc_rbac.KcError('missing', status=404)
            if path.endswith('/groups'):
                return self.groups
            if path.endswith('/users'):
                return [self.users[uid] for uid, grants in self.grants.items() if grants] + self.extra_holders
            return self.role
        bits = path.split('/')
        if bits[0] == 'users':
            return self.users[bits[1]] if len(bits) == 2 else copy.deepcopy(self.grants[bits[1]])
        if bits[0] == 'clients':
            if len(bits) == 2:
                return copy.deepcopy(self.clients[bits[1]])
            if bits[2] == 'service-account-user':
                return self.users[module.HERMES[0]]
            if bits[2] == 'scope-mappings':
                return copy.deepcopy(self.scopes.get(bits[1], []))
            if bits[2] == 'protocol-mappers':
                return copy.deepcopy(self.mappers)
        raise AssertionError(path)

    def write(self, method, path, body):
        self.calls.append((method, path, copy.deepcopy(body)))
        bits = path.split('/')
        if path == 'roles':
            self.role = {'id': 'leila-role', **body}
        elif bits[0] == 'users':
            self.grants[bits[1]] += body
        elif path == 'clients':
            self.clients['oauth'] = {'id': 'oauth', **body}
        elif len(bits) == 2:
            self.clients[bits[1]].update(body)
        elif bits[2] == 'scope-mappings':
            self.scopes.setdefault(bits[1], []).extend(body)
        elif bits[2] == 'protocol-mappers':
            if method == 'PUT':
                # Keycloak reads the mapping id from the BODY (ClientAdapter.updateProtocolMapper):
                # a PUT whose body lacks it answers HTTP 500, it does not take it from the path.
                assert body.get('id') == bits[4], (body.get('id'), bits[4])
                self.mappers = [dict(body)]
            else:
                self.mappers = [{'id': 'audience', **body}]
        else:
            raise AssertionError(path)


class LeilaGrantsTest(unittest.TestCase):
    def test_only_two_pinned_holders_exact_oauth_scope_and_no_rotation(self):
        fake = Fake()
        module.reconcile(fake)
        module.reconcile(fake)
        self.assertEqual({module.ROLE}, {r['name'] for r in fake.scopes['oauth']})
        self.assertEqual([module.REDIRECT], fake.clients['oauth']['redirectUris'])
        self.assertFalse(fake.clients['oauth']['fullScopeAllowed'])
        self.assertEqual('S256', fake.clients['oauth']['attributes']['pkce.code.challenge.method'])
        self.assertTrue(fake.clients['hermes']['fullScopeAllowed'])
        self.assertIn({'name': 'agentgateway-read:workspace'}, fake.scopes['hermes'])
        self.assertEqual(module.AUDIENCE, fake.mappers[0]['config']['included.custom.audience'])
        for uid in fake.grants:
            self.assertEqual([module.ROLE], [r['name'] for r in fake.grants[uid]])
        raw = json.dumps(fake.calls)
        self.assertNotIn('client-secret', raw)
        self.assertNotIn('hindsight-personal', raw)
        self.assertFalse(any(method == 'DELETE' for method, _, _ in fake.calls))

    def test_identity_mismatch_stops_before_any_write(self):
        for change in ('username', 'enabled', 'sa_human', 'hermes_sub'):
            with self.subTest(change=change):
                fake = Fake()
                if change == 'username':
                    fake.users[module.HUMAN[0]]['username'] = 'not-leila'
                elif change == 'enabled':
                    fake.users[module.HUMAN[0]]['enabled'] = False
                elif change == 'sa_human':
                    fake.users[module.HUMAN[0]]['serviceAccountClientId'] = 'shared'
                else:
                    fake.users[module.HERMES[0]]['id'] = 'wrong-sub'
                with self.assertRaises(ValueError):
                    module.reconcile(fake)
                self.assertEqual([], fake.calls)

    def test_extra_holder_group_or_scope_fails_without_revoking(self):
        for change in ('holder', 'group', 'scope', 'composite'):
            with self.subTest(change=change):
                fake = Fake()
                module.reconcile(fake)
                fake.calls.clear()
                if change == 'holder':
                    fake.extra_holders = [{'id': 'shared'}]
                elif change == 'group':
                    fake.groups = [{'id': 'group'}]
                elif change == 'scope':
                    fake.scopes['oauth'].append({'name': 'agentgateway-read:hindsight-personal'})
                else:
                    fake.role['composite'] = True
                with self.assertRaises(ValueError):
                    module.reconcile(fake)
                self.assertEqual([], fake.calls)

    def test_catalog_and_hook_declare_the_same_pinned_grants(self):
        roles = kc_rbac.load_role_catalog(BASE / 'ROLES.yaml')
        self.assertEqual(sorted([module.HUMAN[1], module.HERMES[1]]), sorted(roles[module.ROLE]['grantees']))
        self.assertEqual(['service-account-agentgateway-mcp', 'service-account-hermes-secretaria-skirmshop'],
                         roles['agentgateway-read:hindsight-shopify-contenido']['grantees'])
        principals = kc_rbac.load_json_block(BASE / 'PRINCIPALS.md')['principals']
        for uid, name in (module.HUMAN, module.HERMES):
            self.assertIn(module.ROLE, next(p for p in principals if p['username'] == name)['realm_roles'])
        manifest = (BASE / 'hindsight-leila-grants.yaml').read_text()
        self.assertIn('secretName: keycloak-automation', manifest)
        self.assertNotIn('keycloak-bootstrap', manifest)
        self.assertNotIn('secretKeyRef', manifest)
        self.assertIn('automountServiceAccountToken: false', manifest)
        self.assertIn('readOnlyRootFilesystem: true', manifest)
        self.assertIn('hindsight-leila-grants.yaml', (BASE / 'kustomization.yaml').read_text())


class ShopifyGrantsTest(unittest.TestCase):
    def test_existing_dedicated_reader_gets_only_editorial_role(self):
        from unittest.mock import Mock
        admin = Mock(realm='edani')
        mappings = {'users/' + module.SHOPIFY_SUB + '/role-mappings/realm': [],
                    'clients/shopify/scope-mappings/realm': []}
        role = {'id': 'editorial', 'name': module.SHOPIFY_ROLE, 'composite': False}

        def get(path, params=None):
            if path == 'clients':
                return [{'id': 'shopify', 'clientId': 'hermes-secretaria-skirmshop',
                         'enabled': True, 'serviceAccountsEnabled': True}]
            if path.endswith('/service-account-user'):
                return {'id': module.SHOPIFY_SUB, 'username': 'service-account-hermes-secretaria-skirmshop', 'enabled': True}
            if path in mappings:
                return list(mappings[path])
            if path.endswith('/groups'):
                return []
            if path.endswith('/users'):
                return [{'username': 'service-account-agentgateway-mcp'}]
            return role

        admin.get.side_effect = get
        admin.write.side_effect = lambda method, path, body: mappings[path].extend(body)
        module.reconcile_shopify(admin)
        module.reconcile_shopify(admin)
        self.assertEqual(2, admin.write.call_count)
        self.assertNotIn('personal', str(admin.write.call_args_list))
        for values in mappings.values():
            self.assertEqual([module.SHOPIFY_ROLE], [r['name'] for r in values])


if __name__ == '__main__':
    unittest.main()
