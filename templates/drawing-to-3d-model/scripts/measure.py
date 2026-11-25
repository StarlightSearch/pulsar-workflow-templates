"""
Measures a STEP model so a check row states a measured value, never a guess.
All values are mm (and degrees). Prints JSON, or writes a PNG for `section`.

    python3 measure.py model.step line  --along y --x 116.69 --z 100
        Material along a line: every stretch where the line is inside the
        solid, as [start, end, length]. The line runs along one axis through
        the two given coordinates. Use it for widths, wall and flange
        thicknesses, bore sizes and step positions.

    python3 measure.py model.step planes [--axis z] [--min-area 1]
        Every flat face: its normal, its position along that normal, its
        area, and its tilt from the nearest axis. Use it for heights and
        lengths between faces, and for draft (a 2° draft face shows tilt 2.0).

    python3 measure.py model.step section --axis x --at 116.69 [--png s.png]
        The model cut by a plane (here X = 116.69): the cut outline's size,
        and with --png a drawing of it with a mm grid, to lay next to a
        section on the drawing (A-A, B-B at any position).

    python3 measure.py model.step distance --from x=0 --to x=233.375
        The gap between two planes, mm. A convenience for check rows.
"""
import argparse
import json
import math
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface  # noqa: E402
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section  # noqa: E402
from OCP.BRepClass3d import BRepClass3d_SolidClassifier  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GeomAbs import GeomAbs_Plane  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.IFSelect import IFSelect_RetDone  # noqa: E402
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector  # noqa: E402
from OCP.STEPControl import STEPControl_Reader  # noqa: E402
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_REVERSED  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402
from OCP.TopoDS import TopoDS  # noqa: E402
from OCP.gp import gp_Dir, gp_Lin, gp_Pln, gp_Pnt  # noqa: E402

AXES = {"x": 0, "y": 1, "z": 2}
r3 = lambda v: round(v, 3)  # noqa: E731


def load(path: str):
    r = STEPControl_Reader()
    if r.ReadFile(path) != IFSelect_RetDone:
        sys.exit(f"could not read {path}")
    r.TransferRoots()
    return r.OneShape()


def line(shape, along: str, coords: dict) -> dict:
    i = AXES[along]
    p = [0.0, 0.0, 0.0]
    for k, v in coords.items():
        p[AXES[k]] = v
    d = [0.0, 0.0, 0.0]
    d[i] = 1.0
    lin = gp_Lin(gp_Pnt(*p), gp_Dir(*d))
    hits = IntCurvesFace_ShapeIntersector()
    hits.Load(shape, 1e-6)
    hits.Perform(lin, -1e6, 1e6)
    ts = sorted({round(hits.WParameter(k), 6) for k in range(1, hits.NbPnt() + 1)})
    inside = BRepClass3d_SolidClassifier(shape)
    spans = []
    for a, b in zip(ts, ts[1:]):
        m = (a + b) / 2
        q = list(p)
        q[i] = p[i] + m
        inside.Perform(gp_Pnt(*q), 1e-6)
        if inside.State() == TopAbs_IN:
            if spans and abs(spans[-1][1] - (p[i] + a)) < 1e-6:
                spans[-1][1] = p[i] + b  # touching stretches are one
            else:
                spans.append([p[i] + a, p[i] + b])
    return {
        "line": f"along {along} at " + ", ".join(f"{k}={v}" for k, v in coords.items()),
        "material": [[r3(a), r3(b), r3(b - a)] for a, b in spans],
        "total": r3(sum(b - a for a, b in spans)),
    }


def planes(shape, axis: str | None, min_area: float) -> list:
    out = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current())
        s = BRepAdaptor_Surface(f)
        if s.GetType() == GeomAbs_Plane:
            pl = s.Plane()
            n = pl.Axis().Direction()
            if f.Orientation() == TopAbs_REVERSED:
                n = n.Reversed()
            v = (n.X(), n.Y(), n.Z())
            k = max(range(3), key=lambda j: abs(v[j]))
            tilt = math.degrees(math.acos(min(1.0, abs(v[k]))))
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(f, props)
            area = props.Mass()
            loc = pl.Location()
            offset = loc.X() * v[0] + loc.Y() * v[1] + loc.Z() * v[2]
            name = "xyz"[k]
            if area >= min_area and (axis is None or axis == name):
                out.append({
                    "nearest_axis": ("+" if v[k] > 0 else "-") + name,
                    "tilt_deg": round(tilt, 2),
                    "position": r3(offset * (1 if v[k] > 0 else -1)) if tilt < 1e-6 else None,
                    "normal": [round(c, 4) for c in v],
                    "area_mm2": round(area, 1),
                })
        ex.Next()
    out.sort(key=lambda r: (r["nearest_axis"][-1], r["position"] if r["position"] is not None else 1e9, -r["area_mm2"]))
    return out


def section(shape, axis: str, at: float, png: str | None) -> dict:
    n = [0.0, 0.0, 0.0]
    n[AXES[axis]] = 1.0
    o = [0.0, 0.0, 0.0]
    o[AXES[axis]] = at
    cut = BRepAlgoAPI_Section(shape, gp_Pln(gp_Pnt(*o), gp_Dir(*n)))
    cut.Build()
    if not cut.IsDone():
        sys.exit("section failed")
    u, v = [j for j in range(3) if j != AXES[axis]]
    segs = []
    ex = TopExp_Explorer(cut.Shape(), TopAbs_EDGE)
    while ex.More():
        c = BRepAdaptor_Curve(TopoDS.Edge_s(ex.Current()))
        a, b = c.FirstParameter(), c.LastParameter()
        pts = []
        for k in range(33):
            p = c.Value(a + (b - a) * k / 32)
            xyz = (p.X(), p.Y(), p.Z())
            pts.append((xyz[u], xyz[v]))
        segs.append(pts)
        ex.Next()
    if not segs:
        return {"section": f"{axis}={at}", "empty": True}
    us = [p[0] for s in segs for p in s]
    vs = [p[1] for s in segs for p in s]
    res = {
        "section": f"{axis}={at}",
        "plot_axes": ["xyz"[u], "xyz"[v]],
        "min": [r3(min(us)), r3(min(vs))],
        "max": [r3(max(us)), r3(max(vs))],
        "size": [r3(max(us) - min(us)), r3(max(vs) - min(vs))],
        "edges": len(segs),
    }
    if png:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 8), dpi=110)
        for s in segs:
            ax.plot([p[0] for p in s], [p[1] for p in s], color="#1d2733", linewidth=1)
        ax.set_aspect("equal")
        ax.grid(True, linewidth=0.4)
        ax.minorticks_on()
        ax.grid(True, which="minor", linewidth=0.15)
        ax.set_xlabel(f"{'xyz'[u].upper()} (mm)")
        ax.set_ylabel(f"{'xyz'[v].upper()} (mm)")
        ax.set_title(f"Section at {axis.upper()} = {at} mm   size {res['size'][0]} x {res['size'][1]} mm")
        fig.tight_layout()
        fig.savefig(png)
        res["png"] = png
    return res


def plane_arg(s: str):
    k, v = s.split("=")
    return k.strip().lower(), float(v)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("line")
    pl.add_argument("--along", required=True, choices=list(AXES))
    for k in AXES:
        pl.add_argument(f"--{k}", type=float)
    pp = sub.add_parser("planes")
    pp.add_argument("--axis", choices=list(AXES))
    pp.add_argument("--min-area", type=float, default=1.0)
    ps = sub.add_parser("section")
    ps.add_argument("--axis", required=True, choices=list(AXES))
    ps.add_argument("--at", required=True, type=float)
    ps.add_argument("--png")
    pd = sub.add_parser("distance")
    pd.add_argument("--from", dest="a", required=True, type=plane_arg)
    pd.add_argument("--to", dest="b", required=True, type=plane_arg)
    a = ap.parse_args()

    if a.cmd == "distance":
        if a.a[0] != a.b[0]:
            sys.exit("both planes must be on the same axis")
        print(json.dumps({"axis": a.a[0], "distance": r3(abs(a.b[1] - a.a[1]))}))
        return
    shape = load(a.step)
    if a.cmd == "line":
        coords = {k: getattr(a, k) for k in AXES if k != a.along and getattr(a, k) is not None}
        if len(coords) != 2:
            sys.exit(f"give the two coordinates other than {a.along}")
        print(json.dumps(line(shape, a.along, coords), indent=2))
    elif a.cmd == "planes":
        print(json.dumps(planes(shape, a.axis, a.min_area), indent=2))
    else:
        print(json.dumps(section(shape, a.axis, a.at, a.png), indent=2))


if __name__ == "__main__":
    main()
