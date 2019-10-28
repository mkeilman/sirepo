# -*- coding: utf-8 -*-
"""Runs job supervisor tornado server

:copyright: Copyright (c) 2019 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from pykern import pkconfig
from pykern import pkjson
from pykern.pkcollections import PKDict
from pykern.pkdebug import pkdp, pkdlog, pkdexc, pkdc
from sirepo import job
from sirepo import job_driver
from sirepo import job_supervisor
import asyncio
import signal
import tornado.httpserver
import tornado.ioloop
import tornado.web
import tornado.websocket

cfg = None


def default_command():
    global cfg

    cfg = pkconfig.init(
        debug=(pkconfig.channel_in('dev'), bool, 'run supervisor in debug mode'),
        ip=(job.DEFAULT_IP, str, 'ip address to listen on'),
        port=(job.DEFAULT_PORT, int, 'what port to listen on'),
    )
    app = tornado.web.Application(
        [
            (job.AGENT_URI, _AgentMsg),
            (job.SERVER_URI, _ServerReq),
        ],
        debug=cfg.debug,
    )
    server = tornado.httpserver.HTTPServer(app)
    server.listen(cfg.port, cfg.ip)
    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)
    pkdlog('ip={} port={}', cfg.ip, cfg.port)
    job_supervisor.init()
    tornado.ioloop.IOLoop.current().start()


class _AgentMsg(tornado.websocket.WebSocketHandler):
    sr_class = job_driver.AgentMsg

    def check_origin(self, origin):
        return True

    def on_close(self):
        try:
            d = getattr(self, 'sr_driver', None)
            if d:
                del self.sr_driver
                d.websocket_on_close()
        except Exception as e:
            pkdlog('error={} {}', e, pkdexc())

    async def on_message(self, msg):
        await _incoming(msg, self)

    def open(self):
        pkdlog(self.request.uri)

    def sr_close(self):
        """Close socket and does not call on_close

        Unsets driver to avoid a callback loop.
        """
        if 'sr_driver' in self:
            del self.sr_driver
        self.close()

    def sr_driver_set(self, driver):
        self.sr_driver = driver

    def sr_on_exception(self):
        self.on_close()
        self.close()


class _ServerReq(tornado.web.RequestHandler):
    SUPPORTED_METHODS = ["POST"]
    sr_class = job_supervisor.ServerReq

    def on_connection_close(self):
        # Nothing we can do with the request. Even if a user
        # closes a browser or laptop, we will want to continue with
        # the simulation run request. Only in specific cases would
        # we want to terminate processing, but that cancel problem is
        # quite hard, and not likely we are consuming too many resources.
        #
        # By not having a connection to supervisor (for on_close), we
        # avoid data structure loops.
        pass

    async def post(self):
        await _incoming(self.request.body, self)

    def set_default_headers(self):
        self.set_header("Content-Type", 'application/json; charset="utf-8"')

    def sr_on_exception(self):
        self.send_error()
        self.on_connection_close()


async def _incoming(content, handler):
    try:
        c = pkjson.load_any(content)
        pkdc('class={} content={}', handler.sr_class, job.LogFormatter(c))
        await handler.sr_class(handler=handler, content=c).receive()
    except Exception as e:
        pkdlog('exception={} handler={} content={}', e, content, handler)
        pkdlog(pkdexc())
        try:
            handler.sr_on_exception()
        except Exception as e:
            pkdlog('sr_on_exception: exception={}', e)


def _sigterm(signum, frame):
    tornado.ioloop.IOLoop.current().add_callback_from_signal(_terminate)


def _terminate():
    try:
        job_supervisor.terminate()
    except Exception as e:
        pkdlog('job_supervisor.terminate except={} stack={}', e, pkdexc())
    tornado.ioloop.IOLoop.current().stop()
