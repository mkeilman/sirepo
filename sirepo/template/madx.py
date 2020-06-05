# -*- coding: utf-8 -*-
u"""MAD-X execution template.

:copyright: Copyright (c) 2020 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from pykern import pkcompat
from pykern import pkio
from pykern import pkjinja
from pykern.pkcollections import PKDict
from pykern.pkdebug import pkdp, pkdc, pkdlog
from sirepo import simulation_db
from sirepo.template import code_variable
from sirepo.template import elegant_command_importer
from sirepo.template import elegant_lattice_importer
from sirepo.template import lattice
from sirepo.template import madx_converter, madx_parser
from sirepo.template import sdds_util
from sirepo.template import template_common
from sirepo.template.template_common import ParticleEnergy
from sirepo.template.lattice import LatticeUtil
import copy
import math
import numpy as np
import pykern.pkinspect
import re
import sirepo.sim_data


_FILE_TYPES = ['ele', 'lte', 'madx']
MADX_INPUT_FILENAME = 'madx.in'
MADX_OUTPUT_FILENAME = 'madx.out'
TWISS_OUTPUT_FILENAME = 'twiss.tfs'

_SIM_DATA, SIM_TYPE, _SCHEMA = sirepo.sim_data.template_globals()

_PI = 4 * math.atan(1)
_MADX_CONSTANTS = PKDict(
    pi=_PI,
    twopi=_PI * 2.0,
    raddeg=180.0 / _PI,
    degrad=_PI / 180.0,
    e=math.exp(1),
    emass=0.510998928e-03,
    pmass=0.938272046e+00,
    nmass=0.931494061+00,
    mumass=0.1056583715,
    clight=299792458.0,
    qelect=1.602176565e-19,
    hbar=6.58211928e-25,
    erad=2.8179403267e-15,
)

_METHODS = template_common.RPN_METHODS.extend([])


def get_application_data(data, **kwargs):
    if 'method' not in data:
        raise RuntimeError('no application data method')
    if data.method not in _METHODS:
        raise RuntimeError('unknown application data method: {}'.format(data.method))
    #if data.method in template_common.RPN_METHODS:
    #    return template_common.get_rpn_data(data, _SCHEMA, _MADX_CONSTANTS)
    cv = code_variable.CodeVar(
        data.variables,
        code_variable.PurePythonEval(_MADX_CONSTANTS),
        case_insensitive=True,
    )
    if data.method == 'rpn_value':
        # accept array of values enclosed in curly braces
        if re.search(r'^\{.*\}$', data.value):
            data.result = ''
            return data
        v, err = cv.eval_var(data.value)
        if err:
            data.error = err
        else:
            data.result = v
        return data
    if data.method == 'recompute_rpn_cache_values':
        cv(data.variables).recompute_cache(data.cache)
        return data
    if data.method == 'validate_rpn_delete':
        model_data = simulation_db.read_json(
            simulation_db.sim_data_file(data.simulationType, data.simulationId))
        data.error = cv(data.variables).validate_var_delete(
            data.name,
            model_data,
            _SCHEMA
        )
        return data


# TODO(e-carlin): need to clean this up. copied from elegant
# ex _map_commands_to_lattice doesn't exist in this file only in elegant
def import_file(req, test_data=None, **kwargs):
    ft = '|'.join(_FILE_TYPES)
    if not re.search(r'\.({})$'.format(ft), req.filename, re.IGNORECASE):
        raise IOError('invalid file extension, expecting one of {}'.format(_FILE_TYPES))
    # input_data is passed by test cases only
    input_data = test_data
    text = pkcompat.from_bytes(req.file_stream.read())
    if 'simulationId' in req.req_data:
        input_data = simulation_db.read_simulation_json(SIM_TYPE, sid=req.req_data.simulationId)
    if re.search(r'\.ele$', req.filename, re.IGNORECASE):
        data = elegant_command_importer.import_file(text)
    elif re.search(r'\.lte$', req.filename, re.IGNORECASE):
        data = elegant_lattice_importer.import_file(text, input_data)
        if input_data:
            _map_commands_to_lattice(data)
    elif re.search(r'\.madx$', req.filename, re.IGNORECASE):
        #madx = madx_parser.parse_file(text, downcase_variables=True)
        #data = madx_converter.from_madx(
        #    SIM_TYPE,
        #    madx_parser.parse_file(text, downcase_variables=True)
        #)
        #mm = madx_parser.parse_file(text, downcase_variables=True)
        #pkdp('MADX {} VS DATA {}', mm, data)
        data = madx_parser.parse_file(text, downcase_variables=True)
        madx_converter.fixup_madx(data)
    else:
        raise IOError('invalid file extension, expecting .ele or .lte')
    data.models.simulation.name = re.sub(
        r'\.({})$'.format(ft),
        '',
        req.filename,
        flags=re.IGNORECASE
    )
    if input_data and not test_data:
        simulation_db.delete_simulation(
            SIM_TYPE,
            input_data.models.simulation.simulationId
        )
    return data


def madx_code_var(variables):
    return _code_var(variables)


def prepare_sequential_output_file(run_dir, data):
    r = data.report
    if r == 'twissReport':
        f = simulation_db.json_filename(template_common.OUTPUT_BASE_NAME, run_dir)
        if f.exists():
            f.remove()
            save_sequential_report_data(data, run_dir)


def python_source_for_model(data, model):
    return _generate_parameters_file(data)


def save_sequential_report_data(data, run_dir):
    template_common.write_sequential_result(
        _extract_report_data(data, run_dir),
        run_dir=run_dir,
    )


def write_parameters(data, run_dir, is_parallel):
    """Write the parameters file

    Args:
        data (dict): input
        run_dir (py.path): where to write
        is_parallel (bool): run in background?
    """
    pkdp('WRITE P ||? {}', is_parallel)
    pkio.write_text(
        run_dir.join(MADX_INPUT_FILENAME),
        _generate_parameters_file(data),
    )


def _code_var(variables):
    return code_variable.CodeVar(
        variables,
        code_variable.PurePythonEval(_MADX_CONSTANTS),
        case_insensitive=True,
    )


def _extract_report_data(data, run_dir):
    if 'twissEllipse' in data.report:
        return _extract_report_twissEllipseReport(data, run_dir)
    #if 'bunchReport' in data.report:
    #    return _extract_report_bunchReport(data, run_dir)
    return getattr(
       pykern.pkinspect.this_module(),
       '_extract_report_' + data.report,
    )(data, run_dir)


def _extract_report_twissEllipseReport(data, run_dir):
    util = LatticeUtil(data, _SCHEMA)
    m = util.find_first_command(data, 'twiss')
    #pkdp('TWISS FOUND {}', m)
    # must an initial twiss always exist?
    if not m:
        return template_common.parameter_plot([], [], None, PKDict())
    r_model = data.models[data.report]
    dim = r_model.dim
    plots = []
    n_pts = 200
    theta = np.arange(0, 2. * np.pi * (n_pts / (n_pts - 1)), 2. * np.pi / n_pts)
    alf = 'alf{}'.format(dim)
    bet = 'bet{}'.format(dim)
    a = m[alf]
    b = m[bet]
    g = (1. + a * a) / b
    #pkdp('ELLIPSE A {} B {}', a, b)
    eta = 'e{}'.format(dim)
    e = m[eta] if eta in m else 1.0
    phi = _ellipse_rot(a, b)
    th = theta - phi
    #pkdp('ELLIPSE ROT {}', phi)
    mj = math.sqrt(e * b)
    mn = 1.0 / mj
    r = np.power(
        mn * np.cos(th) * np.cos(th) + mj * np.sin(th) * np.sin(th),
        -0.5
    )
    #pkdp('ELLIPSE R(TH) {}', r)
    x = r * np.cos(theta)
    y = r * np.sin(theta)
    p = PKDict(field=dim, points=y.tolist(), label=f'{dim}\' [rad]')
    plots.append(
        p
    )
    return template_common.parameter_plot(
        x.tolist(),
        plots,
        {},
        PKDict(
            title=f'{data.models.simulation.name} a{dim} = {a} b{dim} = {b} g{dim} = {g}',
            y_label='',
            x_label=f'{dim} [m]'
        )
    )


def _extract_report_bunchReport(data, run_dir):
    pkdp('EXTRACT BUNCH')
    util = LatticeUtil(data, _SCHEMA)
    m = util.find_first_command(data, 'twiss')
    #pkdp('TWISS FOUND {}', m)
    # must an initial twiss always exist?
    if not m:
        return template_common.parameter_plot([], [], None, PKDict())
    r_model = data.models[data.report]
    dim = r_model.dim
    plots = []
    n_pts = 200
    theta = np.arange(0, 2. * np.pi * (n_pts / (n_pts - 1)), 2. * np.pi / n_pts)
    alf = 'alf{}'.format(dim)
    bet = 'bet{}'.format(dim)
    a = m[alf]
    b = m[bet]
    g = (1. + a * a) / b
    #pkdp('ELLIPSE A {} B {}', a, b)
    eta = 'e{}'.format(dim)
    e = m[eta] if eta in m else 1.0
    phi = _ellipse_rot(a, b)
    th = theta - phi
    #pkdp('ELLIPSE ROT {}', phi)
    mj = math.sqrt(e * b)
    mn = 1.0 / mj
    r = np.power(
        mn * np.cos(th) * np.cos(th) + mj * np.sin(th) * np.sin(th),
        -0.5
    )
    #pkdp('ELLIPSE R(TH) {}', r)
    x = r * np.cos(theta)
    y = r * np.sin(theta)
    p = PKDict(field=dim, points=y.tolist(), label=f'{dim}\' [rad]')
    plots.append(
        p
    )
    return template_common.parameter_plot(
        x.tolist(),
        plots,
        {},
        PKDict(
            title=f'{data.models.simulation.name} a{dim} = {a} b{dim} = {b} g{dim} = {g}',
            y_label='',
            x_label=f'{dim} [m]'
        )
    )

def _ellipse_rot(a, b):
    if a == 0:
        return 0
    return 0.5 * math.atan(
        2. * a * b / (1 + a * a - b * b)
    )

def _extract_report_twissReport(data, run_dir):
    t = madx_parser.parse_tfs_file(run_dir.join(TWISS_OUTPUT_FILENAME))
    m = data.models[data.report]
    plots = []
    for f in ('y1', 'y2', 'y3'):
        if m[f] == 'none':
            continue
        plots.append(
            PKDict(field=m[f], points=t[m[f]], label=f'{m[f]} [m]')
        )
    return template_common.parameter_plot(
        t.s,
        plots,
        m,
        PKDict(title=data.models.simulation.name, y_label='', x_label='s[m]')
    )


def _generate_commands(util):
    res = ''
    for c in util.iterate_models(
            lattice.ElementIterator(None, _format_field_value), 'commands'
    ).result:
        res += f'{c[0]._type}'
        for f in c[1]:
           res += f', {f[0]}={f[1]}'
        if c[0]._type == 'twiss':
            res += f', file={TWISS_OUTPUT_FILENAME}'
        res += ';\n'
    return res


def _generate_lattice(util):
    filename_map = PKDict()
    return util.render_lattice_and_beamline(
        lattice.LatticeIterator(filename_map, _format_field_value),
        want_semicolon=True)


def _generate_parameters_file(data):
    pkdp('GEN P')
    res, v = template_common.generate_parameters_file(data)
    util = LatticeUtil(data, _SCHEMA)
    c = _generate_commands(util)
    code_var = _code_var(data.models.rpnVariables)
    v.twissOutputFilename = TWISS_OUTPUT_FILENAME
    v.lattice = _generate_lattice(util)
    v.variables = _generate_variables(code_var, data)
    if data.models.simulation.visualizationBeamlineId:
        v.useBeamline = util.id_map[data.models.simulation.visualizationBeamlineId].name
        v.commands = _generate_commands(util)
        v.hasTwiss = bool(util.find_first_command(data, 'twiss'))
        if not v.hasTwiss:
            v.twissOutputFilename = TWISS_OUTPUT_FILENAME
    return template_common.render_jinja(SIM_TYPE, v, 'parameters.madx')


def _generate_variable(name, variables, visited):
    res = ''
    if name not in visited:
        res += 'REAL {} = {};\n'.format(name, variables[name])
        visited[name] = True
    return res


def _generate_variables(code_var, data):
    res = ''
    visited = PKDict()
    for name in sorted(code_var.variables):
        for dependency in code_var.get_expr_dependencies(code_var.postfix_variables[name]):
            res += _generate_variable(dependency, code_var.variables, visited)
        res += _generate_variable(name, code_var.variables, visited)
    return res


def _format_field_value(state, model, field, el_type):
    #pkdp('FORMAT ST {} M {} F {} T {}', state, model, field, el_type)
    v = model[field]
    if el_type == 'Boolean':
        v = 'true' if v == '1' else 'false'
    elif el_type == 'LatticeBeamlineList':
        v = state.id_map[int(v)].name
    return [field, v]
