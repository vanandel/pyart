#!/usr/bin/python
# Generate and Save a Corrected Moments in Antenna Coordinates file
# usage : process_and_save_csapr_CMAC.py csapr_file.mdv outdir param_file

import sys
import copy

import netCDF4

from pyart.io import py4dd, radar, py_mdv, nc_utils
from pyart.correct import phase_proc, attenuation, dealias


def dt_to_dict(dt, **kwargs):
    pref = kwargs.get('pref', '')
    return dict([(pref+key, getattr(dt, key)) for key in
                ['year', 'month', 'day', 'hour', 'minute', 'second']])


def multiconvert(item, typ):
    if typ == 'string':
        ret = item.strip()
    if typ == 'bool':
        if item.strip().lower() == 'true':
            ret = True
        else:
            ret = False
    if typ == 'float':
        ret = float(item)
    if typ == 'int':
        ret = int(item)
    return ret


def parse_prefs(filename):
    bf = open(filename, 'r')
    text = bf.readlines()
    bf.close()
    params = {}
    metadata = {}
    for item in text:
        details = item.split(' ')
        data = item.split(details[1])
        if 'metadata' in details[0]:
            metadata.update({details[0].split('-')[0]: multiconvert(data[1],
                            details[1])})
        else:
            params.update({details[0]: multiconvert(data[1], details[1])})
    return params, metadata


if __name__ == "__main__":

    # First argument is file name of the CSAPR MDV file
    filename = sys.argv[1]
    # this is the directory and prefix of the file to save to..
    # the rest of the filename
    #is auto generated
    outdir = sys.argv[2]
    # Parse the input param file for parameters and metadata to append to
    # the netcdf file
    params, metadata = parse_prefs(sys.argv[3])
    # Where are my interpolated Sondes
    is_dir = params['sounding_dir']
    # Load the MDV File into a py-mdv object
    my_mdv_object = py_mdv.read_mdv(filename, debug=True)
    # generate a py-radar object from the py-mdv object
    myradar = radar.Radar(my_mdv_object)
    # append extra metadata
    myradar.metadata.update(metadata)
    # Here starts the velocity dealiasing
    # Get the target time for the radar
    target = netCDF4.num2date(myradar.time['data'][0], myradar.time['units'])
    # generate the filename for the ARM interpolated sonde we want to use
    fname = 'sgpinterpolatedsondeC1.c1.%(year)04d%(month)02d%(day)02d.000000.cdf' % radar.dt_to_dict(target)
    # read the ARM VAP
    interp_sonde = netCDF4.Dataset(is_dir + fname)
    # Get the right timestep in the file
    myheight, myspeed, mydirection = dealias.find_time_in_interp_sonde(
        interp_sonde, target)
    # Perform dealiasing using the UWash 4DD Dealias code (using TRMM RSL
    # carrier)
    my_new_field = dealias.dealias(myradar, myheight * 1000.0, myspeed,
                                   mydirection, target)
    # append the new field to the radar object
    myradar.fields.update({'corrected_mean_doppler_velocity': my_new_field})
    # Close out the ARM VAP file containing the sounding data
    interp_sonde.close()
    # Phase processing time, first calculate the number of the gates to
    # ignore phase jumps
    # This is needed as clutter can be both coherent and correlated and can
    # trick the phase folding algorithm, in this case we use 40km, may need
    # to change
    gates = myradar.range['data'][1] - myradar.range['data'][0]
    rge = 40.0 * 1000.0
    ng = rge / gates
    # Perform Linear programming phase processing to get the conditionally
    # fitted phase profile and sobel filtered KDP field
    reproc_phase, sob_kdp = phase_proc.phase_proc(
        myradar, params['reflectivity_offset'],
        sys_phase=params['sys_phase'],
        overide_sys_phase=params['overide_sys_phase'], debug=True, nowrap=ng)
    # Append these back into the radar object
    myradar.fields.update({'recalculated_diff_phase': sob_kdp,
                           'proc_dp_phase_shift': reproc_phase})
    # attenuation correction, this time we just use a straight procedural
    # method, this is a variant of the ZPHI technique and returns both the
    # specific attenuation (dBZ/km) and corrected Z (dBZ)
    # Note: no ZDR correction as of yet...
    spec_at, cor_z = attenuation.calculate_attenuation(
        myradar, params['reflectivity_offset'], debug=True, ncp_min=0.4)
    # Append these new fields to the radar object
    myradar.fields.update({'specific_attenuation': spec_at})
    myradar.fields.update({'corrected_reflectivity_horizontal': cor_z})
    # The following lines deal with determining file name
    mydatetime = netCDF4.num2date(myradar.time['data'][0],
                                  myradar.time['units'],
                                  calendar=myradar.time['calendar'])
    #append a datetime object
    mydict = dt_to_dict(mydatetime)
    mydict.update({
        'scanmode': {'ppi': 'sur', 'rhi': 'rhi'}[myradar.sweep_mode[0]],
        'fac': metadata['facility']})
    ofilename = outdir + '%(scanmode)scmac%(fac)s.c0.%(year)04d%(month)02d%(day)02d.%(hour)02d%(minute)02d%(second)02d.nc' % mydict
    # Open a netcdf file for output
    netcdf_obj = netCDF4.Dataset(ofilename, 'w', format='NETCDF4')
    # write a CF-Radial complaint netcdf file out
    nc_utils.write_radar4(netcdf_obj, myradar)
    netcdf_obj.close()
    #Fin!
