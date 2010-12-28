import numpy as np

from .constants import FIFF
from .open import fiff_open
from .evoked import read_meas_info
from .tree import dir_tree_find
from .tag import read_tag


def setup_read_raw(fname, allow_maxshield=False):
    """
    %
    % [data] = setup_read_raw(fname,allow_maxshield)
    %
    % Read information about raw data file
    %
    % fname               Name of the file to read
    % allow_maxshield     Accept unprocessed MaxShield data
    %
    """

    #   Open the file
    print 'Opening raw data file %s...' % fname
    fid, tree, _ = fiff_open(fname)

    #   Read the measurement info
    info, meas = read_meas_info(fid, tree)

    #   Locate the data of interest
    raw = dir_tree_find(meas, FIFF.FIFFB_RAW_DATA)
    if raw is None:
        raw = dir_tree_find(meas, FIFF.FIFFB_CONTINUOUS_DATA)
        if allow_maxshield:
            raw = dir_tree_find(meas, FIFF.FIFFB_SMSH_RAW_DATA)
            if raw is None:
                raise ValueError, 'No raw data in %s' % fname
        else:
            if raw is None:
                raise ValueError, 'No raw data in %s' % fname

    if len(raw) == 1:
        raw = raw[0]

    #   Set up the output structure
    info['filename'] = fname

    data = dict(fid=fid, info=info, first_samp=0, last_samp=0)

    #   Process the directory
    directory = raw['directory']
    nent = raw['nent']
    nchan = int(info['nchan'])
    first = 0
    first_samp = 0
    first_skip = 0

    #  Get first sample tag if it is there
    if directory[first].kind == FIFF.FIFF_FIRST_SAMPLE:
        tag = read_tag(fid, directory[first].pos)
        first_samp = int(tag.data)
        first += 1

    #  Omit initial skip
    if directory[first].kind == FIFF.FIFF_DATA_SKIP:
        #  This first skip can be applied only after we know the buffer size
        tag = read_tag(fid, directory[first].pos)
        first_skip = int(tag.data)
        first += first

    data['first_samp'] = first_samp

    #   Go through the remaining tags in the directory
    rawdir = list()
    nskip = 0
    for k in range(first, nent):
        ent = directory[k]
        if ent.kind == FIFF.FIFF_DATA_SKIP:
            tag = read_tag(fid, ent.pos)
            nskip = int(tag.data)
        elif ent.kind == FIFF.FIFF_DATA_BUFFER:
            #   Figure out the number of samples in this buffer
            if ent.type == FIFF.FIFFT_DAU_PACK16:
                nsamp = ent.size / (2.0*nchan)
            elif ent.type == FIFF.FIFFT_SHORT:
                nsamp = ent.size / (2.0*nchan)
            elif ent.type == FIFF.FIFFT_FLOAT:
                nsamp = ent.size / (4.0*nchan)
            elif ent.type == FIFF.FIFFT_INT:
                nsamp = ent.size / (4.0*nchan)
            else:
                fid.close()
                raise ValueError, 'Cannot handle data buffers of type %d' % ent.type

            #  Do we have an initial skip pending?
            if first_skip > 0:
                first_samp += nsamp*first_skip
                data['first_samp'] = first_samp
                first_skip = 0

            #  Do we have a skip pending?
            if nskip > 0:
                rawdir.append(dict(ent=None, first=first_samp,
                                   last=first_samp + nskip*nsamp - 1,
                                   nsamp=nskip*nsamp))
                first_samp += nskip*nsamp
                nskip = 0

            #  Add a data buffer
            rawdir.append(dict(ent=ent, first=first_samp,
                               last=first_samp + nsamp -1,
                               nsamp=nsamp))
            first_samp += nsamp

    data['last_samp'] = first_samp - 1

    #   Add the calibration factors
    cals = np.zeros(data['info']['nchan'])
    for k in range(data['info']['nchan']):
       cals[k] = data['info']['chs'][k]['range']*data['info']['chs'][k]['cal']

    data['cals'] = cals
    data['rawdir'] = rawdir
    data['proj'] = None
    data['comp'] = None
    print '\tRange : %d ... %d =  %9.3f ... %9.3f secs' % (
               data['first_samp'], data['last_samp'],
               float(data['first_samp']) / data['info']['sfreq'],
               float(data['last_samp']) / data['info']['sfreq'])
    print 'Ready.\n'

    return data


def read_raw_segment(raw, from_=None, to=None, sel=None):
    """
    %
    % [data,times] = fiff_read_raw_segment(raw,from_,to,sel)
    %
    % Read a specific raw data segment
    %
    % raw    - structure returned by fiff_setup_read_raw
    % from_   - first sample to include. If omitted, defaults to the
    %          first sample in data
    % to     - last sample to include. If omitted, defaults to the last
    %          sample in data
    % sel    - optional channel selection vector
    %
    % data   - returns the data matrix (channels x samples)
    % times  - returns the time values corresponding to the samples (optional)
    %
    """

    if to is None:
       to  = raw['last_samp']
    if from_ is None:
       from_ = raw['first_samp']

    #  Initial checks
    from_ = float(from_)
    to   = float(to)
    if from_ < raw['first_samp']:
       from_ = raw['first_samp']

    if to > raw['last_samp']:
       to = raw['last_samp']

    if from_ > to:
       raise ValueError, 'No data in this range'

    print 'Reading %d ... %d  =  %9.3f ... %9.3f secs...' % (
                       from_, to, from_/raw['info']['sfreq'], to/raw['info']['sfreq'])
    
    #  Initialize the data and calibration vector
    nchan = raw['info']['nchan']
    dest = 1
    cal = np.diag(raw['cals'].ravel())

    if sel is None:
       data = np.zeros((nchan, to - from_ + 1))
       if raw['proj'] is None and raw['comp'] is None:
          mult = None
       else:
          if raw['proj'] is None:
             mult = raw['comp'] * cal
          elif raw['comp'] is None:
             mult = raw['proj'] * cal
          else:
             mult = raw['proj'] * raw['comp'] * cal

    else:
       data = np.zeros((len(sel), to - from_ + 1))
       if raw['proj'] is None and raw['comp'] is None:
          mult = None
          cal = np.diag(raw['cals'][sel].ravel())
       else:
          if raw['proj'] is None:
             mult = raw['comp'][sel,:] * cal
          elif raw['comp'] is None:
             mult = raw['proj'][sel,:]*cal
          else:
             mult = raw['proj'][sel,:] * raw['comp'] * cal

    do_debug = False
    if cal is not None:
        from scipy import sparse
        cal = sparse.csr_matrix(cal)

    if mult is not None:
        from scipy import sparse
        mult = sparse.csr_matrix(sparse(mult))

    for k in range(len(raw['rawdir'])):
        this = raw['rawdir'][k]

        #  Do we need this buffer
        if this['last'] > from_:
            if this['ent'] is None:
                #  Take the easy route: skip is translated to zeros
                if do_debug:
                    print 'S'
                if sel is None:
                    one = np.zeros((nchan, this['nsamp']))
                else:
                    one = np.zeros((len(sel), this['nsamp']))
            else:
                tag = read_tag(raw['fid'], this['ent'].pos)

                #   Depending on the state of the projection and selection
                #   we proceed a little bit differently
                if mult is None:
                    if sel is None:
                        one = cal * tag.data.reshape(nchan, this['nsamp']).astype(np.float)
                    else:
                        one = tag.data.reshape(nchan, this['nsamp']).astype(np.float)
                        one = cal * one[sel,:]
                else:
                    one = mult * tag.data.reshape(tag.data,nchan,this['nsamp']).astype(np.float)

            #  The picking logic is a bit complicated
            if to >= this['last'] and from_ <= this['first']:
                #    We need the whole buffer
                first_pick = 0
                last_pick  = this['nsamp']
                if do_debug:
                    print 'W'

            elif from_ > this['first']:
                first_pick = from_ - this['first'] + 1
                if to < this['last']:
                    #   Something from the middle
                    last_pick = this['nsamp'] + to - this['last']
                    if do_debug:
                        print 'M'

                else:
                    #   From the middle to the end
                    last_pick = this['nsamp']
                    if do_debug:
                        print 'E'
            else:
                #    From the beginning to the middle
                first_pick = 1
                last_pick = to - this['first'] + 1
                if do_debug:
                    print 'B'
        
        #   Now we are ready to pick
        picksamp = last_pick - first_pick + 1
        if picksamp > 0:
             data[:, dest:dest+picksamp-1] = one[:, first_pick:last_pick]
             dest += picksamp

       #   Done?
        if this['last'] >= to:
            print ' [done]\n'
            break

    times = np.range(from_, to) / raw['info']['sfreq']

    return data, times
