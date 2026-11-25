"""
Checks a STEP model and prints JSON: valid, solids, volume, bounding box and
size, the diameters of its cylindrical faces (holes, bores, turned diameters)
with how many faces have each, and `artifacts`: geometry that is almost
certainly a modelling slip rather than a drawn feature.

    python3 check_model.py model.step

`artifacts` lists, each with where it is:
- small_faces: faces under 1 mm² (slivers left where two cuts nearly meet);
- thin_faces: faces under 0.3 mm wide but longer than 2 mm (a cut that stops
  just short of, or just past, another face);
- near_steps: two parallel flat faces facing the same way, 0.01 to 1 mm apart
  and overlapping or side by side within 2 mm (a floor or wall built at two
  slightly different values, which shows as a ledge line);
- thin_walls: two parallel flat faces facing opposite ways, under 0.6 mm apart
  and overlapping in plan (a lip or skin of material left where a cut or a
  boss stops just short of a face).
These are candidates, not verdicts: a drawn feature can be this small (a
dimensioned 0.5 mm step, the slivers where a cross hole meets a groove). Look
at each one in the model and on the drawing; fix the ones the drawing does not
show, so the list holds only drawn features.

Exits 1 when the model is not a valid solid with positive volume.
"""
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from OCP.BRepAdaptor import BRepAdaptor_Surface  # noqa: E402
from OCP.BRepBndLib import BRepBndLib  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.Bnd import Bnd_Box  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.GeomAbs import GeomAbs_Plane  # noqa: E402
from OCP.IFSelect import IFSelect_RetDone  # noqa: E402
from OCP.STEPControl import STEPControl_Reader  # noqa: E402
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402
from OCP.TopoDS import TopoDS  # noqa: E402
from cadkit import info  # noqa: E402

SMALL_FACE_MM2 = 1.0
THIN_FACE_MM = 0.3
STEP_MIN, STEP_MAX = 0.01, 1.0
ADJACENT_MM = 2.0
THIN_WALL_MM = 0.6
r3 = lambda v: round(v, 3)  # noqa: E731


def _box(f):
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(f, b, True, False)
    return b.Get()


def artifacts(shape) -> dict:
    small, thin, planes = [], [], []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current())
        p = GProp_GProps()
        BRepGProp.SurfaceProperties_s(f, p)
        area = p.Mass()
        x0, y0, z0, x1, y1, z1 = _box(f)
        where = {"min": [r3(x0), r3(y0), r3(z0)], "max": [r3(x1), r3(y1), r3(z1)]}
        dims = sorted([x1 - x0, y1 - y0, z1 - z0])
        s = BRepAdaptor_Surface(f)
        kind = str(s.GetType()).split("_")[-1].lower()
        if area < SMALL_FACE_MM2:
            small.append({"area_mm2": round(area, 3), "surface": kind, **where})
        elif dims[1] < THIN_FACE_MM and dims[2] > 2.0:
            thin.append({"width_mm": r3(dims[1]), "length_mm": r3(dims[2]), "surface": kind, **where})
        if s.GetType() == GeomAbs_Plane:
            n = s.Plane().Axis().Direction()
            if f.Orientation() == TopAbs_REVERSED:
                n = n.Reversed()
            v = (n.X(), n.Y(), n.Z())
            k = max(range(3), key=lambda j: abs(v[j]))
            if abs(abs(v[k]) - 1) < 1e-6:
                lo, hi = (x0, y0, z0), (x1, y1, z1)
                planes.append((k, v[k] > 0, lo[k], lo, hi, area))
        ex.Next()

    steps, walls = [], []
    for i in range(len(planes)):
        for j in range(i + 1, len(planes)):
            a, b = planes[i], planes[j]
            if a[0] != b[0]:
                continue
            gap = abs(a[2] - b[2])
            others = [m for m in range(3) if m != a[0]]
            if a[1] != b[1]:
                # Material lies between the two faces only when they face away from
                # each other: the one facing + sits higher. Facing each other is a
                # narrow gap (a relief groove), which is not an artifact.
                up, down = (a, b) if a[1] else (b, a)
                material = up[2] > down[2]
                inside = all(min(a[4][m], b[4][m]) - max(a[3][m], b[3][m]) > 0 for m in others)
                if material and STEP_MIN <= gap < THIN_WALL_MM and inside:
                    walls.append({
                        "axis": "xyz"[a[0]],
                        "positions": [r3(a[2]), r3(b[2])],
                        "thickness_mm": r3(gap),
                        "near": [r3((max(a[3][m], b[3][m]) + min(a[4][m], b[4][m])) / 2) if m != a[0] else r3(a[2]) for m in range(3)],
                    })
                continue
            if not (STEP_MIN <= gap <= STEP_MAX):
                continue
            overlap = all(min(a[4][m], b[4][m]) - max(a[3][m], b[3][m]) > -ADJACENT_MM for m in others)
            if overlap:
                steps.append({
                    "axis": "xyz"[a[0]],
                    "positions": [r3(a[2]), r3(b[2])],
                    "gap_mm": r3(gap),
                    "near": [r3((a[3][m] + a[4][m]) / 2) if m != a[0] else r3(a[2]) for m in range(3)],
                })

    return {
        "small_faces": small[:30],
        "thin_faces": thin[:30],
        "near_steps": steps[:30],
        "thin_walls": walls[:30],
        "count": len(small) + len(thin) + len(steps) + len(walls),
    }


def artifact_points(a: dict) -> list:
    """One point per artifact, for marking them on a picture (render_views.py)."""
    pts = []
    for k in ("small_faces", "thin_faces"):
        for f in a[k]:
            pts.append([(lo + hi) / 2 for lo, hi in zip(f["min"], f["max"])])
    for k in ("near_steps", "thin_walls"):
        pts.extend(f["near"] for f in a[k])
    return pts


def main() -> None:
    r = STEPControl_Reader()
    if r.ReadFile(sys.argv[1]) != IFSelect_RetDone:
        print(json.dumps({"valid": False, "error": "could not read the STEP file"}))
        sys.exit(1)
    r.TransferRoots()
    shape = r.OneShape()
    i = info(shape)
    i["artifacts"] = artifacts(shape)
    print(json.dumps(i, indent=2))
    sys.exit(0 if i["valid"] and i["solids"] >= 1 and i["volume_mm3"] > 0 else 1)


if __name__ == "__main__":
    main()
