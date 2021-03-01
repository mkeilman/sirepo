# -*- coding: utf-8 -*-
u"""User roles

:copyright: Copyright (c) 2021 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
import sirepo.auth_db
import sirepo.util

ROLE_ADM = 'adm'
ROLE_PAYMENT_PLAN_ENTERPRISE = 'enterprise'
ROLE_PAYMENT_PLAN_PREMIUM = 'premium'

PAID_USER_ROLES = (ROLE_PAYMENT_PLAN_PREMIUM, ROLE_PAYMENT_PLAN_ENTERPRISE)


def check_user_has_role(uid, role, raise_forbidden=True):
    if sirepo.auth_db.UserRole.has_role(uid, role):
        return True
    if raise_forbidden:
        sirepo.util.raise_forbidden('uid={} role={} not found'.format(uid, role))
    return False


def get_all_roles():
    return [
        role_for_sim_type(t) for t in sirepo.feature_config.cfg().proprietary_sim_types
    ] + [
        ROLE_ADM,
        ROLE_PAYMENT_PLAN_ENTERPRISE,
        ROLE_PAYMENT_PLAN_PREMIUM,
    ]


def role_for_sim_type(sim_type):
    return 'sim_type_' + sim_type