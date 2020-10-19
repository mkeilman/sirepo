# -*- coding: utf-8 -*-
u"""Common execution template.

:copyright: Copyright (c) 2015 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from pykern import pkcompat
from pykern import pkio
from pykern import pkjinja
from pykern.pkcollections import PKDict
from pykern.pkdebug import pkdc, pkdlog, pkdp, pkdexc
from sirepo.template import code_variable
import math
import numpy
import pykern.pkrunpy
import re
import sirepo.http_reply
import sirepo.http_request
import sirepo.sim_data
import sirepo.template
import sirepo.util
import subprocess
import sys
import types


DEFAULT_INTENSITY_DISTANCE = 20

#: Input json file
INPUT_BASE_NAME = 'in'

#: Test if value is numeric text
NUMERIC_RE = re.compile(r'^\s*(\-|\+)?(\d+|(\d*(\.\d*)))([eE][+-]?\d+)?\s*$')

#: Output json file
OUTPUT_BASE_NAME = 'out'

#: Python file (not all simulations)
PARAMETERS_PYTHON_FILE = 'parameters.py'

#: stderr and stdout
RUN_LOG = 'run.log'

_HISTOGRAM_BINS_MAX = 500

_PLOT_LINE_COLOR = ['#1f77b4', '#ff7f0e', '#2ca02c']


class ModelUnits():
    """Convert model fields from native to sirepo format, or from sirepo to native format.

    Examples::
        def _xpas(value, is_native):
            # custom field conversion code would go here
            return value

        mu = ModelUnits({
            'CHANGREF': {
                'XCE': 'cm_to_m',
                'YCE': 'cm_to_m',
                'ALE': 'deg_to_rad',
                'XPAS': _xpas,
            },
        })
        m = mu.scale_from_native('CHANGREF', {
            'XCE': 2,
            'YCE': 0,
            'ALE': 8,
            'XPAS': '#20|20|20',
        })
        assert m['XCE'] == 2e-2
        assert ModelUnits.scale_value(2, 'cm_to_m', True) == 2e-2
        assert ModelUnits.scale_value(0.02, 'cm_to_m', False) == 2
    """

    # handler for common units, native --> sirepo scale
    _COMMON_HANDLERS = PKDict(
        cm_to_m=1e-2,
        mm_to_cm=1e-1,
        mrad_to_rad=1e-3,
        deg_to_rad=math.pi / 180,
    )

    def __init__(self, unit_def):
        """
        Args:
            unit_def (dict):
            Map of model name to field handlers
        """
        self.unit_def = unit_def

    def scale_from_native(self, name, model):
        """ Scale values from native values into sirepo units. """
        return self.__scale_model(name, model, True)

    def scale_to_native(self, name, model):
        """ Scale values from sirepo units to native values. """
        return self.__scale_model(name, model, False)

    @classmethod
    def scale_value(cls, value, scale_type, is_native):
        """ Scale one value using the specified handler. """
        handler = cls._COMMON_HANDLERS.get(scale_type, scale_type)
        if isinstance(handler, float):
            return float(value) * (handler if is_native else 1 / handler)
        assert isinstance(handler, types.FunctionType), \
            'Unknown unit scale: {}'.format(handler)
        return handler(value, is_native)

    def __scale_model(self, name, model, is_native):
        if name in self.unit_def:
            for field in self.unit_def[name]:
                if field not in model:
                    continue
                model[field] = self.scale_value(
                    model[field],
                    self.unit_def[name][field],
                    is_native)
        return model


class ParticleEnergy():
    """Computes the energy related fields for a particle from one field.
    Units:
        mass [GeV/c^2]
        pc [GeV/c]
        energy [GeV]
        brho [Tm]
    """
    SPEED_OF_LIGHT = 299792458 # [m/s]

    ENERGY_PRIORITY = PKDict(
        opal=['gamma', 'energy', 'pc'],
        madx=['energy', 'pc', 'gamma', 'beta', 'brho'],
    )

    PARTICLE = PKDict(
        # mass [GeV]
        antiproton=PKDict(
            mass=0.938272046,
            charge=-1,
        ),
        electron=PKDict(
            mass=5.10998928e-4,
            charge=-1,
        ),
        muon=PKDict(
            mass=0.1056583755,
            charge=-1.0,
        ),
        positron=PKDict(
            mass=5.10998928e-4,
            charge=1,
        ),
        proton=PKDict(
            mass=0.938272046,
            charge=1,
        ),
    )

    @classmethod
    def compute_energy(cls, sim_type, particle, energy):
        p = cls.PARTICLE[particle] if particle in cls.PARTICLE else PKDict(
            mass=energy.mass,
            charge=energy.charge
        )
        for f in cls.ENERGY_PRIORITY[sim_type]:
            if f in energy and energy[f] != 0:
                v = energy[f]
                handler = '_ParticleEnergy__set_from_{}'.format(f)
                getattr(cls, handler)(p, energy)
                energy[f] = v
                return energy
        assert False, 'missing energy field: {}'.format(energy)

    @classmethod
    def __set_from_beta(cls, particle, energy):
        assert energy.beta >= 0 or energy.beta < 1, \
            'energy beta out of range: {}'.format(energy.beta)
        energy.gamma = 1 / math.sqrt(1 - energy.beta ** 2)
        cls.__set_from_gamma(particle, energy)

    @classmethod
    def __set_from_brho(cls, particle, energy):
        energy.pc = energy.brho * abs(particle.charge) * cls.SPEED_OF_LIGHT * 1e-9
        cls.__set_from_pc(particle, energy)

    @classmethod
    def __set_from_energy(cls, particle, energy):
        energy.gamma = energy.energy / particle.mass
        cls.__set_from_gamma(particle, energy)

    @classmethod
    def __set_from_gamma(cls, particle, energy):
        assert energy.gamma >= 1, \
            'energy gamma out of range: {}'.format(energy.gamma)
        energy.energy = energy.gamma * particle.mass
        energy.kinetic_energy = energy.energy - particle.mass
        energy.beta = math.sqrt(1.0 - 1.0 / (energy.gamma ** 2))
        energy.pc = energy.gamma * energy.beta * particle.mass
        energy.brho = energy.pc / (abs(particle.charge) * cls.SPEED_OF_LIGHT * 1e-9)

    @classmethod
    def __set_from_pc(cls, particle, energy):
        r2 = energy.pc ** 2 / (particle.mass ** 2)
        energy.beta = math.sqrt(r2 / (1 + r2))
        cls.__set_from_beta(particle, energy)


def compute_field_range(args, compute_range):
    """ Computes the fieldRange values for all parameters across all animation files.
    Caches the value on the animation input file. compute_range() is called to
    read the simulation specific datafiles and extract the ranges by field.
    """
    from sirepo import simulation_db

    run_dir = simulation_db.simulation_run_dir(PKDict(
        simulationType=args['simulationType'],
        simulationId=args['simulationId'],
        report='animation',
    ))
    data = simulation_db.read_json(run_dir.join(INPUT_BASE_NAME))
    res = None
    model_name = args['modelName']
    if model_name in data.models:
        if 'fieldRange' in data.models[model_name]:
            res = data.models[model_name].fieldRange
        else:
            #TODO(pjm): second arg was never used
            res = compute_range(run_dir, None)
            data.models[model_name].fieldRange = res
            simulation_db.write_json(run_dir.join(INPUT_BASE_NAME), data)
    return PKDict(fieldRange=res)


def compute_plot_color_and_range(plots, plot_colors=None, fixed_y_range=None):
    """ For parameter plots, assign each plot a color and compute the full y_range.
    If a fixed range is provided, use that instead
    """
    y_range = fixed_y_range
    colors = plot_colors if plot_colors is not None else _PLOT_LINE_COLOR
    for i in range(len(plots)):
        plot = plots[i]
        plot['color'] = colors[i % len(colors)]
        if not plot['points']:
            y_range = [0, 0]
        elif fixed_y_range is None:
            vmin = min(plot['points'])
            vmax = max(plot['points'])
            if y_range:
                if vmin < y_range[0]:
                    y_range[0] = vmin
                if vmax > y_range[1]:
                    y_range[1] = vmax
            else:
                y_range = [vmin, vmax]
    # color child plots the same as parent
    for child in [p for p in plots if '_parent' in p]:
        parent = next((pr for pr in plots if 'label' in pr and pr['label'] == child['_parent']), None)
        if parent:
            child['color'] = parent['color'] if 'color' in parent else '#000000'
    return y_range


def dict_to_h5(d, hf, path=None):
    if path is None:
        path = ''
    try:
        for i in range(len(d)):
            try:
                p = '{}/{}'.format(path, i)
                hf.create_dataset(p, data=d[i])
            except TypeError:
                dict_to_h5(d[i], hf, path=p)
    except KeyError:
        for k in d:
            p = '{}/{}'.format(path, k)
            try:
                hf.create_dataset(p, data=d[k])
            except TypeError:
                dict_to_h5(d[k], hf, path=p)


def enum_text(schema, name, value):
    for e in schema['enum'][name]:
        if e[0] == value:
            return e[1]
    assert False, 'unknown {} enum value: {}'.format(name, value)


def exec_parameters(path=None):
    return pykern.pkrunpy.run_path_as_module(path or PARAMETERS_PYTHON_FILE)


def exec_parameters_with_mpi():
    import sirepo.mpi

    return sirepo.mpi.run_script(pkio.read_text(PARAMETERS_PYTHON_FILE))


def flatten_data(d, res, prefix=''):
    """Takes a nested dictionary and converts it to a single level dictionary with
    flattened keys."""
    for k in d:
        v = d[k]
        if isinstance(v, dict):
            flatten_data(v, res, prefix + k + '_')
        elif isinstance(v, list):
            pass
        else:
            res[prefix + k] = v
    return res


def generate_parameters_file(data):
    v = flatten_data(data['models'], PKDict())
    v['notes'] = _get_notes(v)
    return render_jinja(None, v, name='common-header.py'), v


def sim_frame(frame_id, op):
    f, s = sirepo.sim_data.parse_frame_id(frame_id)
    # document parsing the request
    sirepo.http_request.parse_post(req_data=f, id=True, check_sim_exists=True)
    try:
        x = op(f)
    except Exception as e:
        pkdlog('error generating report frame_id={} stack={}', frame_id, pkdexc())
        raise sirepo.util.convert_exception(e, display_text='Report not generated')
    r = sirepo.http_reply.gen_json(x)
    if 'error' not in x and s.want_browser_frame_cache():
        r.headers['Cache-Control'] = 'private, max-age=31536000'
    else:
        sirepo.http_reply.headers_for_no_cache(r)
    return r


def sim_frame_dispatch(frame_args):
    from sirepo import simulation_db

    frame_args.pksetdefault(
        run_dir=lambda: simulation_db.simulation_run_dir(frame_args),
    ).pksetdefault(
        sim_in=lambda: simulation_db.read_json(
            frame_args.run_dir.join(INPUT_BASE_NAME),
        ),
    )
    t = sirepo.template.import_module(frame_args.simulationType)
    o = getattr(t, 'sim_frame_' + frame_args.frameReport, None) \
        or getattr(t, 'sim_frame')
    res = o(frame_args)
    if res is None:
        raise RuntimeError('unsupported simulation_frame model={}'.format(frame_args.frameReport))
    return res


def h5_to_dict(hf, path=None):
    d = PKDict()
    if path is None:
        path = '/'
    try:
        for k in hf[path]:
            try:
                d[k] = hf[path][k][()].tolist()
            except AttributeError:
                p = '{}/{}'.format(path, k)
                d[k] = h5_to_dict(hf, path=p)
    except TypeError:
        # assume this is a single-valued entry
        return hf[path][()]
    # replace dicts with arrays on a 2nd pass
    d_keys = d.keys()
    try:
        indices = [int(k) for k in d_keys]
        d_arr = [None] * len(indices)
        for i in indices:
            d_arr[i] = d[str(i)]
        d = d_arr
    except ValueError:
        # keys not all integers, we're done
        pass
    return d


def heatmap(values, model, plot_fields=None):
    """Computes a report histogram (x_range, y_range, z_matrix) for a report model."""
    r = None
    if 'plotRangeType' in model:
        if model['plotRangeType'] == 'fixed':
            r = [
                _plot_range(model, 'horizontal'),
                _plot_range(model, 'vertical'),
            ]
        elif model['plotRangeType'] == 'fit' and 'fieldRange' in model:
            r = [
                model.fieldRange[model['x']],
                model.fieldRange[model['y']],
            ]
    hist, edges = numpy.histogramdd(
        values,
        histogram_bins(model['histogramBins']),
        range=r,
    )
    res = PKDict(
        x_range=[float(edges[0][0]), float(edges[0][-1]), len(hist)],
        y_range=[float(edges[1][0]), float(edges[1][-1]), len(hist[0])],
        z_matrix=hist.T.tolist(),
    )
    if plot_fields:
        res.update(plot_fields)
    return res


def histogram_bins(nbins):
    """Ensure the histogram count is in a valid range"""
    nbins = int(nbins)
    if nbins <= 0:
        nbins = 1
    elif nbins > _HISTOGRAM_BINS_MAX:
        nbins = _HISTOGRAM_BINS_MAX
    return nbins


def parameter_plot(x, plots, model, plot_fields=None, plot_colors=None):
    res = PKDict(
        x_points=x,
        x_range=[min(x), max(x)] if x else [0, 0],
        plots=plots,
        y_range=compute_plot_color_and_range(plots, plot_colors),
    )
    if 'plotRangeType' in model:
        if model.plotRangeType == 'fixed':
            res['x_range'] = _plot_range(model, 'horizontal')
            res['y_range'] = _plot_range(model, 'vertical')
        elif model.plotRangeType == 'fit' and 'fieldRange' in model:
            res['x_range'] = model.fieldRange[model.x]
            for i in range(len(plots)):
                r = model.fieldRange[plots[i]['field']]
                if r[0] < res['y_range'][0]:
                    res['y_range'][0] = r[0]
                if r[1] > res['y_range'][1]:
                    res['y_range'][1] = r[1]
    if plot_fields:
        res.update(plot_fields)
    return res


def parse_enums(enum_schema):
    """Returns a list of enum values, keyed by enum name."""
    res = PKDict()
    for k in enum_schema:
        res[k] = PKDict()
        for v in enum_schema[k]:
            res[k][v[0]] = True
    return res


def render_jinja(sim_type, v, name=PARAMETERS_PYTHON_FILE):
    """Render the values into a jinja template.

    Args:
        sim_type (str): application name
        v: flattened model data
    Returns:
        str: source text
    """
    d = sirepo.sim_data.get_class(sim_type).resource_dir() if sim_type \
        else sirepo.sim_data.resource_dir()
    return pkjinja.render_file(
        # append .jinja, because file may already have an extension
        d.join(name) + '.jinja',
        v,
    )


def validate_model(model_data, model_schema, enum_info):
    """Ensure the value is valid for the field type. Scales values as needed."""
    for k in model_schema:
        label = model_schema[k][0]
        field_type = model_schema[k][1]
        if k in model_data:
            value = model_data[k]
        elif len(model_schema[k]) > 2:
            value = model_schema[k][2]
        else:
            raise Exception('no value for field "{}" and no default value in schema'.format(k))
        if field_type in enum_info:
            if str(value) not in enum_info[field_type]:
                # Check a comma-delimited string against the enumeration
                for item in re.split(r'\s*,\s*', str(value)):
                    if item not in enum_info[field_type]:
                        assert item in enum_info[field_type], \
                            '{}: invalid enum "{}" value for field "{}"'.format(item, field_type, k)
        elif field_type == 'Float':
            if not value:
                value = 0
            v = float(value)
            if re.search(r'\[m(m|rad)]', label):
                v /= 1000
            elif re.search(r'\[n(m|rad)]', label) or re.search(r'\[nm/pixel\]', label):
                v /= 1e09
            elif re.search(r'\[ps]', label):
                v /= 1e12
            #TODO(pjm): need to handle unicode in label better (mu)
            elif re.search('\\[\xb5(m|rad)]', label) or re.search(r'\[mm-mrad]', label):
                v /= 1e6
            model_data[k] = float(v)
        elif field_type == 'Integer':
            if not value:
                value = 0
            model_data[k] = int(value)
        elif value is None:
            # value is already None, do not convert
            pass
        else:
            model_data[k] = _escape(value)


def validate_models(model_data, model_schema):
    """Validate top-level models in the schema. Returns enum_info."""
    enum_info = parse_enums(model_schema['enum'])
    for k in model_data['models']:
        if k in model_schema['model']:
            validate_model(
                model_data['models'][k],
                model_schema['model'][k],
                enum_info,
            )
    if 'beamline' in model_data['models']:
        for m in model_data['models']['beamline']:
            validate_model(m, model_schema['model'][m['type']], enum_info)
    return enum_info


def file_extension_ok(file_path, white_list=None, black_list=['py', 'pyc']):
    """Determine whether a file has an acceptable extension

    Args:
        file_path (str): name of the file to examine
        white_list ([str]): list of file types allowed (defaults to empty list)
        black_list ([str]): list of file types rejected (defaults to
            ['py', 'pyc']). Ignored if white_list is not empty
    Returns:
        If file is a directory: True
        If white_list non-empty: True if the file's extension matches any in
        the list, otherwise False
        If white_list is empty: False if the file's extension matches any in
        black_list, otherwise True
    """
    import os

    if os.path.isdir(file_path):
        return True
    if white_list:
        in_list = False
        for ext in white_list:
            in_list = in_list or pkio.has_file_extension(file_path, ext)
        if not in_list:
            return False
        return True
    for ext in black_list:
        if pkio.has_file_extension(file_path, ext):
            return False
    return True


def read_sequential_result(run_dir):
    """Read result data file from simulation

    Args:
        run_dir (py.path): where to find output

    Returns:
        dict: result
    """
    from sirepo import simulation_db

    return simulation_db.read_json(
        simulation_db.json_filename(OUTPUT_BASE_NAME, run_dir),
    )


def subprocess_output(cmd, env):
    """Run cmd and return output or None, logging errors.

    Args:
        cmd (list): what to run
    Returns:
        str: output is None on error else a stripped string
    """
    err = None
    out = None
    try:

        p = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out, err = p.communicate()
        if p.wait() != 0:
            raise subprocess.CalledProcessError(returncode=p.returncode, cmd=cmd)
    except subprocess.CalledProcessError as e:
        pkdlog('{}: exit={} err={}', cmd, e.returncode, err)
        return None
    if out:
        out = pkcompat.from_bytes(out)
        return out.strip()
    return ''


def write_sequential_result(result, run_dir=None):
    """Write the results of a sequential simulation to disk.

    Args:
        result (dict): The results of the simulation
        run_dir (py.path): Defaults to current dir
    """
    from sirepo import simulation_db

    if not run_dir:
        run_dir = pkio.py_path()
    f = simulation_db.json_filename(OUTPUT_BASE_NAME, run_dir)
    assert not f.exists(), \
        '{} file exists'.format(OUTPUT_BASE_NAME)
    simulation_db.write_json(f, result)
    t = sirepo.template.import_module(
        simulation_db.read_json(
            simulation_db.json_filename(
                INPUT_BASE_NAME,
                run_dir,
            ),
        ),
    )
    if hasattr(t, 'clean_run_dir'):
        t.clean_run_dir(run_dir)


def _escape(v):
    return re.sub(r'[\"\'()]', '', str(v))


def _get_notes(data):
    notes = []
    for key in data.keys():
        match = re.search(r'^(.+)_notes$', key)
        if match and data[key]:
            n_key = match.group(1)
            k = n_key[0].capitalize() + n_key[1:]
            k_words = [word for word in re.split(r'([A-Z][a-z]*)', k) if word != '']
            notes.append((' '.join(k_words), data[key]))
    return sorted(notes, key=lambda n: n[0])


def _plot_range(report, axis):
    half_size = float(report['{}Size'.format(axis)]) / 2.0
    midpoint = float(report['{}Offset'.format(axis)])
    return [midpoint - half_size, midpoint + half_size]
