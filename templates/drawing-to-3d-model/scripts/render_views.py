"""
Renders a STEP model as six views in one PNG, so the run can compare it with
the drawing: front (looking along +Y), top (looking down -Z), right (looking
along -X), an isometric, and two half sections (the model cut at its centre
plane, Y and X), like a drawing's section A-A. Views are orthographic and
shaded, with the model's edges drawn dark so holes, grooves and steps show,
and the model's size in the title. Every artifact check_model.py lists
(slivers, thin faces, near steps, thin walls) is ringed in red, so it can be
found on the picture.

    python3 render_views.py model.step views.png [--title "Part 123"] [--section-y 0] [--section-x 116.7]

By default the two sections cut at the model's centre; --section-y and
--section-x put them where a drawing's section line is (B-B off centre, for
example). For a cut along Z or an exact outline with a mm grid, use
measure.py section.
"""
import argparse
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection  # noqa: E402
from OCP.BRepAdaptor import BRepAdaptor_Curve  # noqa: E402
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common  # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox  # noqa: E402
from OCP.gp import gp_Pnt  # noqa: E402
from OCP.TopAbs import TopAbs_EDGE  # noqa: E402
from OCP.BRep import BRep_Tool  # noqa: E402
from OCP.BRepMesh import BRepMesh_IncrementalMesh  # noqa: E402
from OCP.IFSelect import IFSelect_RetDone  # noqa: E402
from OCP.STEPControl import STEPControl_Reader  # noqa: E402
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402
from OCP.TopLoc import TopLoc_Location  # noqa: E402
from OCP.TopoDS import TopoDS  # noqa: E402

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from check_model import artifact_points, artifacts  # noqa: E402


def load(path: str):
    r = STEPControl_Reader()
    if r.ReadFile(path) != IFSelect_RetDone:
        sys.exit(f"could not read {path}")
    r.TransferRoots()
    return r.OneShape()


def edges(shape) -> list:
    out = []
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    while ex.More():
        c = BRepAdaptor_Curve(TopoDS.Edge_s(ex.Current()))
        a, b = c.FirstParameter(), c.LastParameter()
        pts = [c.Value(a + (b - a) * k / 24) for k in range(25)]
        xyz = np.array([[p.X(), p.Y(), p.Z()] for p in pts])
        out.extend(np.stack([xyz[:-1], xyz[1:]], axis=1))
        ex.Next()
    return out


def half(shape, axis: int, lo, hi, at=None):
    """The part of the shape beyond the plane `axis` = at (default: its centre) (0 = X, 1 = Y)."""
    a, b = list(lo - 1), list(hi + 1)
    a[axis] = (lo[axis] + hi[axis]) / 2 if at is None else at
    keep = BRepPrimAPI_MakeBox(gp_Pnt(*a), gp_Pnt(*b)).Shape()
    op = BRepAlgoAPI_Common(shape, keep)
    op.Build()
    return op.Shape() if op.IsDone() else None


def triangles(shape) -> np.ndarray:
    BRepMesh_IncrementalMesh(shape, 0.05, False, 0.25, True)
    tris = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        face = TopoDS.Face_s(ex.Current())
        loc = TopLoc_Location()
        mesh = BRep_Tool.Triangulation_s(face, loc)
        if mesh is not None:
            t = loc.Transformation()
            pts = [mesh.Node(i).Transformed(t) for i in range(1, mesh.NbNodes() + 1)]
            pts = np.array([[p.X(), p.Y(), p.Z()] for p in pts])
            rev = face.Orientation() == TopAbs_REVERSED
            for i in range(1, mesh.NbTriangles() + 1):
                a, b, c = mesh.Triangle(i).Get()
                tri = [pts[a - 1], pts[c - 1], pts[b - 1]] if rev else [pts[a - 1], pts[b - 1], pts[c - 1]]
                tris.append(tri)
        ex.Next()
    return np.array(tris)


def shade(tris: np.ndarray, light) -> np.ndarray:
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    k = np.clip(np.abs(n @ (np.array(light) / np.linalg.norm(light))), 0, 1)
    g = 0.35 + 0.55 * k
    return np.stack([g * 0.75, g * 0.8, g * 0.9, np.ones_like(g)], axis=1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step")
    ap.add_argument("png")
    ap.add_argument("--title", default="")
    ap.add_argument("--section-y", type=float, help="Y of the first section (default: the centre)")
    ap.add_argument("--section-x", type=float, help="X of the second section (default: the centre)")
    a = ap.parse_args()
    shape = load(a.step)
    tris = triangles(shape)
    if len(tris) == 0:
        sys.exit("the model has no faces to draw")
    lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    size = hi - lo
    centre, span = (lo + hi) / 2, size.max() / 2 * 1.08
    whole = (tris, edges(shape))
    marks = np.array(artifact_points(artifacts(shape))).reshape(-1, 3)
    sections = []
    cuts = {1: a.section_y, 0: a.section_x}
    for axis in (1, 0):
        h = half(shape, axis, lo, hi, cuts[axis])
        sections.append((triangles(h), edges(h)) if h is not None else (np.zeros((0, 3, 3)), []))
    # (title, (triangles, edges), elevation, azimuth, light direction)
    views = [
        ("Front (looking +Y)", whole, 0, -90, (0.3, -1, 0.4)),
        ("Top (looking down)", whole, 90, -90, (0.3, -0.3, 1)),
        ("Right (looking -X)", whole, 0, 0, (1, -0.3, 0.4)),
        ("Isometric", whole, 30, -60, (0.6, -0.8, 0.9)),
        (f"Section at Y = {'centre' if a.section_y is None else a.section_y} (looking +Y)", sections[0], 0, -90, (0.3, -1, 0.4)),
        (f"Section at X = {'centre' if a.section_x is None else a.section_x} (looking +X)", sections[1], 0, 180, (-1, 0.3, 0.4)),
    ]
    fig = plt.figure(figsize=(15, 10), dpi=100)
    for i, (name, (t, e), elev, azim, light) in enumerate(views, 1):
        ax = fig.add_subplot(2, 3, i, projection="3d")
        if len(t):
            ax.add_collection3d(Poly3DCollection(t, facecolors=shade(t, light), edgecolors="none"))
        if e:
            ax.add_collection3d(Line3DCollection(e, colors="#1d2733", linewidths=0.6))
        if len(marks):
            # Drawn last and on top, even where the model would hide them.
            ax.computed_zorder = False
            ax.scatter(marks[:, 0], marks[:, 1], marks[:, 2], s=140, facecolors="none", edgecolors="#e5383b", linewidths=1.8, depthshade=False, zorder=10)
        for set_lim, c in zip((ax.set_xlim, ax.set_ylim, ax.set_zlim), centre):
            set_lim(c - span, c + span)
        ax.set_box_aspect((1, 1, 1))
        ax.set_proj_type("ortho")
        ax.view_init(elev=elev, azim=azim)
        ax.set_title(name, fontsize=11)
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")
        ax.tick_params(labelsize=7)
    note = f"   {len(marks)} artifact(s) ringed in red" if len(marks) else ""
    fig.suptitle(f"{a.title}  size X {size[0]:.2f} x Y {size[1]:.2f} x Z {size[2]:.2f} mm{note}", fontsize=13)
    fig.tight_layout()
    fig.savefig(a.png)
    print(f"wrote {a.png}: size {size[0]:.3f} x {size[1]:.3f} x {size[2]:.3f} mm")


if __name__ == "__main__":
    main()
