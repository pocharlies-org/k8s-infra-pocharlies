#!/bin/sh
# SKIRM-15 — reconciler del SSO propio de skirmbooks en el realm `edani`.
# El cuerpo esta en sso-app-common.sh (es el mismo para cada app); aqui solo van
# los literales de esta app, que son lo unico que la distingue de alphalink.
SSO_APP=skirmbooks
EXPECT_REDIRECT_URI=https://skirmbooks.e-dani.com/oauth2/callback
EXPECT_USER_GROUP=/skirmbooks-users
EXPECT_ADMIN_GROUP=/skirmbooks-admins

. "${0%/*}/sso-app-common.sh"
