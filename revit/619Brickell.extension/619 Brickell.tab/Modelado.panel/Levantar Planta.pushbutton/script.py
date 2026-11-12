# -*- coding: utf-8 -*-
"""Levanta en Revit las plantas de 619 Brickell (muros, losa, barandales y puertas)
a partir de la geometria extraida del PDF del proyecto (escala 1/8" = 1'-0", unidades en pies)."""
__title__ = "Levantar\nPlanta"
__author__ = "619 Brickell"

import os, json
from pyrevit import revit, DB, forms, script
from System.Collections.Generic import List

doc = revit.doc
out = script.get_output()
HERE = os.path.dirname(__file__)

PLANES = [
    ("11", u"Nivel 11 (pool deck)", [11]),
    ("1N", u"Nivel 12", [12]),
    ("2C", u"Coleccion II - pisos 13 a 27", list(range(13, 28))),
    ("2N", u"Pisos 28 y 29", [28, 29]),
    ("3C", u"Coleccion III - pisos 30 a 43", list(range(30, 44))),
    ("3N", u"Pisos 44 y 45", [44, 45]),
    ("4C", u"Coleccion IV - pisos 46 a 59", list(range(46, 60))),
    ("4N", u"Pisos 60 y 61", [60, 61]),
    ("5C", u"Coleccion V - pisos 62 a 71", list(range(62, 72))),
    ("5N", u"Pisos 72 a 75", [72, 73, 74, 75]),
]
PLAN_DE_PISO = {}
for k, n, pisos in PLANES:
    for p in pisos:
        PLAN_DE_PISO[p] = k


class SinAdvertencias(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, fa):
        hubo_error = False
        for f in fa.GetFailureMessages():
            sev = f.GetSeverity()
            if sev == DB.FailureSeverity.Warning:
                fa.DeleteWarning(f)
            elif f.HasResolutions():
                try:
                    if f.HasResolutionOfType(DB.FailureResolutionType.DetachElements):
                        f.SetCurrentResolutionType(DB.FailureResolutionType.DetachElements)
                    elif f.HasResolutionOfType(DB.FailureResolutionType.DeleteElements):
                        f.SetCurrentResolutionType(DB.FailureResolutionType.DeleteElements)
                    fa.ResolveFailure(f)
                    hubo_error = True
                except Exception:
                    pass
        if hubo_error:
            return DB.FailureProcessingResult.ProceedWithCommit
        return DB.FailureProcessingResult.Continue


def cargar(k):
    with open(os.path.join(HERE, "plan_%s.json" % k)) as f:
        return json.load(f)


def material(nombres):
    for m in DB.FilteredElementCollector(doc).OfClass(DB.Material):
        for n in nombres:
            if n.lower() in m.Name.lower():
                return m.Id
    return DB.ElementId.InvalidElementId


def tipo_muro(nombre, pulgadas, mat):
    for wt in DB.FilteredElementCollector(doc).OfClass(DB.WallType):
        if DB.Element.Name.GetValue(wt) == nombre:
            return wt
    base = None
    for wt in DB.FilteredElementCollector(doc).OfClass(DB.WallType):
        if wt.Kind == DB.WallKind.Basic:
            base = wt
            break
    nuevo = base.Duplicate(nombre)
    cs = DB.CompoundStructure.CreateSingleLayerCompoundStructure(
        DB.MaterialFunctionAssignment.Structure, pulgadas / 12.0, mat)
    nuevo.SetCompoundStructure(cs)
    return nuevo


def niveles():
    lv = list(DB.FilteredElementCollector(doc).OfClass(DB.Level))
    return sorted(lv, key=lambda l: l.Elevation)


def nivel_de_piso(p, altura, crear):
    nombre = u"Nivel %d" % p
    for l in niveles():
        if l.Name == nombre:
            return l
    if not crear:
        return None
    l = DB.Level.Create(doc, (p - 11) * altura)
    l.Name = nombre
    return l


def pt(q, z):
    return DB.XYZ(q[0], q[1], z)


def levantar(data, nivel, altura, opciones, tipos):
    z = nivel.Elevation
    hechos = {"muros": 0, "losa": 0, "barandales": 0, "puertas": 0, "errores": 0}
    creados = {}
    if u"Muros" in opciones:
        for i, w in enumerate(data["muros"]):
            a, b = w["a"], w["b"]
            if ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 < 0.25:
                continue
            try:
                wt = tipos[(w["tipo"], w["t_in"])]
                muro = DB.Wall.Create(doc, DB.Line.CreateBound(pt(a, z), pt(b, z)),
                                      wt.Id, nivel.Id, altura, 0.0, False, False)
                try:
                    DB.WallUtils.DisallowWallJoinAtEnd(muro, 0)
                    DB.WallUtils.DisallowWallJoinAtEnd(muro, 1)
                except Exception:
                    pass
                creados[i] = muro
                hechos["muros"] += 1
            except Exception:
                hechos["errores"] += 1
    if u"Losa" in opciones:
        try:
            pts = data["losa"]
            limpio = [pts[0]]
            for q in pts[1:]:
                if ((q[0] - limpio[-1][0]) ** 2 + (q[1] - limpio[-1][1]) ** 2) ** 0.5 > 0.2:
                    limpio.append(q)
            cl = DB.CurveLoop()
            for i in range(len(limpio)):
                cl.Append(DB.Line.CreateBound(pt(limpio[i], z), pt(limpio[(i + 1) % len(limpio)], z)))
            ft = DB.FilteredElementCollector(doc).OfClass(DB.FloorType).FirstElement()
            loops = List[DB.CurveLoop]()
            loops.Add(cl)
            DB.Floor.Create(doc, loops, ft.Id, nivel.Id)
            hechos["losa"] = 1
        except Exception:
            hechos["errores"] += 1
    if u"Barandales" in opciones:
        rt = DB.FilteredElementCollector(doc).OfClass(DB.Architecture.RailingType).FirstElement()
        for a, b in data["barandales"]:
            try:
                cl = DB.CurveLoop()
                cl.Append(DB.Line.CreateBound(pt(a, z), pt(b, z)))
                DB.Architecture.Railing.Create(doc, cl, rt.Id, nivel.Id)
                hechos["barandales"] += 1
            except Exception:
                hechos["errores"] += 1
    if u"Puertas" in opciones and creados:
        sym = None
        for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).OfCategory(DB.BuiltInCategory.OST_Doors):
            sym = s
            break
        if sym is not None:
            if not sym.IsActive:
                sym.Activate()
                doc.Regenerate()
            for d in data["puertas"]:
                muro = creados.get(d["muro"])
                if muro is None:
                    continue
                try:
                    inst = doc.Create.NewFamilyInstance(pt(d["p"], z), sym, muro, nivel,
                                                       DB.Structure.StructuralType.NonStructural)
                    v = pt(d["abre_hacia"], z) - pt(d["p"], z)
                    if inst.FacingOrientation.DotProduct(v) < 0:
                        inst.flipFacing()
                    hechos["puertas"] += 1
                except Exception:
                    hechos["errores"] += 1
    return hechos


# ---------------- interfaz ----------------
eleccion = forms.SelectFromList.show(
    [u"Un piso", u"Una coleccion completa (todos sus pisos)", u"Toda la torre (pisos 11 a 75)"],
    title=u"619 Brickell - que quieres levantar?", button_name=u"Siguiente")
if not eleccion:
    script.exit()

pisos = []
if eleccion == u"Un piso":
    txt = forms.ask_for_string(default="30", prompt=u"Numero de piso (11 a 75):", title=u"Piso")
    if not txt:
        script.exit()
    pisos = [int(txt)]
elif eleccion.startswith(u"Una coleccion"):
    sel = forms.SelectFromList.show([n for k, n, p in PLANES], title=u"Planta tipo", button_name=u"Siguiente")
    if not sel:
        script.exit()
    pisos = [p for k, n, ps in PLANES if n == sel for p in ps]
else:
    pisos = list(range(11, 76))

opciones = forms.SelectFromList.show([u"Muros", u"Losa", u"Barandales", u"Puertas"], multiselect=True,
                                     title=u"Elementos a crear", button_name=u"Levantar")
if not opciones:
    script.exit()
txt = forms.ask_for_string(default="10.5", prompt=u"Altura entre pisos en pies (usada para muros y niveles nuevos):",
                           title=u"Altura de piso")
altura = float(txt or "10.5")

mat_c = material([u"concrete", u"concreto", u"hormigon"])
mat_t = material([u"gypsum", u"yeso", u"drywall"])
tipos = {}
resumen = []
with DB.TransactionGroup(doc, u"619 Brickell - levantar plantas") as tg:
    tg.Start()
    t = DB.Transaction(doc, u"Tipos de muro")
    t.Start()
    for tipo, nombre, mat in [("concreto", u"Concreto", mat_c), ("tabique", u"Tabique", mat_t), ("fachada", u"Fachada", mat_c)]:
        for pul in (4, 6, 8, 12):
            tipos[(tipo, pul)] = tipo_muro(u"619 - %s %d in" % (nombre, pul), pul, mat)
    t.Commit()
    cache = {}
    with forms.ProgressBar(title=u"Levantando piso {value} de {max_value}") as pb:
        for i, p in enumerate(pisos):
            k = PLAN_DE_PISO.get(p)
            if k is None:
                continue
            if k not in cache:
                cache[k] = cargar(k)
            t = DB.Transaction(doc, u"Piso %d" % p)
            op = t.GetFailureHandlingOptions()
            op.SetFailuresPreprocessor(SinAdvertencias())
            t.SetFailureHandlingOptions(op)
            t.Start()
            nivel = nivel_de_piso(p, altura, True)
            r = levantar(cache[k], nivel, altura, opciones, tipos)
            t.Commit()
            resumen.append((p, k, r))
            pb.update_progress(i + 1, len(pisos))
    tg.Assimilate()

out.print_md(u"## 619 Brickell - resultado")
filas = [[str(p), k, str(r["muros"]), str(r["losa"]), str(r["barandales"]), str(r["puertas"]), str(r["errores"])] for p, k, r in resumen]
out.print_table(filas, columns=[u"Piso", u"Planta", u"Muros", u"Losa", u"Barandales", u"Puertas", u"Omitidos"])
