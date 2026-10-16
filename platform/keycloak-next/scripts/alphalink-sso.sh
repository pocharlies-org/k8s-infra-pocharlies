#!/bin/sh
# SC-2495 — reconciler del SSO del planificador de AlphaLink en el realm `edani`.
# El cuerpo esta en sso-app-common.sh (es el mismo para cada app); aqui solo van
# los literales de esta app. Los nombres de grupo y el callback tienen que coincidir
# con oauth2-proxy-alphalink-config y con la IngressRoute: si difieren, sin acceso.
SSO_APP=alphalink
EXPECT_REDIRECT_URI=https://horarios.alphalinkcrossfit.com/oauth2/callback
EXPECT_USER_GROUP=/alphalink-horarios-users
EXPECT_ADMIN_GROUP=/alphalink-horarios-admins

. "${0%/*}/sso-app-common.sh"
