# -*- coding: utf-8 -*-

from abc import abstractproperty
import itertools as it

import numpy as np
import sympy as sy

from pyfr.bases.base import BaseBasis
from pyfr.quadrules import get_quadrule
from pyfr.syutil import lagrange_basis
from pyfr.util import ndrange, lazyprop


def nodal_basis(points, dims, compact=True):
    p = list(points)

    # Evaluate the basis function in terms of each dimension
    basis = [lagrange_basis(p, d) for d in reversed(dims)]

    # Take the cartesian product of these and multiply the resulting tuples
    cpbasis = np.array([np.prod(b) for b in it.product(*basis)])

    return cpbasis if compact else cpbasis.reshape((len(p),)*len(dims))


_quad_map_rots_np = np.array([[[ 1,  0], [ 0,  1]],
                              [[ 0,  1], [-1,  0]],
                              [[-1,  0], [ 0, -1]],
                              [[ 0, -1], [ 1,  0]]])


def quad_map_edge(fpts):
    mfpts = np.empty((4,) + fpts.shape, dtype=fpts.dtype)

    for i, frot in enumerate(_quad_map_rots_np):
        mfpts[i,...] = np.dot(fpts, frot)

    return mfpts


# Cube map face rotation scheme to go from face 1 -> 0..5
_cube_map_rots = np.array([
    [[-1,  0,  0], [ 0,  0,  1], [ 0,  1,  0]],   # 1 -> 0
    [[ 1,  0,  0], [ 0,  1,  0], [ 0,  0,  1]],   # 1 -> 1 (ident)
    [[ 0,  1,  0], [-1,  0,  0], [ 0,  0,  1]],   # 1 -> 2
    [[-1,  0,  0], [ 0, -1,  0], [ 0,  0,  1]],   # 1 -> 3
    [[ 0, -1,  0], [ 1,  0,  0], [ 0,  0,  1]],   # 1 -> 4
    [[ 1,  0,  0], [ 0,  0, -1], [ 0,  1,  0]]])  # 1 -> 5


def quad_map_face(fpts):
    """Given a matrix of points (p,q,r) corresponding to face one of
    `the cube' this method maps these points onto the remaining faces

    On a cube parameterized by (p,q,r) -> (-1,-1,-1) × (1,1,1) face one
    is defined by (-1,-1,-1) × (1,-1,1)."""
    mfpts = np.empty((6,) + fpts.shape, dtype=fpts.dtype)

    for i, frot in enumerate(_cube_map_rots):
        mfpts[i,...] = np.dot(fpts, frot)

    return mfpts


class TensorProdBasis(object):
    # List of face numbers paired according to their normal dimension
    # e.g, [(a, b), ...] where a, b are the faces whose normal points
    # in -p and p, respectively
    _fpairs = None

    # List of opposite face numbers
    _flipb = None

    def __init__(self, *args, **kwargs):
        super(TensorProdBasis, self).__init__(*args, **kwargs)

        if self.nspts:
            # Root the number of shape points to get the # in each dim
            self._nsptsord = sy.S(self.nspts)**(sy.S(1)/self.ndims)

            if not self._nsptsord.is_Number:
                raise ValueError('Invalid number of shape points for {} dims'
                                 .format(self.ndims))

    @classmethod
    def std_ele(cls, sptord):
        n = (sptord + 1)**cls.ndims
        return get_quadrule(cls.name, 'equi-spaced', n).points

    @lazyprop
    def _pts1d(self):
        rule = self._cfg.get('solver-elements-' + self.name, 'soln-pts')
        return get_quadrule('line', rule, self._order + 1).points

    def _vcjh_fn(self, sym):
        k = self._order
        eta = self._cfg.get('solver-elements-' + self.name, 'vcjh-eta')

        # Expand shorthand forms of eta for common schemes
        etacommon = dict(dg='0', sd='k/(k+1)', hu='(k+1)/k')
        eta_k = sy.S(etacommon.get(eta, eta), locals=dict(k=k))

        lkm1, lk, lkp1 = [sy.legendre_poly(m, sym) for m in [k - 1, k, k + 1]]
        return (sy.S(1)/2 * (lk + (eta_k*lkm1 + lkp1)/(1 + eta_k)))

    @lazyprop
    def upts(self):
        rule = self._cfg.get('solver-elements-' + self.name, 'soln-pts')
        return get_quadrule(self.name, rule, self.nupts).points

    @lazyprop
    def ubasis(self):
        return nodal_basis(self._pts1d, self._dims)

    @lazyprop
    def fbasis(self):
        # Get the 1D points
        pts1d = self._pts1d

        # Dummy symbol
        _x = sy.Symbol('_x')

        # Get the derivative of the 1D correction function
        diffg = self._vcjh_fn(_x).diff()

        # Allocate space for the flux points basis
        fbasis = np.empty([2*self.ndims] + [len(pts1d)]*(self.ndims - 1),
                          dtype=np.object)

        # Pair up opposite faces with their associated (normal) dimension
        for (fl, fr), sym in zip(self._fpairs, self._dims):
            nbdims = [d for d in self._dims if d is not sym]
            fbasis[(fl, fr),...] = nodal_basis(pts1d, nbdims, compact=False)

            fbasis[fl,...] *= diffg.subs(_x, -sym)
            fbasis[fr,...] *= diffg.subs(_x, sym)

        # Some faces have flux points that count backwards; for
        # these faces we must reverse the basis
        fbasis[self._flipb] = fbasis[self._flipb,...,::-1]

        return fbasis.ravel()

    @property
    def facefpts(self):
        kn = (self._order + 1)**(self.ndims - 1)
        return [list(xrange(i*kn, (i + 1)*kn)) for i in xrange(2*self.ndims)]

    @lazyprop
    def spts(self):
        return self.std_ele(self._nsptsord - 1)

    @lazyprop
    def sbasis(self):
        pts1d = get_quadrule('line', 'equi-spaced', self._nsptsord).points
        return nodal_basis(pts1d, self._dims)

    @property
    def nupts(self):
        return (self._order + 1)**self.ndims


class QuadBasis(TensorProdBasis, BaseBasis):
    name = 'quad'
    ndims = 2

    _fpairs = [(3, 1), (0, 2)]
    _flipb = [2, 3]

    @lazyprop
    def fpts(self):
        # Get the 1D points
        pts1d = self._pts1d

        # Edge zero has points (q,-1)
        ezeropts = np.empty((len(pts1d), 2), dtype=np.object)
        ezeropts[:,0] = pts1d
        ezeropts[:,1] = -1

        # Quad map edge zero to get the full set
        return quad_map_edge(ezeropts).reshape(-1, 2)

    @lazyprop
    def norm_fpts(self):
        # Normals for edge zero are (0,-1)
        ezeronorms = np.zeros((self._order + 1, 2), dtype=np.int)
        ezeronorms[:,1] = -1

        # Edge map
        return quad_map_edge(ezeronorms).reshape(-1, 2)


class HexBasis(TensorProdBasis, BaseBasis):
    name = 'hex'
    ndims = 3

    _fpairs = [(4, 2), (1, 3), (0, 5)]
    _flipb = [0, 3, 4]

    @lazyprop
    def fpts(self):
        # Flux points for a single face
        rule = self._cfg.get('solver-elements-hex', 'soln-pts')
        pts2d = get_quadrule('quad', rule, self.nfpts // 6).points

        # 3D points are just (p,-1,r) for face one
        fonepts = np.empty((len(pts2d), 3), dtype=np.object)
        fonepts[...,(0,2)] = pts2d
        fonepts[...,1] = -1

        # Cube map face one to get faces zero through five
        return quad_map_face(fonepts).reshape(-1, 3)

    @lazyprop
    def norm_fpts(self):
        # Normals for face one are (0,-1,0)
        fonenorms = np.zeros([self._order + 1]*2 + [3], dtype=np.int)
        fonenorms[...,1] = -1

        # Cube map to get the remaining face normals
        return quad_map_face(fonenorms).reshape(-1, 3)
