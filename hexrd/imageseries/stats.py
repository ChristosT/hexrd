"""Stats for imageseries

runs in chunks:
if chunks is None, chunks are determined here and all are run
otherwise, chunks is tuple of (i, n, img) where
 i < n is the current chunk to compute,
 n is the total number of chunks,
 and img is the current image
"""


import numpy as np
import logging

from psutil import virtual_memory

from hexrd.imageseries.process import ProcessedImageSeries as PIS

# Default Buffer: half of available memory
vmem = virtual_memory()
STATS_BUFFER = int(0.5*vmem.available)


def max(ims, chunk=None, nframes=0):
    """maximum over frames"""
    nf = _nframes(ims, nframes)
    if chunk is None:
        dt = ims.dtype
        (nr, nc) = ims.shape
        mem = nf*nr*nc*dt.itemsize
        nchunks = 1 + mem // STATS_BUFFER
        img = np.zeros((nr, nc), dtype=dt)
        for i in range(nchunks):
            chunk = (i, nchunks, img)
            img = _chunk_op(np.max, ims, nf, chunk)
    else:
        img = _chunk_op(np.max, ims, nf, chunk)

    return img


def _old_max(ims, nframes=0):
    nf = _nframes(ims, nframes)
    imgmax = ims[0]
    for i in range(1, nf):
        imgmax = np.maximum(imgmax, ims[i])
    return imgmax


def average(ims, nframes=0):
    """return image with average values over all frames"""
    nf = _nframes(ims, nframes)
    avg = np.array(ims[0], dtype=float)
    for i in range(1, nf):
        avg += ims[i]
    return avg/nf


def median(ims, nframes=0, chunk=None):
    """return image with median values over all frames

    chunk -- a tuple: (i, n, img), where i is the current chunk (0-based), n is total number of chunks,
             and img is the current state of the image and will be updated on return

    For example, to use 50 chunks, call 50 times consecutively with (0, 50, img) ... (49, 50, img)
    Each time, a number of rows of the image is updated.
"""
    # use percentile since it has better performance
    if chunk is None:
        return percentile(ims, 50, nframes=nframes)

    nf = _nframes(ims, nframes)
    nrows, ncols = ims.shape
    i = chunk[0]
    nchunk = chunk[1]
    img = chunk[2]
    r0, r1 = _chunk_ranges(nrows, nchunk, i)
    rect = np.array([[r0, r1], [0, ncols]])
    pims = PIS(ims, [('rectangle', rect)])
    img[r0:r1, :] = np.median(_toarray(pims, nf), axis=0)

    return img


def percentile(ims, pct, nframes=0):
    """return image with given percentile values over all frames"""
    # could be done by rectangle by rectangle if full series
    # too  big for memory
    nf = _nframes(ims, nframes)
    dt = ims.dtype
    (nr, nc) = ims.shape
    nrpb  = _rows_in_buffer(nframes, nf*nc*dt.itemsize)

    # now build the result a rectangle at a time
    img = np.zeros_like(ims[0])
    for rr in _row_ranges(nr, nrpb):
        rect = np.array([[rr[0], rr[1]], [0, nc]])
        pims = PIS(ims, [('rectangle', rect)])
        img[rr[0]:rr[1], :] = np.percentile(_toarray(pims, nf), pct, axis=0)
    return img
#
# ==================== Utilities
#
def _nframes(ims, nframes):
    """number of frames to use: len(ims) or specified number"""
    mynf = len(ims)
    return np.min((mynf, nframes)) if nframes > 0 else mynf


def _toarray(ims, nframes):
    ashp = (nframes,) + ims.shape
    a = np.zeros(ashp, dtype=ims.dtype)
    for i in range(nframes):
        logging.info('frame: %s', i)
        a[i] = ims[i]

    return a


def _chunk_ranges(nrows, nchunk, chunk):
    """Return start and end row for current chunk

    nrows -- total number of rows (row indices are 0-based)
    nchunk -- number of chunks
    chunk -- current chunk (0-based, i.e. ranges from 0 to nchunk - 1)
"""
    csize = nrows//nchunk
    rem = nrows % nchunk
    if chunk < rem:
        r0 = (chunk)*(csize + 1)
        r1 = r0 + csize + 1
    else:
        r0 = chunk*csize + rem
        r1 = r0 + csize

    return r0, r1


def _chunk_op(op, ims, nf, chunk, *args):
    """run operation on one chunk of image data
    ims -- the imageseries
    nf -- total number of frames to use
    chunk -- tuple of (i, n, img)
    args -- args to pass to op
"""
    nf = len(ims)
    nrows, ncols = ims.shape
    i = chunk[0]
    nchunk = chunk[1]
    img = chunk[2]
    r0, r1 = _chunk_ranges(nrows, nchunk, i)
    rect = np.array([[r0, r1], [0, ncols]])
    pims = PIS(ims, [('rectangle', rect)])
    a = _toarray(pims, nf)
    img[r0:r1, :] = op(a, *args, axis=0)

    return img


def _row_ranges(n, m):
    """return row ranges, representing m rows or remainder, until exhausted"""
    i = 0
    while i < n:
        imax = i+m
        if imax <= n:
            yield (i, imax)
        else:
            yield (i, n)
        i = imax


def _rows_in_buffer(ncol, rsize):
    """number of rows in buffer

    NOTE: Use ceiling to make sure at it has at least one row"""
    return int(np.ceil(STATS_BUFFER/rsize))
