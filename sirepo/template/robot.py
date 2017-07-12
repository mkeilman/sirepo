# -*- coding: utf-8 -*-
u"""Robot execution template.

:copyright: Copyright (c) 2017 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import absolute_import, division, print_function
from pykern import pkcollections
from pykern import pkio
from pykern import pkjinja
from pykern.pkdebug import pkdc, pkdp
from sirepo import simulation_db
from sirepo.template import template_common
import ctypes
import dicom
import numpy as np
import os
import os.path
import py.path
import struct
import werkzeug
import zipfile

SIM_TYPE = 'robot'

WANT_BROWSER_FRAME_CACHE = True

_CT_DICOM_CLASS = '1.2.840.10008.5.1.4.1.1.2'
_DICOM_DIR = 'dicom'
_DICOM_MAX_VALUE = 2000
_DICOM_MIN_VALUE = -1250
_EXPECTED_ORIENTATION = np.array([1, 0, 0, 0, 1, 0])
_INT_SIZE = ctypes.sizeof(ctypes.c_int)
_PIXEL_FILE = 'pixels3d.dat'
_ROI_FILE_NAME = 'rs4pi-roi-data.json'
_RTSTRUCT_DICOM_CLASS = '1.2.840.10008.5.1.4.1.1.481.3'
_TMP_INPUT_FILE_FIELD = 'tmpDicomFilePath'
_TMP_ZIP_DIR = 'tmp-dicom-files'
_ZIP_FILE_NAME = 'input.zip'


def background_percent_complete(report, run_dir, is_running, schema):
    data_path = run_dir.join(template_common.INPUT_BASE_NAME)
    if not os.path.exists(str(simulation_db.json_filename(data_path))):
        return {
            'percentComplete': 0,
            'frameCount': 0,
        }
    return {
        'percentComplete': 100,
        # real frame count depends on the series selected
        'frameCount': 1,
        'errors': '',
    }


def copy_related_files(data, source_path, target_path):
    #TODO(pjm): copy pixel and roi files
    #py.path.local(source_path).join(_DICOM_DIR).copy(py.path.local(target_path))
    pass


def fixup_old_data(data):
    pass


def get_animation_name(data):
    return 'animation'


def get_application_data(data):
    if data['method'] == 'roi_points':
        return _read_roi_file(data['simulationId'])
    else:
        raise RuntimeError('{}: unknown application data method'.format(data['method']))


def get_simulation_frame(run_dir, data, model_data):
    frame_index = int(data['frameIndex'])
    args = data['animationArgs'].split('_')
    if data['modelName'].startswith('dicomAnimation'):
        plane = args[0]
        res = simulation_db.read_json(_dicom_path(model_data['models']['simulation'], plane, frame_index))
        res['pixel_array'] = _read_pixel_plane(plane, frame_index, model_data)
        return res
    raise RuntimeError('{}: unknown simulation frame model'.format(data['modelName']))


def import_file(request, lib_dir=None, tmp_dir=None):
    f = request.files['file']
    filename = werkzeug.secure_filename(f.filename)
    if not pkio.has_file_extension(str(filename), 'zip'):
        raise RuntimeError('unsupported import filename: {}'.format(filename))
    filepath = str(tmp_dir.join(_ZIP_FILE_NAME))
    f.save(filepath)
    data = simulation_db.default_data(SIM_TYPE)
    data['models']['simulation']['name'] = filename
    data['models']['simulation'][_TMP_INPUT_FILE_FIELD] = filepath
    # more processing occurs below in prepare_for_client() after simulation dir is prepared
    return data


def lib_files(data, source_lib):
    return template_common.internal_lib_files([], source_lib)


def models_related_to_report(data):
    return []


def new_simulation(data, new_simulation_data):
    pass


def prepare_aux_files(run_dir, data):
    template_common.copy_lib_files(data, None, run_dir)


def prepare_for_client(data):
    if _TMP_INPUT_FILE_FIELD in data['models']['simulation']:
        _move_import_file(data)
    return data


def prepare_for_save(data):
    return data


def remove_last_frame(run_dir):
    pass


def resource_files():
    return []


def write_parameters(data, schema, run_dir, is_parallel):
    pass


def _calculate_domain(frame):
    position = _float_list(frame['ImagePositionPatient'])
    spacing = frame['PixelSpacing']
    shape = frame['shape']
    return [
        position,
        [
            position[0] + spacing[0] * shape[0],
            position[1] + spacing[1] * shape[1],
            position[2],
        ],
    ]


def _compute_histogram(simulation, frames):
    pixels = []
    for frame in frames:
        pixels.append(frame['pixels'])
    histogram = _histogram_from_pixels(pixels)
    filename = _roi_file(simulation['simulationId'])
    if os.path.exists(filename):
        roi_data = _read_roi_file(simulation['simulationId'])
    else:
        roi_data = {
            'models': {
                'regionsOfInterest': {},
            },
        }
    roi_data['models']['dicomHistogram'] = histogram
    simulation_db.write_json(filename, roi_data)


def _dicom_path(simulation, plane, idx):
    return str(py.path.local(_sim_file(simulation['simulationId'], _DICOM_DIR)).join(_frame_file_name(plane, idx)))


def _extract_series_frames(simulation, dicom_dir):
    #TODO(pjm): give user a choice between multiple study/series if present
    selected_series = None
    series_description = ''
    frames = {}
    for path in pkio.walk_tree(dicom_dir):
        if pkio.has_file_extension(str(path), 'dcm'):
            plan = dicom.read_file(str(path))
            if plan.SOPClassUID == _RTSTRUCT_DICOM_CLASS:
                _summarize_rt_structure(simulation, plan)
            if plan.SOPClassUID != _CT_DICOM_CLASS:
                continue
            orientation = _float_list(plan.ImageOrientationPatient)
            if not (_EXPECTED_ORIENTATION == orientation).all():
                continue
            if not selected_series:
                selected_series = plan.SeriesInstanceUID
                if hasattr(plan, 'SeriesDescription'):
                    series_description = plan.SeriesDescription
            if selected_series != plan.SeriesInstanceUID:
                continue
            info = {
                'pixels': np.int32(plan.pixel_array),
                'shape': plan.pixel_array.shape,
                'ImagePositionPatient': _string_list(plan.ImagePositionPatient),
                'ImageOrientationPatient': _float_list(plan.ImageOrientationPatient),
                'PixelSpacing': _float_list(plan.PixelSpacing),
            }
            for f in ('StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID'):
                info[f] = getattr(plan, f)
            z = float(info['ImagePositionPatient'][2])
            if z in frames:
                raise RuntimeError('duplicate frame with z coord: {}'.format(z))
            _scale_pixel_data(plan, info['pixels'])
            frames[z] = info
    if not selected_series:
        raise RuntimeError('No series found with {} orientation'.format(_EXPECTED_ORIENTATION))
    res = []
    for z in sorted(frames.keys()):
        res.append(frames[z])
    return series_description, res


def _frame_info(count):
    return {
        'frameIndex': int(count / 2),
        'frameCount': count,
    }


def _float_list(ar):
    return map(lambda x: float(x), ar)


def _frame_file_name(plane, index):
    return plane + str(index).zfill(5)


def _histogram_from_pixels(pixels):
    m = 50
    extent = [np.array(pixels).min(), np.array(pixels).max()]
    if extent[0] < _DICOM_MIN_VALUE:
        extent[0] = _DICOM_MIN_VALUE
    if extent[1] > _DICOM_MAX_VALUE:
        extent[1] = _DICOM_MAX_VALUE
    span = extent[1] - extent[0]
    step = np.power(10, np.floor(np.log(span / m) / np.log(10)))
    err = float(m) / span * step
    if err <= .15:
        step *= 10
    elif err <= .35:
        step *= 5
    elif err <= .75:
        step *= 2
    e = [
        np.ceil(extent[0] / step) * step,
        np.floor(extent[1] / step) * step + step * .5,
        step,
    ]
    bins = np.ceil((e[1] - e[0]) / e[2])
    hist, edges = np.histogram(pixels, bins=bins, range=[e[0], e[0] + (bins - 1) * step])
    if hist[0] == hist.max():
        v = hist[0]
        hist[0] = 0
        if v > hist.max() * 2:
            hist[0] = hist.max() * 2
        else:
            hist[0] = v
    return {
        'histogram': hist.tolist(),
        'extent': [edges[0], edges[-1], bins],
    }


def _move_import_file(data):
    sim = data['models']['simulation']
    path = sim[_TMP_INPUT_FILE_FIELD]
    del sim[_TMP_INPUT_FILE_FIELD]
    if os.path.exists(path):
        zip_path = _sim_file(sim['simulationId'], _ZIP_FILE_NAME)
        os.rename(path, zip_path)
        pkio.unchecked_remove(os.path.dirname(path))
        tmp_dir = _sim_file(sim['simulationId'], _TMP_ZIP_DIR)
        zipfile.ZipFile(zip_path).extractall(tmp_dir)
        _summarize_dicom_files(data, tmp_dir)
        pkio.unchecked_remove(tmp_dir)
        simulation_db.save_simulation_json(SIM_TYPE, data)


def _pixel_filename(simulation):
    return _sim_file(simulation['simulationId'], _PIXEL_FILE)


def _read_pixel_plane(plane, idx, data):
    plane_info = data['models']['dicomSeries']['planes']
    size = [plane_info['c']['frameCount'], plane_info['s']['frameCount'], plane_info['t']['frameCount']]
    frame = []
    # pixels = np.array(all_frame_pixels)[:, idx]
    # pixels = np.array(all_frame_pixels)[:, :, idx]
    with open (_pixel_filename(data['models']['simulation']), 'rb') as f:
        if plane == 't':
            if idx > 0:
                f.seek(idx * _INT_SIZE * size[0] * size[1], 1)
            for r in range(size[1]):
                row = []
                frame.append(row)
                for v in range(size[0]):
                    row.append(struct.unpack('i', f.read(_INT_SIZE))[0])
        elif plane == 'c':
            if idx > 0:
                f.seek(idx * _INT_SIZE * size[0], 1)
            for r in range(size[2]):
                row = []
                frame.append(row)
                for v in range(size[0]):
                    row.append(struct.unpack('i', f.read(_INT_SIZE))[0])
                f.seek(_INT_SIZE * (size[0] - 1) * size[1], 1)
            frame = np.flipud(frame).tolist()
        elif plane == 's':
            if idx > 0:
                f.seek(idx * _INT_SIZE, 1)
            for r in range(size[2]):
                row = []
                frame.append(row)
                for v in range(size[1]):
                    row.append(struct.unpack('i', f.read(_INT_SIZE))[0])
                    f.seek(_INT_SIZE * (size[0] - 1), 1)
            frame = np.flipud(frame).tolist()
        else:
            raise RuntimeError('plane not supported: {}'.format(plane))
    return frame


def _read_roi_file(sim_id):
    return simulation_db.read_json(_roi_file(sim_id))


def _roi_file(sim_id):
    return _sim_file(sim_id, _ROI_FILE_NAME)


def _scale_pixel_data(plan, pixels):
    scale_required = False
    slope = 1
    offset = 0
    if 'RescaleSlope' in plan and plan.RescaleSlope != slope:
        slope = plan.RescaleSlope
        scale_required = True
    if 'RescaleIntercept' in plan and plan.RescaleIntercept != offset:
        offset = plan.RescaleIntercept
        scale_required = True
    if scale_required:
        pixels *= slope
        pixels += offset


def _sim_file(sim_id, filename):
    return str(simulation_db.simulation_dir(SIM_TYPE, sim_id).join(filename))


def _string_list(ar):
    return map(lambda x: str(x), ar)


def _summarize_dicom_files(data, dicom_dir):
    simulation = data['models']['simulation']
    series_description, frames = _extract_series_frames(simulation, dicom_dir)
    _summarize_dicom_series(simulation, frames)
    with open (_pixel_filename(simulation), 'wb') as f:
        for frame in frames:
            frame['pixels'].tofile(f)
    data['models']['dicomSeries'] = {
        'description': series_description,
        'planes': {
            't': _frame_info(len(frames)),
            's': _frame_info(len(frames[0]['pixels'])),
            'c': _frame_info(len(frames[0]['pixels'][0])),
        }
    }
    _compute_histogram(simulation, frames)


def _summarize_dicom_series(simulation, frames):
    idx = 0
    z_space = abs(float(frames[0]['ImagePositionPatient'][2]) - float(frames[1]['ImagePositionPatient'][2]))
    os.mkdir(_sim_file(simulation['simulationId'], _DICOM_DIR))
    for frame in frames:
        res = {
            'shape': frame['shape'],
            'ImagePositionPatient': frame['ImagePositionPatient'],
            'PixelSpacing': frame['PixelSpacing'],
            'domain': _calculate_domain(frame),
        }
        filename = _dicom_path(simulation, 't', idx)
        simulation_db.write_json(filename, res)
        idx += 1

    frame0 = frames[0]
    shape = [
        len(frames),
        len(frame0['pixels'][0]),
    ]
    res = {
        'shape': shape,
        'ImagePositionPatient': [
            frame0['ImagePositionPatient'][0],
            frame0['ImagePositionPatient'][2],
            frame0['ImagePositionPatient'][1],
        ],
        'PixelSpacing': [
            frame0['PixelSpacing'][0],
            z_space,
        ],
    }
    for idx in range(len(frame0['pixels'][0])):
        res['ImagePositionPatient'][2] = str(float(frame0['ImagePositionPatient'][1]) + idx * float(frame0['PixelSpacing'][0]))
        res['domain'] = _calculate_domain(res)
        filename = _dicom_path(simulation, 'c', idx)
        simulation_db.write_json(filename, res)

    shape = [
        len(frames),
        len(frame0['pixels'][1]),
    ]
    res = {
        'shape': shape,
        'ImagePositionPatient': [
            frame0['ImagePositionPatient'][1],
            frame0['ImagePositionPatient'][2],
            frame0['ImagePositionPatient'][0],
        ],
        'PixelSpacing': [
            frame0['PixelSpacing'][0],
            z_space,
        ],
    }
    for idx in range(len(frame0['pixels'][0])):
        res['ImagePositionPatient'][2] = str(float(frame0['ImagePositionPatient'][0]) + idx * float(frame0['PixelSpacing'][1]))
        res['domain'] = _calculate_domain(res)
        filename = _dicom_path(simulation, 's', idx)
        simulation_db.write_json(filename, res)


def _summarize_rt_structure(simulation, plan):
    data = {
        'models': {},
    }
    res = data['models']['regionsOfInterest'] = {}
    for roi in plan.StructureSetROISequence:
        res[roi.ROINumber] = {
            'name': roi.ROIName,
        }
    for roi_contour in plan.ROIContourSequence:
        roi = res[roi_contour.ReferencedROINumber]
        if 'contour' in roi:
            raise RuntimeError('duplicate contour sequence for roi')
        if not hasattr(roi_contour, 'ContourSequence'):
            continue
        roi['color'] = roi_contour.ROIDisplayColor
        roi['contour'] = {}
        for contour in roi_contour.ContourSequence:
            if contour.ContourGeometricType != 'CLOSED_PLANAR':
                continue
            if len(contour.ContourData):
                # the z index is the key
                ct_id = str(contour.ContourData[2])
                contour_data = _float_list(contour.ContourData)
                if len(contour_data) > 3 and float(ct_id) != contour_data[5]:
                    raise RuntimeError('expected contour data z to be equal')
                del contour_data[2::3]
                if ct_id not in roi['contour']:
                    roi['contour'][ct_id] = []
                roi['contour'][ct_id].append(contour_data)
    simulation_db.write_json(_roi_file(simulation['simulationId']), data)
