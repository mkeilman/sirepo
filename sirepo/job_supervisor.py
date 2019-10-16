# -*- coding: utf-8 -*-
"""TODO(e-carlin): Doc

:copyright: Copyright (c) 2019 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from pykern import pkcollections
from pykern import pkjson
from pykern.pkcollections import PKDict
from pykern.pkdebug import pkdp, pkdc, pkdlog, pkdexc
import aenum
import copy
import sirepo.driver
import sirepo.job
import sys
import time
import tornado.locks

_DATA_ACTIONS = (sirepo.job.ACTION_ANALYSIS, sirepo.job.ACTION_COMPUTE)

_OPERATOR_ACTIONS = (sirepo.job.ACTION_CANCEL,)


class AgentMsg(PKDict):

    async def do(self):
        pkdlog('content={}', self.content)
        d = sirepo.driver.get_instance_for_agent(self.content.agent_id)
        if not d:
            # TODO(e-carlin): handle
            pkdlog('no driver for agent_id={}', self.content.agent_id)
            return
        d.set_handler(self.handler)
        d.set_state(self.content)
        i = self.content.get('op_id')
        if not i:
            return
        d.ops[i].set_result(self.content)


def init():
    sirepo.job.init()
    sirepo.driver.init()


class Op(PKDict):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._result_set = tornado.locks.Event()
        self._result = None

    async def get_result(self):
        await self._result_set.wait()
        return self._result

    def set_result(self, res):
        self._result = res
        self._result_set.set()


class ServerReq(PKDict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.agent_dir = self.content.agent_dir
        self.compute_jid = self.content.compute_jid
        self.driver_kind = sirepo.driver.get_kind(self)
        self.run_dir = self.content.run_dir
        self.uid = self.content.uid
        # self._resource_class = sirepo.job
        self._response = None
        self._response_received = tornado.locks.Event()

    async def do(self):
        c = self.content
        if c.api == 'api_runStatus':
            # TODO(e-carlin): handle error from get_compute_status
            self.handler.write(await _Job.get_compute_status(self))
            return
        elif c.api == 'api_runSimulation':
            # TODO(e-carlin): handle error from get_compute_status
            s = await _Job.get_compute_status(self)
            if s not in sirepo.job.ALREADY_GOOD_STATUS:
                # TODO(e-carlin): Handle forceRun
                # TODO(e-carlin): Handle parametersChanged
                # TODO(e-carlin): only run job if no others running
                self.handler.write(
                    await _Job.run(self))
                return
        raise AssertionError('api={} unkown', c.api)


def terminate():
    sirepo.driver.terminate()


class _Job(PKDict):
    instances = PKDict()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.compute_hash = self.req.content.compute_hash
        self.compute_status = None
        self.jid = self._jid_for_req(self.req)
        self.instances[self.jid] = self
        self.last_update_time = time.time()
        self.start_time = time.time()

    def get_response(self, req):
        try:
            pkdp('in get_response. self is {}', self)
            # TODO(e-carlin): This only works for compute_jobs now. What about analysis jobs?
            i = self.get_job_info(req)
            res = PKDict(state=i.job_status)
            # TODO(e-carlin):  Job is not processing then send result op
            assert i.job_status in (sirepo.job.Status.RUNNING.value, sirepo.job.Status.MISSING.value)
            # TODO(e-carlin): handle parallel
            res.setdefault('startTime', self.start_time)
            res.setdefault('lastUpdateTime', self.last_update_time)
            res.setdefault('elapsedTime', res.lastUpdateTime - res.startTime)
            if self.compute_status in (
                sirepo.job.Status.PENDING.value,
                sirepo.job.Status.RUNNING.value
                ):
                res.nextRequestSeconds = 2 # TODO(e-carlin): use logic from simulation_db.poll_seconds()
                res.nextRequest = PKDict(
                    report=i.model_name,
                    reportParametersHash=i.cached_hash,
                    simulationId=i.simulation_id,
                    simulationType=i.simulation_type,
                )
        except Exception as e:
            pkdlog('error={} \n{}', e, pkdexc())
            return PKDict(error=e)
        return res

        def __repr__(self):
            return f'jid={self.jid} compute_status={self.compute_status} compute_hash={self.compute_hash}'
         

    def get_job_info(self, req):
        assert self.compute_status is not None
        i = pkcollections.Dict(
            cache_hit=False,
            cached_data=None,
            cached_hash=self.compute_hash,
            job_id=req.compute_jid,
            job_status=self.compute_status,
            model_name=req.content.compute_model,
            parameters_changed=False,
            req_hash=req.content.compute_hash,
            run_dir=req.content.run_dir,
            simulation_id=req.content.data.simulationId,
            simulation_type=req.content.sim_type,
        )
        if self.compute_status == sirepo.job.Status.MISSING.value:
            return i
        if i.req_hash == i.cached_hash:
            i.cache_hit = True
            return i
        i.parameters_changed = True
        return i

    @classmethod
    async def get_compute_status(cls, req):
        #TODO(robnagler) deal with non-in-memory job state (db?)
        self = cls.instances.get(cls._jid_for_req(req))
        if not self:
            self = cls(req=req)
        if self.compute_status is not None:
            return self.get_response(req)
            # return PKDict(statu=self.compute_status)
        d = await sirepo.driver.get_instance_for_job(self)
        # TODO(e-carlin): handle error response from do_op
        await d.do_op(
            op=sirepo.job.OP_COMPUTE_STATUS,
            jid=self.req.compute_jid,
            run_dir=self.req.run_dir,
        )
        return self.get_response(req)

    @classmethod
    async def run(cls, req):
        self = cls.instances.get(cls._jid_for_req(req))
        if not self:
            self = cls(req=req)
        d = await sirepo.driver.get_instance_for_job(self)
        # TODO(e-carlin): handle error response from do_op
        self.start_time = time.time()
        self.last_update_time = time.time()
        await d.do_op(
            op=sirepo.job.OP_RUN,
            jid=self.req.compute_jid,
            **self.req.content,
        )
        pkdp('22222222222222222222222222222222222222222')
        pkdp('about to get response for run request')
        pkdp(req.content.data.simulationId)
        pkdp('22222222222222222222222222222222222222222')
        return pkdp(self.get_response(req))

    @classmethod
    def _jid_for_req(cls, req):
        """Get the jid (compute or analysis) for a job from a request.
        """
        c = req.content
        if c.api in ('api_runStatus', 'api_runCancel', 'api_runSimulation'):
            return c.compute_jid
        if c.api in ('api_simulationFrame',):
            return c.analysis_jid
        raise AssertionError('unknown api={} req={}', c.api, req)