"""
cadkit: a small modelling layer over Open CASCADE (OCP) for drawing-to-STEP work.

Import it from a model script:

    import sys; sys.path.insert(0, "/workspace/workflow/scripts")
    from cadkit import *

All lengths are millimetres. Axes: X right, Y back, Z up (the drawing's front
view looks along +Y, the top view looks down -Z). Every function returns a new
shape; nothing is modified in place.

Primitives
    box(x, y, z, at=(0,0,0), center=False)       axis-aligned block
    cylinder(d, h, at=(0,0,0), axis="z")          solid cylinder, base at `at`
    tube(od, id, h, at=(0,0,0), axis="z")          hollow cylinder
    cone(d1, d2, h, at=(0,0,0), axis="z")          frustum (d2 may be 0)
    sphere(d, at=(0,0,0))
    extrude(points, h, plane="xy", at=0.0)        closed 2D polygon -> prism
    extrude_profile(profile, h, plane="xy", at=0.0)  profile made with Profile()
    revolve(points, axis="z", angle=360)          (r, z) polygon around an axis -> turned part

Profiles with arcs (for slots, rounded plates, keyholes):
    p = Profile(0, 0); p.line_to(40, 0); p.arc_to(50, 10, (40, 10)); ... p.close()
    slot(length, width, at=(0,0), angle=0) -> Profile of an obround slot
    rounded_rect(w, h, r, at=(0,0)) -> Profile of a rectangle with corner radius r

Booleans and placement
    fuse(a, b, ...)      cut(a, b, ...)      common(a, b)
    move(shape, dx, dy, dz)       rotate(shape, deg, axis="z", about=(0,0,0))
    mirror(shape, plane="yz")     pattern_linear(shape, n, dx, dy=0, dz=0)
    pattern_polar(shape, n, axis="z", about=(0,0,0), start_deg=0)

Features
    hole(shape, d, x, y, depth=None, z_top=None, axis="z")   drilled hole down from z_top (default: the top of `shape`)
    drill(shape, d, start, direction, length)    hole of diameter d from point `start` along any direction (angled or cross holes)
    rod(d, p1, p2)                                 solid cylinder between two points (to cut or fuse)
    counterbore(shape, d, cb_d, cb_depth, x, y, depth=None, z_top=None)
    countersink(shape, d, cs_d, x, y, angle=90, depth=None, z_top=None)
    fillet(shape, r, edges=None)    chamfer(shape, d, edges=None)
    edges_where(shape, test)        edges whose midpoint (x, y, z) passes test(x, y, z)
    vertical_edges(shape)           edges parallel to Z (plate corners)

Output and checks
    save_step(shape, path)          merges same-surface faces (clean), then writes STEP (AP214, mm); raises if the shape is not valid
    clean(shape)                    merges the seam faces booleans leave on one surface
    save_stl(shape, path, tol=0.05)
    info(shape) -> dict             valid, solids, volume, area, bbox (min, max, size), hole diameters
"""
from __future__ import annotations

import contextlib
import math
import os
from typing import Callable, Iterable, Sequence

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_Transform,
)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import (
    BRepPrimAPI_MakeBox,
    BRepPrimAPI_MakeCone,
    BRepPrimAPI_MakeCylinder,
    BRepPrimAPI_MakePrism,
    BRepPrimAPI_MakeRevol,
    BRepPrimAPI_MakeSphere,
)
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.Bnd import Bnd_Box
from OCP.GC import GC_MakeArcOfCircle
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Line
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.StlAPI import StlAPI_Writer
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopTools import TopTools_ListOfShape
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

__all__ = [
    "box", "cylinder", "tube", "cone", "sphere", "extrude", "extrude_profile", "revolve",
    "Profile", "slot", "rounded_rect",
    "fuse", "cut", "common", "move", "rotate", "mirror", "pattern_linear", "pattern_polar",
    "hole", "drill", "rod", "counterbore", "countersink", "fillet", "chamfer", "edges_where", "vertical_edges",
    "save_step", "save_stl", "info", "clean",
]

_AXES = {"x": gp_Dir(1, 0, 0), "y": gp_Dir(0, 1, 0), "z": gp_Dir(0, 0, 1)}


def _dir(axis) -> gp_Dir:
    if isinstance(axis, str):
        return _AXES[axis.lower()]
    return gp_Dir(*axis)


def _ax2(at, axis) -> gp_Ax2:
    return gp_Ax2(gp_Pnt(*at), _dir(axis))


def _done(maker, what: str) -> TopoDS_Shape:
    maker.Build()
    if not maker.IsDone():
        raise RuntimeError(f"{what} failed")
    return maker.Shape()


# ---------------------------------------------------------------- primitives

def box(x: float, y: float, z: float, at=(0.0, 0.0, 0.0), center: bool = False) -> TopoDS_Shape:
    ox, oy, oz = at
    if center:
        ox, oy, oz = ox - x / 2, oy - y / 2, oz - z / 2
    return _done(BRepPrimAPI_MakeBox(gp_Pnt(ox, oy, oz), x, y, z), "box")


def cylinder(d: float, h: float, at=(0.0, 0.0, 0.0), axis="z") -> TopoDS_Shape:
    return _done(BRepPrimAPI_MakeCylinder(_ax2(at, axis), d / 2, h), "cylinder")


def tube(od: float, id: float, h: float, at=(0.0, 0.0, 0.0), axis="z") -> TopoDS_Shape:
    return cut(cylinder(od, h, at, axis), cylinder(id, h, at, axis))


def cone(d1: float, d2: float, h: float, at=(0.0, 0.0, 0.0), axis="z") -> TopoDS_Shape:
    return _done(BRepPrimAPI_MakeCone(_ax2(at, axis), d1 / 2, d2 / 2, h), "cone")


def sphere(d: float, at=(0.0, 0.0, 0.0)) -> TopoDS_Shape:
    return _done(BRepPrimAPI_MakeSphere(gp_Pnt(*at), d / 2), "sphere")


def _plane_pnt(u: float, v: float, plane: str, at: float) -> gp_Pnt:
    plane = plane.lower()
    if plane == "xy":
        return gp_Pnt(u, v, at)
    if plane == "xz":
        return gp_Pnt(u, at, v)
    if plane == "yz":
        return gp_Pnt(at, u, v)
    raise ValueError("plane must be xy, xz or yz")


def _normal(plane: str) -> gp_Vec:
    return {"xy": gp_Vec(0, 0, 1), "xz": gp_Vec(0, 1, 0), "yz": gp_Vec(1, 0, 0)}[plane.lower()]


def extrude(points: Sequence[Sequence[float]], h: float, plane: str = "xy", at: float = 0.0) -> TopoDS_Shape:
    """A closed polygon (list of (u, v)) on `plane` at offset `at`, extruded `h` along the plane normal."""
    poly = BRepBuilderAPI_MakePolygon()
    for u, v in points:
        poly.Add(_plane_pnt(u, v, plane, at))
    poly.Close()
    face = _done(BRepBuilderAPI_MakeFace(poly.Wire()), "polygon face")
    return _done(BRepPrimAPI_MakePrism(face, _normal(plane).Multiplied(h)), "extrude")


class Profile:
    """A closed 2D outline of lines and arcs: start, then line_to / arc_to, then close()."""

    def __init__(self, u: float, v: float):
        self.start = (u, v)
        self.cur = (u, v)
        self.segs: list = []

    def line_to(self, u: float, v: float) -> "Profile":
        self.segs.append(("line", self.cur, (u, v)))
        self.cur = (u, v)
        return self

    def arc_to(self, u: float, v: float, through: Sequence[float]) -> "Profile":
        """Arc from the current point through `through` to (u, v)."""
        self.segs.append(("arc", self.cur, tuple(through), (u, v)))
        self.cur = (u, v)
        return self

    def close(self) -> "Profile":
        if math.dist(self.cur, self.start) > 1e-9:
            self.line_to(*self.start)
        return self

    def face(self, plane: str = "xy", at: float = 0.0):
        wire = BRepBuilderAPI_MakeWire()
        for s in self.segs:
            if s[0] == "line":
                a, b = s[1], s[2]
                if math.dist(a, b) < 1e-9:
                    continue
                e = BRepBuilderAPI_MakeEdge(_plane_pnt(*a, plane, at), _plane_pnt(*b, plane, at)).Edge()
            else:
                a, m, b = s[1], s[2], s[3]
                arc = GC_MakeArcOfCircle(_plane_pnt(*a, plane, at), _plane_pnt(*m, plane, at), _plane_pnt(*b, plane, at)).Value()
                e = BRepBuilderAPI_MakeEdge(arc).Edge()
            wire.Add(e)
        if not wire.IsDone():
            raise RuntimeError("profile wire failed: check the points join up")
        return _done(BRepBuilderAPI_MakeFace(wire.Wire()), "profile face")


def slot(length: float, width: float, at=(0.0, 0.0), angle: float = 0.0) -> Profile:
    """An obround slot `length` overall (end to end) and `width` wide, centred at `at`."""
    r = width / 2
    half = length / 2 - r
    cx, cy = at
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    t = lambda u, v: (cx + u * c - v * s, cy + u * s + v * c)  # noqa: E731
    p = Profile(*t(-half, -r))
    p.line_to(*t(half, -r)).arc_to(*t(half, r), t(half + r, 0))
    p.line_to(*t(-half, r)).arc_to(*t(-half, -r), t(-half - r, 0))
    return p.close()


def rounded_rect(w: float, h: float, r: float, at=(0.0, 0.0)) -> Profile:
    """A w x h rectangle centred at `at` with corner radius r."""
    cx, cy = at
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    k = r * (1 - math.sqrt(0.5))
    p = Profile(x0 + r, y0)
    p.line_to(x1 - r, y0).arc_to(x1, y0 + r, (x1 - k, y0 + k))
    p.line_to(x1, y1 - r).arc_to(x1 - r, y1, (x1 - k, y1 - k))
    p.line_to(x0 + r, y1).arc_to(x0, y1 - r, (x0 + k, y1 - k))
    p.line_to(x0, y0 + r).arc_to(x0 + r, y0, (x0 + k, y0 + k))
    return p.close()


def extrude_profile(profile: Profile, h: float, plane: str = "xy", at: float = 0.0) -> TopoDS_Shape:
    return _done(BRepPrimAPI_MakePrism(profile.face(plane, at), _normal(plane).Multiplied(h)), "extrude")


def revolve(points: Sequence[Sequence[float]], axis: str = "z", angle: float = 360.0) -> TopoDS_Shape:
    """A closed (r, a) polygon revolved about `axis`: r is the radius, a the position along the axis.

    Use it for shafts, pins, bushings and flanges: list the outline of the half
    section (radius >= 0), e.g. [(0,0), (10,0), (10,30), (6,30), (6,45), (0,45)].
    """
    axis = axis.lower()
    def p(r, a):
        return {"z": gp_Pnt(r, 0, a), "x": gp_Pnt(a, r, 0), "y": gp_Pnt(0, a, r)}[axis]
    poly = BRepBuilderAPI_MakePolygon()
    for r, a in points:
        poly.Add(p(r, a))
    poly.Close()
    face = _done(BRepBuilderAPI_MakeFace(poly.Wire()), "revolve face")
    ax = gp_Ax1(gp_Pnt(0, 0, 0), _dir(axis))
    return _done(BRepPrimAPI_MakeRevol(face, ax, math.radians(angle)), "revolve")


# ---------------------------------------------------------------- booleans

# Booleans run with a small fuzzy tolerance: two faces that should coincide but
# differ by rounding (1e-4 mm) are treated as one, instead of leaving a sliver.
FUZZY_MM = 1e-4


def _bool(cls, what, a, others):
    out = a
    for b in others:
        op = cls()
        args, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
        args.Append(out)
        tools.Append(b)
        op.SetArguments(args)
        op.SetTools(tools)
        op.SetFuzzyValue(FUZZY_MM)
        op.Build()
        if not op.IsDone():
            raise RuntimeError(f"{what} failed")
        out = op.Shape()
    return out


def clean(shape):
    """Merges faces and edges that lie on the same surface (the seams booleans leave), keeping the shape valid."""
    u = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
    u.Build()
    out = u.Shape()
    return out if BRepCheck_Analyzer(out).IsValid() else shape


def fuse(a, *others):
    return _bool(BRepAlgoAPI_Fuse, "fuse", a, others)


def cut(a, *others):
    return _bool(BRepAlgoAPI_Cut, "cut", a, others)


def common(a, b):
    return _bool(BRepAlgoAPI_Common, "common", a, [b])


def _transform(shape, trsf: gp_Trsf):
    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()


def move(shape, dx=0.0, dy=0.0, dz=0.0):
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(dx, dy, dz))
    return _transform(shape, t)


def rotate(shape, deg: float, axis="z", about=(0.0, 0.0, 0.0)):
    t = gp_Trsf()
    t.SetRotation(gp_Ax1(gp_Pnt(*about), _dir(axis)), math.radians(deg))
    return _transform(shape, t)


def mirror(shape, plane: str = "yz"):
    """Mirror across a plane through the origin: yz flips X, xz flips Y, xy flips Z."""
    n = {"yz": gp_Dir(1, 0, 0), "xz": gp_Dir(0, 1, 0), "xy": gp_Dir(0, 0, 1)}[plane.lower()]
    t = gp_Trsf()
    t.SetMirror(gp_Ax2(gp_Pnt(0, 0, 0), n))
    return _transform(shape, t)


def pattern_linear(shape, n: int, dx: float, dy: float = 0.0, dz: float = 0.0):
    """n copies stepped by (dx, dy, dz), fused into one shape (the first copy is `shape`)."""
    return fuse(shape, *[move(shape, i * dx, i * dy, i * dz) for i in range(1, n)])


def pattern_polar(shape, n: int, axis="z", about=(0.0, 0.0, 0.0), start_deg: float = 0.0):
    """n copies spaced evenly around `axis` through `about`, fused."""
    first = rotate(shape, start_deg, axis, about) if start_deg else shape
    return fuse(first, *[rotate(shape, start_deg + i * 360.0 / n, axis, about) for i in range(1, n)])


# ---------------------------------------------------------------- features

def _bbox(shape):
    """The tight bounding box (BRepBndLib.Add is loose: it pads curved faces)."""
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, b, True, False)
    return b.Get()


def hole(shape, d: float, x: float, y: float, depth: float | None = None, z_top: float | None = None, axis: str = "z"):
    """A drilled hole of diameter d at (x, y), going down from z_top (default: top of the shape).

    depth None means through. With axis "x" or "y", (x, y) are the other two
    coordinates and the hole goes in from the max side of that axis.
    """
    x0, y0, z0, x1, y1, z1 = _bbox(shape)
    axis = axis.lower()
    if axis == "z":
        top = z1 if z_top is None else z_top
        length = (top - z0 + 1.0) if depth is None else depth
        tool = cylinder(d, length + 0.5, at=(x, y, top - length), axis="z")
    elif axis == "x":
        top = x1 if z_top is None else z_top
        length = (top - x0 + 1.0) if depth is None else depth
        tool = cylinder(d, length + 0.5, at=(top - length, x, y), axis="x")
    else:
        top = y1 if z_top is None else z_top
        length = (top - y0 + 1.0) if depth is None else depth
        tool = cylinder(d, length + 0.5, at=(x, top - length, y), axis="y")
    return cut(shape, tool)


def rod(d: float, p1, p2) -> TopoDS_Shape:
    """A solid cylinder of diameter d from point p1 to point p2."""
    v = gp_Vec(gp_Pnt(*p1), gp_Pnt(*p2))
    if v.Magnitude() < 1e-9:
        raise ValueError("rod needs two different points")
    return _done(BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*p1), gp_Dir(v)), d / 2, v.Magnitude()), "rod")


def drill(shape, d: float, start, direction, length: float):
    """Cut a hole of diameter d starting at `start`, going `length` along `direction` (any angle)."""
    v = gp_Vec(*direction)
    v.Normalize()
    end = (start[0] + v.X() * length, start[1] + v.Y() * length, start[2] + v.Z() * length)
    return cut(shape, rod(d, start, end))


def counterbore(shape, d: float, cb_d: float, cb_depth: float, x: float, y: float, depth: float | None = None, z_top: float | None = None):
    top = _bbox(shape)[5] if z_top is None else z_top
    out = hole(shape, d, x, y, depth, top)
    return cut(out, cylinder(cb_d, cb_depth + 0.5, at=(x, y, top - cb_depth)))


def countersink(shape, d: float, cs_d: float, x: float, y: float, angle: float = 90.0, depth: float | None = None, z_top: float | None = None):
    top = _bbox(shape)[5] if z_top is None else z_top
    out = hole(shape, d, x, y, depth, top)
    h = (cs_d - d) / 2 / math.tan(math.radians(angle / 2))
    return cut(out, cone(d, cs_d, h, at=(x, y, top - h)), cylinder(cs_d, 0.5, at=(x, y, top)))


def _edges(shape):
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    seen, out = set(), []
    while ex.More():
        e = TopoDS.Edge_s(ex.Current())
        h = e.__hash__()
        if h not in seen:
            seen.add(h)
            out.append(e)
        ex.Next()
    return out


def edges_where(shape, test: Callable[[float, float, float], bool]):
    out = []
    for e in _edges(shape):
        c = BRepAdaptor_Curve(e)
        p = c.Value((c.FirstParameter() + c.LastParameter()) / 2)
        if test(p.X(), p.Y(), p.Z()):
            out.append(e)
    return out


def vertical_edges(shape):
    out = []
    for e in _edges(shape):
        c = BRepAdaptor_Curve(e)
        if c.GetType() == GeomAbs_Line:
            d = c.Line().Direction()
            if abs(abs(d.Z()) - 1) < 1e-6:
                out.append(e)
    return out


def fillet(shape, r: float, edges: Iterable | None = None):
    mk = BRepFilletAPI_MakeFillet(shape)
    for e in (edges if edges is not None else _edges(shape)):
        mk.Add(r, e)
    return _done(mk, f"fillet r={r}")


def chamfer(shape, d: float, edges: Iterable | None = None):
    mk = BRepFilletAPI_MakeChamfer(shape)
    for e in (edges if edges is not None else _edges(shape)):
        mk.Add(d, e)
    return _done(mk, f"chamfer {d}")


# ---------------------------------------------------------------- output

def info(shape) -> dict:
    valid = BRepCheck_Analyzer(shape).IsValid()
    solids, volume = 0, 0.0
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        p = GProp_GProps()
        BRepGProp.VolumeProperties_s(ex.Current(), p)
        volume += p.Mass()
        solids += 1
        ex.Next()
    area = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, area)
    x0, y0, z0, x1, y1, z1 = _bbox(shape)
    diameters: dict[float, int] = {}
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        s = BRepAdaptor_Surface(TopoDS.Face_s(ex.Current()))
        if s.GetType() == GeomAbs_Cylinder:
            dia = round(2 * s.Cylinder().Radius(), 3)
            diameters[dia] = diameters.get(dia, 0) + 1
        ex.Next()
    r = lambda v: round(v, 3)  # noqa: E731
    return {
        "valid": valid,
        "solids": solids,
        "volume_mm3": r(volume),
        "area_mm2": r(area.Mass()),
        "bbox_min": [r(x0), r(y0), r(z0)],
        "bbox_max": [r(x1), r(y1), r(z1)],
        "size": [r(x1 - x0), r(y1 - y0), r(z1 - z0)],
        "cylindrical_face_diameters": {str(k): v for k, v in sorted(diameters.items())},
    }


@contextlib.contextmanager
def _quiet():
    """Open CASCADE's STEP writer prints a banner to stdout: keep it out of the run's output."""
    try:
        fd = os.dup(1)
    except OSError:
        yield
        return
    with open(os.devnull, "w") as null:
        os.dup2(null.fileno(), 1)
        try:
            yield
        finally:
            os.dup2(fd, 1)
            os.close(fd)


def save_step(shape, path: str) -> dict:
    shape = clean(shape)
    i = info(shape)
    if not i["valid"] or i["solids"] < 1 or i["volume_mm3"] <= 0:
        raise RuntimeError(f"not saving an invalid model: {i}")
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    with _quiet():
        w = STEPControl_Writer()
        w.Transfer(shape, STEPControl_AsIs)
        status = w.Write(path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"could not write {path}")
    return i


def save_stl(shape, path: str, tol: float = 0.05) -> None:
    BRepMesh_IncrementalMesh(shape, tol, False, 0.3, True)
    w = StlAPI_Writer()
    w.ASCIIMode = False
    if not w.Write(shape, path):
        raise RuntimeError(f"could not write {path}")
