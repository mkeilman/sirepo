#!/bin/bash
: how to setup postfix with sasl for smtpd auth <<'EOF'
sudo su -
dnf install -y postfix cyrus-sasl cyrus-sasl-lib cyrus-sasl-plain telnet
systemctl start postfix
systemctl enable postfix
echo vagrant | saslpasswd2 -f /etc/sasldb2 -c -p vagrant
chgrp mail /etc/sasldb2
cat > /etc/sasl2/smtpd-sasldb.conf <<'END'
auxprop_plugin: sasldb
log_level: 4
mech_list: plain
pwcheck_method: auxprop
END
postconf smtpd_sasl_path=smtpd-sasldb smtpd_sasl_auth_enable=yes
systemctl restart postfix
# to test
(sleep 1; echo EHLO localhost; sleep 1; echo AUTH PLAIN AHZhZ3JhbnQAdmFncmFudA==; sleep 1; echo QUIT) | telnet localhost 25
EOF
export SIREPO_AUTH_EMAIL_FROM_EMAIL='support@radiasoft.net'
export SIREPO_AUTH_EMAIL_FROM_NAME='RadiaSoft Support'
export SIREPO_AUTH_EMAIL_SMTP_PASSWORD='n/a'
# POSIT: same as sirepo.auth.email._DEV_SMTP_SERVER
export SIREPO_AUTH_EMAIL_SMTP_SERVER='dev'
export SIREPO_AUTH_EMAIL_SMTP_USER='n/a'
export SIREPO_AUTH_METHODS='email:guest'
export PYKERN_PKDEBUG_WANT_PID_TIME=1
exec sirepo service http
