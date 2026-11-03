"""
MOTORE 3D PrimaVista: costruisce la stanza in Blender dalle MISURE e fa il render 360 (equirettangolare).

Si esegue DENTRO Blender, senza finestra:
    blender -b --factory-startup -P scena_blender.py -- scena.json uscita.png

scena.json (preparato da render.py) contiene, in metri e nel sistema della stanza
(fotocamera all'origine, x = destra, y = alto, z = avanti verso la parete A, pavimento a y = -h):
    stanza  {XL, XR, ZB, ZW, H, h, theta}
    fissi   [{tipo, parete, u:[a,b], v:[basso, alto]}]       porte, finestre, porte-finestre, passaggi
    mobili  [{nome, tipo, centro_m:[x,z], L, P, A, rot, quota_m, forma}]
    finiture{pavimento, rivestimento, pareti, ...}            colori e formati delle superfici
    render  {larghezza, campioni}

In Blender: X = x, Y = z, Z = y + h (pavimento a Z = 0). Nessuna AI: le misure sono quelle del progetto.
"""
import json
import math
import sys
import time

import bpy
import bmesh

T0 = time.time()
argomenti = sys.argv[sys.argv.index("--") + 1:]
SCENA = json.load(open(argomenti[0], encoding="utf-8"))
USCITA = argomenti[1]

S = SCENA["stanza"]
H, HC = S["H"], S["h"]                  # altezza soffitto, altezza fotocamera
XL, XR, ZB, ZW = S["XL"], S["XR"], S["ZB"], S["ZW"]
SPESSORE = 0.15
FIN = SCENA.get("finiture", {})
SUP = SCENA.get("superfici") or {}     # zone con piastrelle vere dal catalogo (se scelte)


# ------------------------------------------------------------------ utilità

def pulisci_scena():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def attiva(obj):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def applica_scala(obj):
    attiva(obj)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)


def cubo(nome, dimensioni, posizione, materiale=None, smusso=0.0, rotazione_z=0.0, genitore=None):
    """Parallelepipedo con il centro in 'posizione' (metri). Smusso facoltativo per spigoli morbidi."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=posizione)
    o = bpy.context.active_object
    o.name = nome
    o.scale = dimensioni
    o.rotation_euler.z = rotazione_z
    applica_scala(o)
    if smusso > 0:
        m = o.modifiers.new("smusso", "BEVEL")
        m.width = min(smusso, min(dimensioni) * 0.45)
        m.segments = 4
        m.limit_method = "ANGLE"
    if materiale:
        o.data.materials.append(materiale)
    if genitore:
        o.parent = genitore
    return o


def cilindro(nome, raggio, altezza, posizione, materiale=None, genitore=None, vertici=48, asse="Z"):
    bpy.ops.mesh.primitive_cylinder_add(radius=raggio, depth=altezza, location=posizione, vertices=vertici)
    o = bpy.context.active_object
    o.name = nome
    if asse == "X":
        o.rotation_euler.y = math.pi / 2
    elif asse == "Y":
        o.rotation_euler.x = math.pi / 2
    bpy.ops.object.shade_smooth()
    if materiale:
        o.data.materials.append(materiale)
    if genitore:
        o.parent = genitore
    return o


def taglia(oggetto, cutter):
    """Buco nell'oggetto (porte, finestre, vasche dei lavabi): boolean applicato, cutter eliminato."""
    bpy.context.view_layer.update()
    m = oggetto.modifiers.new("buco", "BOOLEAN")
    m.operation = "DIFFERENCE"
    m.object = cutter
    m.solver = "EXACT"
    attiva(oggetto)
    bpy.ops.object.modifier_apply(modifier=m.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def colore(hex_o_rgb):
    if isinstance(hex_o_rgb, str):
        h = hex_o_rgb.lstrip("#")
        rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    else:
        rgb = list(hex_o_rgb)
    # sRGB -> lineare (i colori del progetto sono scritti come li vede l'occhio)
    return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb] + [1.0]


# ------------------------------------------------------------------ materiali

_materiali = {}


def principled(nome, base, ruvidita=0.5, metallo=0.0, trasmissione=0.0, coat=0.0, ior=1.45):
    if nome in _materiali:
        return _materiali[nome]
    m = bpy.data.materials.new(nome)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = colore(base)
    b.inputs["Roughness"].default_value = ruvidita
    b.inputs["Metallic"].default_value = metallo
    for chiave in ("Transmission Weight", "Transmission"):
        if chiave in b.inputs:
            b.inputs[chiave].default_value = trasmissione
            break
    for chiave in ("Coat Weight", "Clearcoat"):
        if chiave in b.inputs:
            b.inputs[chiave].default_value = coat
            break
    b.inputs["IOR"].default_value = ior
    _materiali[nome] = m
    return m


def piastrelle(nome, colore1, colore2, fuga, largo, alto, ruvidita=0.35, sfalsata=False, piano_altezza=None, sopra=None):
    """Piastrelle IN SCALA REALE (metri) sul piano XY locale dell'oggetto: formato largo x alto, fuga 2 mm.
    'piano_altezza' + 'sopra': sopra quella quota (Y locale, metri dal pavimento) la parete diventa 'sopra'."""
    m = bpy.data.materials.new(nome)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes.get("Principled BSDF")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    brick = nt.nodes.new("ShaderNodeTexBrick")
    brick.offset = 0.5 if sfalsata else 0.0
    brick.offset_frequency = 2
    brick.inputs["Scale"].default_value = 1.0
    brick.inputs["Mortar Size"].default_value = 0.0025
    brick.inputs["Mortar Smooth"].default_value = 0.2
    brick.inputs["Brick Width"].default_value = largo
    brick.inputs["Row Height"].default_value = alto
    brick.inputs["Color1"].default_value = colore(colore1)
    brick.inputs["Color2"].default_value = colore(colore2)
    brick.inputs["Mortar"].default_value = colore(fuga)
    brick.inputs["Bias"].default_value = 0.0
    nt.links.new(coord.outputs["Object"], brick.inputs["Vector"])
    # leggera variazione di luce sulla superficie (la ceramica non è mai piatta al 100%)
    rumore = nt.nodes.new("ShaderNodeTexNoise")
    rumore.inputs["Scale"].default_value = 3.0
    nt.links.new(coord.outputs["Object"], rumore.inputs["Vector"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["Factor"].default_value = 0.06
    nt.links.new(brick.outputs["Color"], mix.inputs["A"])
    nt.links.new(rumore.outputs["Color"], mix.inputs["B"])
    colore_finale = mix.outputs["Result"]
    # rugosità: le fughe sono opache
    rug = nt.nodes.new("ShaderNodeMapRange")
    rug.inputs["From Min"].default_value = 0.0
    rug.inputs["From Max"].default_value = 1.0
    rug.inputs["To Min"].default_value = ruvidita
    rug.inputs["To Max"].default_value = 0.9
    nt.links.new(brick.outputs["Fac"], rug.inputs["Value"])
    rug_finale = rug.outputs["Result"]
    if piano_altezza is not None and sopra is not None:
        # rivestimento fino a una quota: sopra si passa all'intonaco
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(coord.outputs["Object"], sep.inputs["Vector"])
        soglia = nt.nodes.new("ShaderNodeMath")
        soglia.operation = "GREATER_THAN"
        soglia.inputs[1].default_value = piano_altezza
        nt.links.new(sep.outputs["Y"], soglia.inputs[0])
        mc = nt.nodes.new("ShaderNodeMix")
        mc.data_type = "RGBA"
        nt.links.new(soglia.outputs["Value"], mc.inputs["Factor"])
        nt.links.new(colore_finale, mc.inputs["A"])
        mc.inputs["B"].default_value = colore(sopra)
        colore_finale = mc.outputs["Result"]
        mr = nt.nodes.new("ShaderNodeMix")
        mr.data_type = "FLOAT"
        nt.links.new(soglia.outputs["Value"], mr.inputs["Factor"])
        nt.links.new(rug_finale, mr.inputs["A"])
        mr.inputs["B"].default_value = 0.85
        rug_finale = mr.outputs["Result"]
    nt.links.new(colore_finale, b.inputs["Base Color"])
    nt.links.new(rug_finale, b.inputs["Roughness"])
    return m


def legno(nome, chiaro, scuro, doghe=None):
    """Legno procedurale; con 'doghe' = (lunghezza, larghezza) diventa un parquet posato a correre."""
    m = bpy.data.materials.new(nome)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes.get("Principled BSDF")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    onde = nt.nodes.new("ShaderNodeTexWave")
    onde.wave_type = "BANDS"
    onde.inputs["Scale"].default_value = 6.0
    onde.inputs["Distortion"].default_value = 6.0
    onde.inputs["Detail"].default_value = 3.0
    mappa = nt.nodes.new("ShaderNodeMapping")
    mappa.inputs["Scale"].default_value = (1.0, 8.0, 1.0)
    nt.links.new(coord.outputs["Object"], mappa.inputs["Vector"])
    nt.links.new(mappa.outputs["Vector"], onde.inputs["Vector"])
    rampa = nt.nodes.new("ShaderNodeValToRGB")
    rampa.color_ramp.elements[0].color = colore(scuro)
    rampa.color_ramp.elements[1].color = colore(chiaro)
    nt.links.new(onde.outputs["Fac"], rampa.inputs["Fac"])
    uscita_colore = rampa.outputs["Color"]
    if doghe:
        brick = nt.nodes.new("ShaderNodeTexBrick")
        brick.offset = 0.37
        brick.inputs["Scale"].default_value = 1.0
        brick.inputs["Mortar Size"].default_value = 0.0012
        brick.inputs["Brick Width"].default_value = doghe[0]
        brick.inputs["Row Height"].default_value = doghe[1]
        brick.inputs["Color1"].default_value = (1, 1, 1, 1)
        brick.inputs["Color2"].default_value = (0.86, 0.86, 0.86, 1)
        brick.inputs["Mortar"].default_value = (0.35, 0.35, 0.35, 1)
        nt.links.new(coord.outputs["Object"], brick.inputs["Vector"])
        molt = nt.nodes.new("ShaderNodeMix")
        molt.data_type = "RGBA"
        molt.blend_type = "MULTIPLY"
        molt.inputs["Factor"].default_value = 1.0
        nt.links.new(uscita_colore, molt.inputs["A"])
        nt.links.new(brick.outputs["Color"], molt.inputs["B"])
        uscita_colore = molt.outputs["Result"]
    nt.links.new(uscita_colore, b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.45
    return m


# ------------------------------------------------------------------ piastrelle VERE (foto dal catalogo)

RUVIDITA_FINITURA = {"lucida": 0.05, "satinata": 0.22, "opaca": 0.42, "strutturata": 0.55}


def _nodo(nt, tipo, **valori):
    n = nt.nodes.new(tipo)
    for k, v in valori.items():
        setattr(n, k, v)
    return n


def _mat(nt, op, a, b=None):
    """Nodo Math: a e b possono essere numeri o uscite di altri nodi."""
    n = _nodo(nt, "ShaderNodeMath", operation=op)
    for i, x in enumerate((a, b)):
        if x is None:
            continue
        if isinstance(x, (int, float)):
            n.inputs[i].default_value = x
        else:
            nt.links.new(x, n.inputs[i])
    return n.outputs[0]


def nodi_piastrella(nt, coord, p):
    """La FOTO di una piastrella posata in scala reale sulle coordinate 'coord' (metri, piano XY).
    p: foto, largo, alto (m), fuga_mm, fuga_colore, finitura, posa (dritta | sfalsata | terzo | diagonale).
    Ogni piastrella è ruotata a caso (90° se quadrata, 180° se rettangolare) e ha una lievissima
    differenza di tono, come nella posa vera: niente effetto "carta da parati". Restituisce un BSDF."""
    largo, alto = p["largo"], p["alto"]
    g = max(p.get("fuga_mm", 2), 0) / 1000
    passo_x, passo_y = largo + g, alto + g
    if p.get("posa") == "diagonale":
        giro = _nodo(nt, "ShaderNodeVectorRotate", rotation_type="Z_AXIS")
        giro.inputs["Angle"].default_value = math.pi / 4
        nt.links.new(coord, giro.inputs["Vector"])
        coord = giro.outputs["Vector"]
    sep = _nodo(nt, "ShaderNodeSeparateXYZ")
    nt.links.new(coord, sep.inputs["Vector"])
    # riga e colonna della piastrella (con lo sfalsamento della posa)
    fy = _mat(nt, "DIVIDE", sep.outputs["Y"], passo_y)
    riga = _mat(nt, "FLOOR", fy)
    fx = _mat(nt, "DIVIDE", sep.outputs["X"], passo_x)
    if p.get("posa") == "sfalsata":
        fx = _mat(nt, "ADD", fx, _mat(nt, "MULTIPLY", _mat(nt, "FLOORED_MODULO", riga, 2.0), 0.5))
    elif p.get("posa") == "terzo":
        fx = _mat(nt, "ADD", fx, _mat(nt, "DIVIDE", _mat(nt, "FLOORED_MODULO", riga, 3.0), 3.0))
    colonna = _mat(nt, "FLOOR", fx)
    # posizione dentro la piastrella: 0..1 sulla piastrella, oltre 1 = fuga
    u = _mat(nt, "MULTIPLY", _mat(nt, "FRACT", fx), passo_x / largo)
    v = _mat(nt, "MULTIPLY", _mat(nt, "FRACT", fy), passo_y / alto)
    fuga = _mat(nt, "MAXIMUM", _mat(nt, "GREATER_THAN", u, 1.0), _mat(nt, "GREATER_THAN", v, 1.0))
    # un numero a caso per ogni piastrella
    cella = _nodo(nt, "ShaderNodeCombineXYZ")
    nt.links.new(colonna, cella.inputs["X"])
    nt.links.new(riga, cella.inputs["Y"])
    caso = _nodo(nt, "ShaderNodeTexWhiteNoise", noise_dimensions="3D")
    nt.links.new(cella.outputs["Vector"], caso.inputs["Vector"])
    quadrata = abs(largo - alto) < 0.01
    giri = _mat(nt, "FLOOR", _mat(nt, "MULTIPLY", caso.outputs["Value"], 4.0 if quadrata else 2.0))
    angolo = _mat(nt, "MULTIPLY", giri, math.pi / 2 if quadrata else math.pi)
    uv = _nodo(nt, "ShaderNodeCombineXYZ")
    nt.links.new(_mat(nt, "MINIMUM", u, 1.0), uv.inputs["X"])
    nt.links.new(_mat(nt, "MINIMUM", v, 1.0), uv.inputs["Y"])
    ruota = _nodo(nt, "ShaderNodeVectorRotate", rotation_type="Z_AXIS")
    ruota.inputs["Center"].default_value = (0.5, 0.5, 0.0)
    nt.links.new(uv.outputs["Vector"], ruota.inputs["Vector"])
    nt.links.new(angolo, ruota.inputs["Angle"])
    foto = _nodo(nt, "ShaderNodeTexImage", extension="EXTEND", interpolation="Cubic")
    foto.image = bpy.data.images.load(p["foto"], check_existing=True)
    nt.links.new(ruota.outputs["Vector"], foto.inputs["Vector"])
    # tono: ±4% tra una piastrella e l'altra
    tono = _nodo(nt, "ShaderNodeHueSaturation")
    nt.links.new(foto.outputs["Color"], tono.inputs["Color"])
    secondo_caso = _mat(nt, "FRACT", _mat(nt, "MULTIPLY", caso.outputs["Value"], 7.13))
    nt.links.new(_mat(nt, "ADD", _mat(nt, "MULTIPLY", secondo_caso, 0.08), 0.96), tono.inputs["Value"])
    mix = _nodo(nt, "ShaderNodeMix", data_type="RGBA")
    nt.links.new(fuga, mix.inputs["Factor"])
    nt.links.new(tono.outputs["Color"], mix.inputs["A"])
    mix.inputs["B"].default_value = colore(p.get("fuga_colore", "#b9b2a6"))
    # lucentezza: quella della finitura sulla piastrella, opaca sulla fuga
    ruv = _nodo(nt, "ShaderNodeMix", data_type="FLOAT")
    nt.links.new(fuga, ruv.inputs["Factor"])
    ruv.inputs["A"].default_value = RUVIDITA_FINITURA.get(p.get("finitura"), 0.4)
    ruv.inputs["B"].default_value = 0.9
    # rilievo: la fuga è più bassa; la finitura strutturata prende rilievo dalla foto
    altezza = _mat(nt, "SUBTRACT", 1.0, fuga)
    forza = 0.25
    if p.get("finitura") == "strutturata":
        altezza = _mat(nt, "ADD", altezza, _mat(nt, "MULTIPLY", foto.outputs["Color"], 0.3))
        forza = 0.4
    rilievo = _nodo(nt, "ShaderNodeBump")
    rilievo.inputs["Strength"].default_value = forza
    rilievo.inputs["Distance"].default_value = 0.0015
    nt.links.new(altezza, rilievo.inputs["Height"])
    b = _nodo(nt, "ShaderNodeBsdfPrincipled")
    nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
    nt.links.new(ruv.outputs["Result"], b.inputs["Roughness"])
    nt.links.new(rilievo.outputs["Normal"], b.inputs["Normal"])
    if p.get("finitura") == "lucida":
        for chiave in ("Coat Weight", "Clearcoat"):
            if chiave in b.inputs:
                b.inputs[chiave].default_value = 0.4
                break
    return b.outputs["BSDF"]


def nodi_superficie(nt, coord, p):
    """Superficie GIÀ POSATA (parquet, SPC, resina, lastre): la foto del produttore copre largo x alto metri
    e si ripete così com'è, senza aggiungere fughe e senza girarla."""
    mappa = _nodo(nt, "ShaderNodeMapping")
    mappa.inputs["Scale"].default_value = (1 / p["largo"], 1 / p["alto"], 1.0)
    nt.links.new(coord, mappa.inputs["Vector"])
    foto = _nodo(nt, "ShaderNodeTexImage", extension="REPEAT", interpolation="Cubic")
    foto.image = bpy.data.images.load(p["foto"], check_existing=True)
    nt.links.new(mappa.outputs["Vector"], foto.inputs["Vector"])
    rilievo = _nodo(nt, "ShaderNodeBump")
    rilievo.inputs["Strength"].default_value = 0.35 if p.get("finitura") == "strutturata" else 0.12
    rilievo.inputs["Distance"].default_value = 0.001
    nt.links.new(foto.outputs["Color"], rilievo.inputs["Height"])
    b = _nodo(nt, "ShaderNodeBsdfPrincipled")
    nt.links.new(foto.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = RUVIDITA_FINITURA.get(p.get("finitura"), 0.42)
    nt.links.new(rilievo.outputs["Normal"], b.inputs["Normal"])
    return b.outputs["BSDF"]


def nodi_strato(nt, coord, spec):
    """Uno strato di superficie: piastrella o superficie posata dal catalogo, oppure pittura a tinta unita."""
    if spec.get("piastrella"):
        p = dict(spec["piastrella"])
        if spec.get("verso") == "verticale" or p.get("verso") == "verticale":
            p["largo"], p["alto"] = p["alto"], p["largo"]          # piastrella rettangolare girata in piedi
        if p.get("foto_tipo") == "superficie":
            return nodi_superficie(nt, coord, p)
        return nodi_piastrella(nt, coord, p)
    b = _nodo(nt, "ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = colore(spec.get("colore", "#e2ddd4"))
    b.inputs["Roughness"].default_value = 0.85
    return b.outputs["BSDF"]


def materiale_zone(nome, base, zone):
    """Materiale composto per zone sul piano XY locale (X lungo la superficie, Y = altezza da terra).
    base: lo strato sotto; zone: [(spec, {"x": [a, b] facoltativo, "y_max": h facoltativo})] in ordine di priorità
    crescente (l'ultima vince)."""
    m = bpy.data.materials.new(nome)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    uscita = _nodo(nt, "ShaderNodeOutputMaterial")
    coord = _nodo(nt, "ShaderNodeTexCoord").outputs["Object"]
    sep = _nodo(nt, "ShaderNodeSeparateXYZ")
    nt.links.new(coord, sep.inputs["Vector"])
    shader = nodi_strato(nt, coord, base)
    for spec, dove in zone:
        maschera = 1.0
        if dove.get("y_max") is not None:
            maschera = _mat(nt, "LESS_THAN", sep.outputs["Y"], dove["y_max"])
        if dove.get("x"):
            dentro = _mat(nt, "MULTIPLY", _mat(nt, "GREATER_THAN", sep.outputs["X"], dove["x"][0]),
                          _mat(nt, "LESS_THAN", sep.outputs["X"], dove["x"][1]))
            maschera = dentro if maschera == 1.0 else _mat(nt, "MULTIPLY", maschera, dentro)
        mix = _nodo(nt, "ShaderNodeMixShader")
        if maschera == 1.0:
            mix.inputs["Fac"].default_value = 1.0
        else:
            nt.links.new(maschera, mix.inputs["Fac"])
        nt.links.new(shader, mix.inputs[1])
        nt.links.new(nodi_strato(nt, coord, spec), mix.inputs[2])
        shader = mix.outputs["Shader"]
    nt.links.new(shader, uscita.inputs["Surface"])
    return m


# ------------------------------------------------------------------ finiture scelte (dallo stile)

def finiture():
    f = {
        "pavimento": FIN.get("pavimento", {"tipo": "gres", "colore1": "#cfc8bd", "colore2": "#c7bfb3", "fuga": "#b9b2a7",
                                           "largo": 0.6, "alto": 0.6}),
        "rivestimento": FIN.get("rivestimento", None),
        "pareti": FIN.get("pareti", {"colore": "#ece8e1"}),
        "soffitto": FIN.get("soffitto", {"colore": "#f4f2ee"}),
        "legno_mobili": FIN.get("legno_mobili", {"chiaro": "#b48a5f", "scuro": "#8d6744"}),
        "accento": FIN.get("accento", "#2b2b2b"),
        "tessuto": FIN.get("tessuto", "#d9d2c5"),
    }
    return f


F = finiture()
M_CERAMICA = None
M_CROMO = None
M_VETRO = None
M_LACCATO = None
M_TESSUTO = None
M_ACCENTO = None


def prepara_materiali():
    global M_CERAMICA, M_CROMO, M_VETRO, M_LACCATO, M_TESSUTO, M_ACCENTO
    M_CERAMICA = principled("ceramica", "#f7f7f5", ruvidita=0.06, coat=0.6)
    M_CROMO = principled("rubinetteria", F["accento"], ruvidita=0.25, metallo=1.0)
    M_VETRO = principled("vetro", "#ffffff", ruvidita=0.0, trasmissione=1.0, ior=1.5)
    M_LACCATO = principled("laccato", F.get("laccato", "#e9e5de"), ruvidita=0.35)
    M_TESSUTO = principled("tessuto", F["tessuto"], ruvidita=0.95)
    M_ACCENTO = principled("accento", F["accento"], ruvidita=0.4, metallo=0.6)


# ------------------------------------------------------------------ la stanza

def stanza():
    W, D = XR - XL, ZW - ZB
    cx, cy = (XL + XR) / 2, (ZB + ZW) / 2
    # pavimento
    p = F["pavimento"]
    if p.get("tipo") == "parquet":
        m_pav = legno("pavimento", p.get("chiaro", "#c9a77f"), p.get("scuro", "#a17d55"), doghe=(p.get("largo", 1.2), p.get("alto", 0.18)))
    else:
        m_pav = piastrelle("pavimento", p["colore1"], p["colore2"], p["fuga"], p["largo"], p["alto"], ruvidita=p.get("ruvidita", 0.3))
    if SUP.get("pavimento"):
        m_pav = materiale_zone("pavimento_zone", SUP["pavimento"], [])
    cubo("Pavimento", (W, D, 0.02), (cx, cy, -0.01), m_pav)
    # soffitto
    m_sof = (materiale_zone("soffitto_zone", SUP["soffitto"], []) if SUP.get("soffitto")
             else principled("soffitto", F["soffitto"]["colore"], ruvidita=0.9))
    cubo("Soffitto", (W + 2 * SPESSORE, D + 2 * SPESSORE, 0.02), (cx, cy, H + 0.01), m_sof)
    # pareti: ogni parete è un "cubo" con il piano XY locale sulla superficie (X lungo la parete, Y in altezza)
    riv = F["rivestimento"]
    if riv:
        m_par = piastrelle("pareti", riv["colore1"], riv["colore2"], riv["fuga"], riv["largo"], riv["alto"],
                           ruvidita=riv.get("ruvidita", 0.15), piano_altezza=riv.get("altezza", 1.2),
                           sopra=F["pareti"]["colore"])
    else:
        m_par = principled("intonaco", F["pareti"]["colore"], ruvidita=0.85)
    pareti = {}
    definizioni = {
        # nome: (centro X, centro Y, lunghezza, rotazione Z, asse lungo cui corre u)
        "fondo": ((XL + XR) / 2, ZW + SPESSORE / 2, W + 2 * SPESSORE, 0.0),
        "dietro": ((XL + XR) / 2, ZB - SPESSORE / 2, W + 2 * SPESSORE, math.pi),
        "destra": (XR + SPESSORE / 2, (ZB + ZW) / 2, D, -math.pi / 2),
        "sinistra": (XL - SPESSORE / 2, (ZB + ZW) / 2, D, math.pi / 2),
    }
    for nome, (x, y, lung, rz) in definizioni.items():
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, H / 2))
        o = bpy.context.active_object
        o.name = f"Parete_{nome}"
        # cubo: X = lunghezza, Y = spessore, Z = altezza; poi ruotato attorno a Z
        o.scale = (lung, SPESSORE, H)
        o.rotation_euler.z = rz
        attiva(o)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        o.data.materials.append(materiale_parete(nome, x, y, rz) if SUP else m_par)
        pareti[nome] = o
    # coordinate "piastrelle" sulle pareti: X lungo la parete, Y = altezza dal pavimento (in metri)
    for o in pareti.values():
        for v in o.data.vertices:
            pass
    for nome, o in pareti.items():
        o["asse"] = nome
    return pareti


PAROLE_ZONA = {"doccia": ("doccia",), "zona_vasca": ("vasca",), "zona_lavabo": ("lavabo", "mobile bagno", "lavandino", "lavello")}


def zona_doccia(nome, wx, wy, rz, parole=("doccia",), margine=0.02):
    """Tratto della parete (X locale, metri dal centro della parete) dietro i mobili che la toccano
    (docce, vasche o lavabi secondo 'parole')."""
    piano = {"fondo": ("y", ZW), "dietro": ("y", ZB), "destra": ("x", XR), "sinistra": ("x", XL)}[nome]
    tratti = []
    for m in SCENA.get("mobili", []):
        if not any(k in f"{m.get('nome', '')} {m.get('tipo', '')}".lower() for k in parole):
            continue
        rot = math.radians(m.get("rot", 0.0))
        ca, sa = math.cos(rot), math.sin(rot)
        angoli = []
        for lx in (-m["L"] / 2, m["L"] / 2):
            for ly in (-m["P"] / 2, m["P"] / 2):
                angoli.append((m["centro_m"][0] + lx * ca + ly * sa, m["centro_m"][1] - lx * sa + ly * ca))
        vicino = min(abs((px if piano[0] == "x" else py) - piano[1]) for px, py in angoli)
        if vicino > 0.12:
            continue                     # il mobile non tocca questa parete
        lungo = [(px - wx) * math.cos(rz) + (py - wy) * math.sin(rz) for px, py in angoli]
        tratti.append([min(lungo) - margine, max(lungo) + margine])
    return tratti


def tutta(altezza):
    """Altezza di una zona: oltre il soffitto (o vuota) = tutta la parete."""
    return None if altezza is None or altezza >= H - 0.01 else altezza


def materiale_parete(nome, wx, wy, rz):
    """Le zone di una parete, dalla meno alla più importante:
    pareti (tutte) < parete singola < rivestimento fino a un'altezza < zona doccia."""
    zone = []
    singola = SUP.get(f"parete_{nome}")
    if singola:
        zone.append((singola, {"y_max": tutta(singola.get("altezza"))}))
    riv = SUP.get("rivestimento")
    if riv:
        zone.append((riv, {"y_max": tutta(riv.get("altezza", 1.2))}))
    # zone "bagnate": dietro lavabo, vasca e doccia (l'ultima vince)
    for chiave, alt_base, margine in (("zona_lavabo", 1.2, 0.10), ("zona_vasca", 2.2, 0.02), ("doccia", 2.2, 0.02)):
        z = SUP.get(chiave)
        if z:
            for tratto in zona_doccia(nome, wx, wy, rz, PAROLE_ZONA[chiave], margine):
                zone.append((z, {"x": tratto, "y_max": tutta(z.get("altezza", alt_base))}))
    return materiale_zone(f"parete_{nome}", SUP.get("pareti") or {"colore": F["pareti"]["colore"]}, zone)


def mappa_pareti(pareti):
    """Le texture usano le coordinate dell'oggetto: si spostano i vertici in modo che il locale sia
    (X lungo la parete, Y altezza da terra, Z spessore). Per questo la mesh si ricostruisce in locale."""
    for nome, o in pareti.items():
        rz = o.rotation_euler.z
        loc = o.location.copy()
        me = o.data
        bm = bmesh.new()
        bm.from_mesh(me)
        # mesh attuale: X lungo, Y spessore, Z altezza (centrata) -> X lungo, Y altezza (da 0), Z spessore
        for v in bm.verts:
            x, y, z = v.co
            v.co = (x, z + H / 2, y)
        bm.to_mesh(me)
        bm.free()
        # ora l'oggetto va ruotato di 90° attorno a X per rimettere Y locale in verticale
        o.rotation_euler = (math.pi / 2, 0.0, rz)
        o.location = (loc.x, loc.y, 0.0)


def apri(pareti, fissi):
    """Porte, finestre e passaggi: buchi nelle pareti, con infissi, vetri e ante."""
    m_telaio = principled("infisso", F.get("infissi", "#ece9e3"), ruvidita=0.4)
    m_porta = principled("porta", F.get("porte", "#efebe4"), ruvidita=0.35)
    finestre = []
    for f in fissi:
        u0, u1 = f["u"]
        v0, v1 = f["v"]
        largo, alto = u1 - u0, v1 - v0
        um = (u0 + u1) / 2
        parete = f["parete"]
        if parete in ("fondo", "dietro"):
            x, y = um, (ZW if parete == "fondo" else ZB)
            dim = (largo, SPESSORE * 3, alto)
            rz = 0.0
            normale = (0, 1 if parete == "fondo" else -1)
        else:
            x, y = (XR if parete == "destra" else XL), um
            dim = (SPESSORE * 3, largo, alto)
            rz = 0.0
            normale = (1 if parete == "destra" else -1, 0)
        zc = v0 + alto / 2
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, zc))
        cutter = bpy.context.active_object
        cutter.scale = dim
        attiva(cutter)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        taglia(pareti[parete], cutter)
        # profondità dell'infisso, spostato verso l'esterno della parete
        ox, oy = normale[0] * SPESSORE * 0.5, normale[1] * SPESSORE * 0.5
        lungo_x = parete in ("fondo", "dietro")
        sp_tel = 0.06
        def pezzo(nome, du, dz, lu, lz, prof, mat, scost=0.0):
            if lungo_x:
                return cubo(nome, (lu, prof, lz), (x + du, y + ox * 0 + oy * 0 + normale[1] * scost, zc + dz), mat)
            return cubo(nome, (prof, lu, lz), (x + normale[0] * scost, y + du, zc + dz), mat)
        if f["tipo"] in ("finestra", "porta-finestra"):
            sc = SPESSORE * 0.55
            pezzo("telaio_sx", -largo / 2 + sp_tel / 2, 0, sp_tel, alto, 0.07, m_telaio, sc)
            pezzo("telaio_dx", largo / 2 - sp_tel / 2, 0, sp_tel, alto, 0.07, m_telaio, sc)
            pezzo("telaio_su", 0, alto / 2 - sp_tel / 2, largo, sp_tel, 0.07, m_telaio, sc)
            pezzo("telaio_giu", 0, -alto / 2 + sp_tel / 2, largo, sp_tel, 0.07, m_telaio, sc)
            if largo > 0.9:
                pezzo("montante", 0, 0, sp_tel, alto, 0.07, m_telaio, sc)
            pezzo("vetro", 0, 0, largo - sp_tel, alto - sp_tel, 0.008, M_VETRO, sc)
            if f["tipo"] == "finestra" and v0 > 0.3:
                pezzo("davanzale", 0, -alto / 2 - 0.015, largo + 0.06, 0.03, SPESSORE + 0.06,
                      principled("davanzale", "#e6e0d6", ruvidita=0.3), 0.0)
            finestre.append((x, y, normale, zc, largo, alto))
        elif f["tipo"] == "porta":
            sc = SPESSORE * 0.15
            pezzo("anta", 0, 0, largo - 0.02, alto - 0.01, 0.04, m_porta, sc)
            # stipiti a cavallo dello spessore del muro, 2 cm in fuori per lato
            pezzo("stipite_sx", -largo / 2 - 0.03, 0, 0.07, alto + 0.07, SPESSORE + 0.04, m_porta, SPESSORE * 0.5)
            pezzo("stipite_dx", largo / 2 + 0.03, 0, 0.07, alto + 0.07, SPESSORE + 0.04, m_porta, SPESSORE * 0.5)
            pezzo("stipite_su", 0, alto / 2 + 0.035, largo + 0.13, 0.07, SPESSORE + 0.04, m_porta, SPESSORE * 0.5)
            # maniglia, verso l'interno
            dentro = -0.05
            if lungo_x:
                cubo("maniglia", (0.13, 0.02, 0.02), (x + largo / 2 - 0.12, y - normale[1] * 0.05, 1.05), M_ACCENTO)
            else:
                cubo("maniglia", (0.02, 0.13, 0.02), (x - normale[0] * 0.05, y + largo / 2 - 0.12, 1.05), M_ACCENTO)
    return finestre


# ------------------------------------------------------------------ mobili e sanitari a misura

CI_SONO_SPECCHI = any("specchio" in f"{m.get('nome', '')} {m.get('tipo', '')}".lower() for m in SCENA.get("mobili", []))
# temperatura della luce (Kelvin) -> colore
COLORE_K = {2700: (1.0, 0.76, 0.52), 3000: (1.0, 0.82, 0.62), 3500: (1.0, 0.87, 0.72), 4000: (1.0, 0.92, 0.82),
            5000: (1.0, 0.97, 0.93)}


def colore_k(k):
    k = min(COLORE_K, key=lambda x: abs(x - int(k or 3000)))
    return COLORE_K[k]


def materiale_specchio():
    if "specchio" not in _materiali:
        _materiali["specchio"] = principled("specchio", "#ffffff", ruvidita=0.0, metallo=1.0)
    return _materiali["specchio"]


def materiale_luce(nome, colore_rgb, forza):
    """Superficie che si vede accesa (diffusore, striscia LED)."""
    m = bpy.data.materials.new(nome)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (*colore_rgb, 1.0)
    e.inputs["Strength"].default_value = forza
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs["Emission"], out.inputs["Surface"])
    return m


def elemento_a_parete(nome, m, c, L, P, A, q):
    """Specchi, applique, mensole, pensili, colonne: appesi alla parete (retro su +Y), bordo basso a 'q' da terra."""
    if "specchio" in nome:
        luce = m.get("luce_specchio") or ("dietro" if (m.get("led") or "retroillumin" in nome) else "")
        led = luce == "dietro"
        if luce == "sopra":
            # lampada a barra sopra lo specchio, accesa verso il basso
            larga = min(0.6, L * 0.6)
            c("braccio_lampada", (0.04, 0.12, 0.02), (0, P / 2 - 0.06, q + A + 0.03), M_CROMO)
            c("lampada", (larga, 0.05, 0.025), (0, -P / 2 - 0.06, q + A + 0.035), M_CROMO, 0.005)
            striscia = c("led_lampada", (larga - 0.02, 0.035, 0.004), (0, -P / 2 - 0.06, q + A + 0.0215),
                         materiale_luce("lampada_specchio", colore_k(4000), 30))
            # la luce vera, agganciata alla lampada (si muove con lo specchio)
            bpy.ops.object.light_add(type="AREA", location=(0, 0, 0))
            lamp = bpy.context.active_object
            lamp.data.shape, lamp.data.size, lamp.data.size_y = "RECTANGLE", larga, 0.03
            lamp.data.energy, lamp.data.color = 18, colore_k(4000)
            lamp.parent = striscia
            lamp.location = (0, 0, -0.006)
            lamp.rotation_euler = (math.radians(25), 0, 0)
        c("supporto", (L - 0.02, max(P - 0.006, 0.006), A - 0.02), (0, 0.003, q + A / 2), principled("supporto", "#2b2b2b", 0.6))
        c("specchio", (L, 0.006, A), (0, -P / 2 + 0.003, q + A / 2), materiale_specchio(), 0.002)
        if led:
            # luce LED dietro lo specchio: alone sulla parete tutto intorno
            striscia = materiale_luce("led_specchio", colore_k(4000), 25)
            for nome_s, dim, pos in (("led_alto", (L - 0.06, 0.004, 0.01), (0, P / 2 - 0.004, q + A - 0.03)),
                                     ("led_basso", (L - 0.06, 0.004, 0.01), (0, P / 2 - 0.004, q + 0.03)),
                                     ("led_sx", (0.01, 0.004, A - 0.06), (-L / 2 + 0.03, P / 2 - 0.004, q + A / 2)),
                                     ("led_dx", (0.01, 0.004, A - 0.06), (L / 2 - 0.03, P / 2 - 0.004, q + A / 2))):
                c(nome_s, dim, pos, striscia)
    elif "applique" in nome:
        c("base_applique", (min(L, 0.08), 0.015, min(A, 0.12)), (0, P / 2 - 0.0075, q + A / 2), M_ACCENTO)
        diffusore = c("diffusore", (L, P - 0.02, A), (0, -0.01, q + A / 2), materiale_luce("diffusore", colore_k(3000), 12), 0.02)
        # la luce vera, appena davanti al diffusore (agganciata a lui: si muove con l'applique)
        bpy.ops.object.light_add(type="POINT", location=(0, 0, 0))
        luce = bpy.context.active_object
        luce.data.energy = 6
        luce.data.shadow_soft_size = 0.05
        luce.data.color = colore_k(3000)
        luce.parent = diffusore
        luce.location = (0, -(P - 0.02) / 2 - 0.04, 0)
    elif "mensola" in nome:
        c("mensola", (L, P, max(A, 0.025)), (0, 0, q + max(A, 0.025) / 2),
          legno("legno_mensola", F["legno_mobili"]["chiaro"], F["legno_mobili"]["scuro"]), 0.003)
    else:
        # pensile o colonna: scatola laccata con le ante (fuga sottile in mezzo se è larga)
        c("corpo", (L, P, A), (0, 0, q + A / 2), M_LACCATO, 0.004)
        if L > 0.45:
            c("fuga_ante", (0.003, 0.002, A - 0.02), (0, -P / 2 - 0.001, q + A / 2), principled("fuga", "#5a5a5a", 0.6))


def mobile(m):
    """Costruisce il mobile nel suo sistema locale (larghezza L lungo X, profondità P lungo Y,
    retro verso +Y, appoggio a terra Z = 0), poi lo ruota e lo mette al suo posto."""
    nome = f"{m.get('nome', '')} {m.get('tipo', '')}".lower()
    L, P, A, q = m["L"], m["P"], m["A"], m.get("quota_m", 0.0)
    bpy.ops.object.empty_add(location=(m["centro_m"][0], m["centro_m"][1], 0.0))
    radice = bpy.context.active_object
    radice.name = m.get("nome", "mobile")
    radice.rotation_euler.z = -math.radians(m.get("rot", 0.0))
    bpy.context.view_layer.update()
    g = radice

    def c(n, dim, pos, mat, smusso=0.0):
        return cubo(n, dim, pos, mat, smusso=smusso, genitore=g)

    if m.get("modello"):
        try:
            pezzi = importa_modello(m["modello"], L, P, A, q, g, m.get("rotazione_modello", 0), m.get("scala_modello") == "esatte")
            if "specchio" in nome:
                rendi_specchio(pezzi, radice, m.get("luce_specchio") or ("dietro" if m.get("led") else ""))
            if m.get("luce"):
                bpy.ops.object.light_add(type="POINT", location=(0, 0, 0))
                luce = bpy.context.active_object
                luce.data.energy, luce.data.shadow_soft_size, luce.data.color = 6, 0.05, colore_k(m.get("k", 3000))
                luce.parent = g
                luce.location = (0, -P / 2 - 0.05, q + A / 2)
            return radice
        except Exception as e:  # noqa: BLE001  modello illeggibile: si usa la forma a misura
            print(f"[PV] modello {m['modello']} non importato ({e}): forma a misura")

    if any(k in nome for k in ("specchio", "applique", "mensola", "pensile", "colonna bagno")) and "mobile bagno" not in nome:
        elemento_a_parete(nome, m, c, L, P, A, q)
        return radice
    if "doccia" in nome:
        c("piatto", (L, P, 0.03), (0, 0, 0.015), M_CERAMICA, 0.01)
        # vetri sui lati che NON toccano una parete (si capisce dalla posizione nella stanza)
        lati_liberi = lati_aperti(m)
        for lato in lati_liberi:
            if lato in ("davanti", "dietro"):
                y = -P / 2 if lato == "davanti" else P / 2
                larghezza = L * (0.7 if lato == "davanti" else 1.0)
                x = (L - larghezza) / 2 * (-1 if lato == "davanti" else 0)
                c("vetro_doccia", (larghezza, 0.008, 1.95), (x, y, 0.03 + 0.975), M_VETRO)
                c("profilo", (larghezza, 0.02, 0.02), (x, y, 2.0), M_ACCENTO)
            else:
                x = -L / 2 if lato == "sinistra" else L / 2
                c("vetro_doccia", (0.008, P, 1.95), (x, 0, 0.03 + 0.975), M_VETRO)
                c("profilo", (0.02, P, 0.02), (x, 0, 2.0), M_ACCENTO)
        # soffione e miscelatore sulla parete di fondo della doccia
        cilindro("soffione", 0.11, 0.012, (0, P / 2 - 0.25, 2.1), M_ACCENTO, g)
        c("braccio", (0.02, 0.25, 0.02), (0, P / 2 - 0.125, 2.12), M_ACCENTO)
        c("miscelatore", (0.12, 0.05, 0.06), (0, P / 2 - 0.03, 1.1), M_ACCENTO)
    elif "vasca" in nome:
        vasca = c("vasca", (L, P, A), (0, 0, A / 2), M_CERAMICA, 0.03)
        bpy.ops.mesh.primitive_cube_add(size=1, location=vasca.matrix_world @ __import__("mathutils").Vector((0, 0, A / 2 + 0.1)))
        cut = bpy.context.active_object
        cut.scale = (L - 0.12, P - 0.12, A)
        cut.rotation_euler.z = radice.rotation_euler.z
        taglia(vasca, cut)
        c("rubinetto", (0.05, 0.15, 0.04), (0, P / 2 - 0.08, A + 0.05), M_ACCENTO)
    elif "wc" in nome or "bidet" in nome:
        # sanitario sospeso: corpo arrotondato + placca di scarico sulla parete (solo WC)
        corpo = c("sanitario", (L, P, 0.32), (0, 0, 0.24), M_CERAMICA, 0.12)
        if "wc" in nome:
            c("sedile", (L * 0.95, P * 0.85, 0.03), (0, -0.02, 0.415), M_CERAMICA, 0.1)
            c("placca", (0.24, 0.015, 0.16), (0, P / 2 + 0.005, 1.0), principled("placca", "#f2f2f2", 0.2, 0.3))
        else:
            c("rubinetto", (0.04, 0.12, 0.05), (0, P / 2 - 0.07, 0.43), M_ACCENTO)
        _ = corpo
    elif "lavabo" in nome or "mobile bagno" in nome or ("bagno" in nome and "mobile" in nome):
        z0 = q if q > 0 else 0.3
        alto_mob = max(0.3, (A if A > 0 else 0.55))
        mob = c("mobile_lavabo", (L, P - 0.02, alto_mob - 0.03), (0, 0.01, z0 + (alto_mob - 0.03) / 2),
                legno("legno_mobile", F["legno_mobili"]["chiaro"], F["legno_mobili"]["scuro"]), 0.004)
        _ = mob
        piano = c("piano_lavabo", (L, P, 0.03), (0, 0, z0 + alto_mob - 0.015), M_CERAMICA, 0.01)
        # vasca del lavabo scavata nel piano
        import mathutils
        centro = radice.matrix_world @ mathutils.Vector((0, -0.03, z0 + alto_mob + 0.05))
        bpy.ops.mesh.primitive_cube_add(size=1, location=centro)
        cut = bpy.context.active_object
        cut.scale = (min(0.5, L - 0.15), P - 0.18, 0.14)
        cut.rotation_euler.z = radice.rotation_euler.z
        taglia(piano, cut)
        c("rubinetto", (0.03, 0.14, 0.03), (0, P / 2 - 0.1, z0 + alto_mob + 0.12), M_CROMO)
        c("rubinetto_base", (0.04, 0.04, 0.12), (0, P / 2 - 0.05, z0 + alto_mob + 0.06), M_CROMO)
        # specchio sopra il lavabo (solo se l'impresa non ne ha messo uno suo)
        if not CI_SONO_SPECCHI:
            c("specchio", (min(L, 0.9), 0.02, 0.7), (0, P / 2 + 0.01, z0 + alto_mob + 0.65), materiale_specchio())
    elif "termo" in nome or "scaldasalviette" in nome:
        for i in range(10):
            c(f"barra{i}", (L, 0.025, 0.02), (0, 0, 0.3 + i * (A - 0.3) / 10), M_ACCENTO)
        c("montante_sx", (0.03, 0.03, A - 0.25), (-L / 2, 0, 0.3 + (A - 0.3) / 2), M_ACCENTO)
        c("montante_dx", (0.03, 0.03, A - 0.25), (L / 2, 0, 0.3 + (A - 0.3) / 2), M_ACCENTO)
    elif "letto" in nome:
        c("base_letto", (L, P, 0.3), (0, 0, 0.15), M_TESSUTO, 0.02)
        c("materasso", (L - 0.04, P - 0.06, 0.22), (0, -0.02, 0.41), principled("lenzuola", "#f3f1ec", 0.9), 0.06)
        c("testiera", (L + 0.04, 0.08, 1.05), (0, P / 2 - 0.04, 0.525), M_TESSUTO, 0.03)
        for dx in ((-L / 4, L / 4) if L > 1.2 else (0,)):
            c("cuscino", (min(0.6, L / 2 - 0.1), 0.35, 0.14), (dx, P / 2 - 0.3, 0.58), principled("cuscini", "#ffffff", 0.9), 0.06)
    elif "divano" in nome:
        c("base_divano", (L, P, 0.42), (0, 0, 0.21), M_TESSUTO, 0.04)
        c("schienale", (L, 0.2, 0.42), (0, P / 2 - 0.1, 0.63), M_TESSUTO, 0.06)
        c("bracciolo_sx", (0.18, P, 0.22), (-L / 2 + 0.09, 0, 0.53), M_TESSUTO, 0.05)
        c("bracciolo_dx", (0.18, P, 0.22), (L / 2 - 0.09, 0, 0.53), M_TESSUTO, 0.05)
    elif "tappeto" in nome:
        c("tappeto", (L, P, 0.012), (0, 0, 0.006), principled("tappeto", F.get("tappeto", "#cbbfae"), 1.0))
    elif "tavolo" in nome or "tavolino" in nome or "scrivania" in nome:
        m_leg = legno("legno_tavolo", F["legno_mobili"]["chiaro"], F["legno_mobili"]["scuro"])
        if m.get("forma") == "cilindro":
            cilindro("piano", L / 2, 0.04, (0, 0, A - 0.02), m_leg, g)
            cilindro("gamba", 0.04, A - 0.04, (0, 0, (A - 0.04) / 2), M_ACCENTO, g)
        else:
            c("piano", (L, P, 0.04), (0, 0, A - 0.02), m_leg, 0.005)
            for sx in (-1, 1):
                for sy in (-1, 1):
                    c("gamba", (0.04, 0.04, A - 0.04), (sx * (L / 2 - 0.05), sy * (P / 2 - 0.05), (A - 0.04) / 2), M_ACCENTO)
    elif "sedia" in nome or "poltrona" in nome:
        mat = M_TESSUTO if "poltrona" in nome else legno("legno_sedia", F["legno_mobili"]["chiaro"], F["legno_mobili"]["scuro"])
        c("seduta", (L, P, 0.06 if "sedia" in nome else 0.2), (0, 0, 0.45 if "sedia" in nome else 0.3), mat, 0.02)
        c("schienale", (L, 0.05 if "sedia" in nome else 0.15, A - 0.45), (0, P / 2 - 0.05, 0.45 + (A - 0.45) / 2), mat, 0.02)
    else:
        # mobili contenitori e tutto il resto: volume a misura con frontali
        m_corpo = M_LACCATO if any(k in nome for k in ("armadio", "cucina", "pensil", "colonna", "frigo", "basi")) else \
            legno("legno_generico", F["legno_mobili"]["chiaro"], F["legno_mobili"]["scuro"])
        c("corpo", (L, P, A), (0, 0, q + A / 2), m_corpo, 0.004)
        ante = max(1, round(L / 0.5))
        for i in range(1, ante):
            c("fuga_anta", (0.004, 0.004, A - 0.04), (-L / 2 + i * L / ante, -P / 2 - 0.001, q + A / 2), M_ACCENTO)
        if "basi" in nome or "cucina" in nome:
            c("top", (L + 0.02, P + 0.02, 0.03), (0, -0.01, q + A + 0.015), principled("top", "#e8e4dc", 0.2))
    return radice


def importa_modello(percorso, L, P, A, quota, genitore, rotazione=0, esatte=False, sdraia=False):
    """Modello 3D del catalogo (GLB/GLTF/OBJ/FBX, del produttore o creato da Meshy) portato ESATTAMENTE alle misure
    del prodotto: larghezza L lungo X, profondità P lungo Y (fronte verso -Y, retro verso +Y), altezza A, a terra."""
    import mathutils
    prima = set(bpy.data.objects)
    basso = percorso.lower()
    if basso.endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=percorso)
    elif basso.endswith(".obj"):
        bpy.ops.wm.obj_import(filepath=percorso)
    elif basso.endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=percorso)
    else:
        raise ValueError("formato non supportato")
    nuovi = [o for o in bpy.data.objects if o not in prima]
    radici = [o for o in nuovi if o.parent is None or o.parent not in nuovi]
    bpy.context.view_layer.update()
    # orientamento corretto a mano dalla scheda (per i file dei produttori girati diversamente)
    if rotazione:
        giro = mathutils.Matrix.Rotation(math.radians(rotazione), 4, "Z")
        for o in radici:
            o.matrix_world = giro @ o.matrix_world
        bpy.context.view_layer.update()
    if sdraia:
        # luci a soffitto (plafoniere, faretti): il lato più sottile va in verticale, la faccia davanti verso il basso.
        # Meshy, da una foto presa di fronte, le crea "in piedi" come una ruota.
        pp = [o.matrix_world @ mathutils.Vector(v) for o in nuovi if o.type == "MESH" for v in o.bound_box]
        d = [max(p[i] for p in pp) - min(p[i] for p in pp) for i in range(3)]
        sottile = min(range(3), key=lambda i: d[i])
        giro = {1: mathutils.Matrix.Rotation(math.pi / 2, 4, "X"), 0: mathutils.Matrix.Rotation(-math.pi / 2, 4, "Y")}.get(sottile)
        if giro is not None:
            for o in radici:
                o.matrix_world = giro @ o.matrix_world
            bpy.context.view_layer.update()
    punti = [o.matrix_world @ mathutils.Vector(v) for o in nuovi if o.type == "MESH" for v in o.bound_box]
    if not punti:
        raise ValueError("nessuna geometria nel file")
    mn = mathutils.Vector((min(p.x for p in punti), min(p.y for p in punti), min(p.z for p in punti)))
    mx = mathutils.Vector((max(p.x for p in punti), max(p.y for p in punti), max(p.z for p in punti)))
    dim = mx - mn
    if esatte:
        # misure esatte su tutti e tre gli assi (file dei produttori, già proporzionati)
        scala = mathutils.Vector((L / max(dim.x, 1e-4), P / max(dim.y, 1e-4), A / max(dim.z, 1e-4)))
    else:
        # IN PROPORZIONE dalla larghezza: niente schiacciamenti. Serve per i modelli da foto (Meshy), che a volte
        # includono pezzi in più (es. il rubinetto a muro sopra la vasca) e falserebbero altezza e profondità.
        s = L / max(dim.x, 1e-4)
        scala = mathutils.Vector((s, s, s))
        print(f"[PV] modello in proporzione: {dim.x * s:.2f} x {dim.y * s:.2f} x {dim.z * s:.2f} m (scheda {L} x {P} x {A})")
    centro = mathutils.Vector(((mn.x + mx.x) / 2, (mn.y + mx.y) / 2, mn.z))
    bpy.ops.object.empty_add(location=(0, 0, 0))
    contenitore = bpy.context.active_object
    contenitore.name = "modello_catalogo"
    for o in radici:
        mondo = o.matrix_world.copy()
        o.parent = contenitore
        o.matrix_parent_inverse = mathutils.Matrix.Identity(4)
        o.matrix_world = mondo
    contenitore.scale = scala
    contenitore.location = (-centro.x * scala.x, -centro.y * scala.y, -centro.z * scala.z + quota)
    contenitore.parent = genitore
    for o in nuovi:
        if o.type == "MESH":
            o.data.update()
    return [o for o in nuovi if o.type == "MESH"]


def accendi_diffusore(oggetti, colore_rgb):
    """Plafoniere e faretti del catalogo: la parte di sotto (il diffusore) si vede accesa.
    Si accendono le facce rivolte in giù dello strato più basso, lasciando fuori il bordo esterno."""
    import collections
    import mathutils
    bpy.context.view_layer.update()
    facce = []
    for o in oggetti:
        m3 = o.matrix_world.to_3x3()
        for f in o.data.polygons:
            if (m3 @ f.normal).normalized().z < -0.9:
                facce.append((o, f, o.matrix_world @ f.center))
    if not facce:
        return
    strati = collections.Counter()
    for o, f, c in facce:
        strati[round(c.z / 0.005)] += f.area
    z_giu = strati.most_common(1)[0][0] * 0.005
    xs = [c.x for _, _, c in facce]
    ys = [c.y for _, _, c in facce]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    raggio = 0.85 * max(max(xs) - min(xs), max(ys) - min(ys)) / 2
    acceso = materiale_luce("diffusore_acceso", colore_rgb, 6)
    for o, f, c in facce:
        if abs(c.z - z_giu) < 0.008 and math.hypot(c.x - cx, c.y - cy) < raggio:
            if acceso.name not in [m.name for m in o.data.materials if m]:
                o.data.materials.append(acceso)
            f.material_index = [m.name if m else "" for m in o.data.materials].index(acceso.name)


def rendi_specchio(oggetti, radice, luce=""):
    """Modello di uno specchio (es. creato da Meshy, che lo fa grigio e opaco): la superficie piatta più grande
    rivolta verso la stanza diventa VETRO A SPECCHIO. luce: "sopra" = lampada sopra lo specchio (la parte che sporge
    in alto si accende e illumina in giù), "dietro" = LED dietro (alone sulla parete), "" = nessuna."""
    import collections
    import mathutils
    bpy.context.view_layer.update()
    inv = radice.matrix_world.inverted()
    giro = radice.matrix_world.to_3x3().normalized()
    fronte, su = giro @ mathutils.Vector((0, -1, 0)), mathutils.Vector((0, 0, 1))
    facce = []          # (oggetto, faccia, centro nel sistema del mobile, normale nel mondo)
    for o in oggetti:
        m3 = o.matrix_world.to_3x3()
        for f in o.data.polygons:
            facce.append((o, f, inv @ (o.matrix_world @ f.center), (m3 @ f.normal).normalized()))
    davanti = [x for x in facce if x[3].dot(fronte) > 0.9]
    if not davanti:
        return
    # profondità più "piena" di facce frontali = il vetro
    strati = collections.Counter()
    for o, f, c, n in davanti:
        strati[round(c.y / 0.01)] += f.area * (o.matrix_world.to_scale().x * o.matrix_world.to_scale().z)
    vetro_y = strati.most_common(1)[0][0] * 0.01
    vetro = [x for x in davanti if abs(x[2].y - vetro_y) < 0.012]
    mat = materiale_specchio()
    for o, f, c, n in vetro:
        if mat.name not in [m.name for m in o.data.materials if m]:
            o.data.materials.append(mat)
        f.material_index = [m.name if m else "" for m in o.data.materials].index(mat.name)
    xs = [c.x for _, _, c, _ in vetro]
    zs = [c.z for _, _, c, _ in vetro]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    print(f"[PV] specchio: vetro {x1 - x0:.2f} x {z1 - z0:.2f} m, luce '{luce}'")
    if luce == "sopra":
        # la lampada: i pezzi sopra il bordo alto del vetro; la loro parte di sotto si accende
        lampada = [x for x in facce if x[2].z > z1 + 0.01]
        accesa = materiale_luce("lampada_specchio", colore_k(4000), 30)
        for o, f, c, n in lampada:
            if n.dot(su) < -0.3:
                if accesa.name not in [m.name for m in o.data.materials if m]:
                    o.data.materials.append(accesa)
                f.material_index = [m.name if m else "" for m in o.data.materials].index(accesa.name)
        lx = [c.x for _, _, c, _ in lampada] or [-(x1 - x0) / 4, (x1 - x0) / 4]
        ly = [c.y for _, _, c, _ in lampada] or [vetro_y - 0.08]
        lz = [c.z for _, _, c, _ in lampada] or [z1 + 0.04]
        bpy.ops.object.light_add(type="AREA", location=(0, 0, 0))
        l = bpy.context.active_object
        l.data.shape, l.data.size, l.data.size_y = "RECTANGLE", max(0.1, max(lx) - min(lx)), 0.03
        l.data.energy, l.data.color = 18, colore_k(4000)
        l.parent = radice
        l.location = ((min(lx) + max(lx)) / 2, min(ly), min(lz) - 0.01)
        l.rotation_euler = (math.radians(25), 0, 0)          # guarda in giù, un po' verso la stanza
    elif luce == "dietro":
        dietro = max(c.y for _, _, c, _ in facce) - 0.004
        striscia = materiale_luce("led_specchio", colore_k(4000), 25)
        for nome_s, dim, pos in (("led_alto", (x1 - x0 - 0.06, 0.004, 0.01), ((x0 + x1) / 2, dietro, z1 - 0.03)),
                                 ("led_basso", (x1 - x0 - 0.06, 0.004, 0.01), ((x0 + x1) / 2, dietro, z0 + 0.03)),
                                 ("led_sx", (0.01, 0.004, z1 - z0 - 0.06), (x0 + 0.03, dietro, (z0 + z1) / 2)),
                                 ("led_dx", (0.01, 0.004, z1 - z0 - 0.06), (x1 - 0.03, dietro, (z0 + z1) / 2))):
            cubo(nome_s, dim, pos, striscia, genitore=radice)


def lati_aperti(m):
    """Lati della doccia che non toccano una parete (lì va il vetro)."""
    import mathutils
    rot = math.radians(m.get("rot", 0.0))
    ca, sa = math.cos(rot), math.sin(rot)
    lati = {"davanti": (0, -m["P"] / 2), "dietro": (0, m["P"] / 2), "sinistra": (-m["L"] / 2, 0), "destra": (m["L"] / 2, 0)}
    liberi = []
    for nome, (lx, ly) in lati.items():
        # dal sistema del mobile a quello della stanza (stessa rotazione usata per l'oggetto: -rot attorno a Z)
        x = m["centro_m"][0] + lx * ca + ly * sa
        y = m["centro_m"][1] - lx * sa + ly * ca
        vicino = min(abs(x - XL), abs(XR - x), abs(y - ZB), abs(ZW - y))
        if vicino > 0.06:
            liberi.append(nome)
    _ = mathutils
    return liberi


# ------------------------------------------------------------------ luce, fotocamera, render

def faretto_acceso():
    """Il vetrino del faretto: piccolo e luminoso, così nei riflessi è un puntino come nella realtà."""
    if "faretto_acceso" in _materiali:
        return _materiali["faretto_acceso"]
    m = principled("faretto_acceso", "#ffffff", 0.3)
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    for chiave in ("Emission Color", "Emission"):
        if chiave in b.inputs:
            b.inputs[chiave].default_value = (1.0, 0.9, 0.8, 1.0)
            break
    if "Emission Strength" in b.inputs:
        b.inputs["Emission Strength"].default_value = 8.0
    return m


def luci(finestre):
    mondo = bpy.data.worlds.new("Mondo")
    bpy.context.scene.world = mondo
    mondo.use_nodes = True
    nt = mondo.node_tree
    sfondo = nt.nodes.get("Background")
    cielo = nt.nodes.new("ShaderNodeTexSky")
    tipi = [i.identifier for i in cielo.bl_rna.properties["sky_type"].enum_items]
    for t in ("MULTIPLE_SCATTERING", "NISHITA", "HOSEK_WILKIE"):
        if t in tipi:
            cielo.sky_type = t
            break
    # sole dalla prima finestra (entra in diagonale), altrimenti alto
    azimut = 0.0
    if finestre:
        nx, ny = finestre[0][2][0], finestre[0][2][1]
        azimut = math.atan2(nx, ny)
    try:
        cielo.sun_elevation = math.radians(35)
        cielo.sun_rotation = azimut + math.radians(25)
    except AttributeError:
        pass
    nt.links.new(cielo.outputs["Color"], sfondo.inputs["Color"])
    sera = SCENA.get("atmosfera") == "sera"
    sfondo.inputs["Strength"].default_value = 0.004 if sera else 0.25
    if not sera:
        # di giorno, guardando FUORI dalla finestra (dalla fotocamera o attraverso il vetro) si vede luce piena, quasi bianca:
        # come nelle foto d'interni professionali. Nessuna vista inventata; la stanza resta illuminata dal cielo vero.
        percorso = nt.nodes.new("ShaderNodeLightPath")
        vista = nt.nodes.new("ShaderNodeMath")
        vista.operation = "MAXIMUM"
        nt.links.new(percorso.outputs["Is Camera Ray"], vista.inputs[0])
        nt.links.new(percorso.outputs["Is Transmission Ray"], vista.inputs[1])
        luminoso = nt.nodes.new("ShaderNodeBackground")
        luminoso.inputs["Color"].default_value = (1.0, 0.985, 0.96, 1.0)
        luminoso.inputs["Strength"].default_value = 4.0
        misto = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(vista.outputs[0], misto.inputs["Fac"])
        nt.links.new(sfondo.outputs["Background"], misto.inputs[1])
        nt.links.new(luminoso.outputs["Background"], misto.inputs[2])
        uscita = next(n for n in nt.nodes if n.type == "OUTPUT_WORLD")
        nt.links.new(misto.outputs["Shader"], uscita.inputs["Surface"])
    if SCENA.get("luci"):
        luci_scelte(SCENA["luci"], sera)
        if not sera:
            portali(finestre)
        return
    # luci interne calde, sempre: in un 360 d'interni senza luce artificiale gli angoli diventano neri
    W, D = XR - XL, ZW - ZB
    righe = max(1, round(D / 1.4))
    colonne = max(1, round(W / 1.4))
    for i in range(colonne):
        for j in range(righe):
            x = XL + (i + 0.5) * W / colonne
            y = ZB + (j + 0.5) * D / righe
            bpy.ops.object.light_add(type="AREA", location=(x, y, H - 0.02))
            l = bpy.context.active_object
            l.data.shape = "DISK"
            l.data.size = 0.25
            l.data.energy = (12 if finestre else 22) * max(1.0, (W * D) / (colonne * righe) / 1.5)
            l.data.color = (1.0, 0.86, 0.72)
            # la luce "di riempimento" (disco da 25 cm) non si specchia sui pavimenti: nei riflessi si vede solo il faretto vero
            try:
                l.visible_glossy = False
            except AttributeError:
                l.cycles.visible_glossy = False
            cilindro("faretto", 0.04, 0.008, (x, y, H - 0.004), faretto_acceso())
    portali(finestre)


def portali(finestre):
    """"Portale" di luce sulle finestre: più luce naturale, meno rumore."""
    import mathutils
    for (x, y, (nx, ny), zc, largo, alto) in finestre:
        bpy.ops.object.light_add(type="AREA", location=(x - nx * 0.05, y - ny * 0.05, zc))
        l = bpy.context.active_object
        l.data.shape = "RECTANGLE"
        l.data.size, l.data.size_y = largo, alto
        l.data.energy = 60 * largo * alto
        l.data.color = (1.0, 0.97, 0.94)
        # la luce guarda dentro la stanza (l'area emette lungo il suo -Z locale)
        l.rotation_euler = mathutils.Vector((-nx, -ny, 0.0)).to_track_quat("-Z", "Z").to_euler()


def luci_scelte(elenco, sera):
    """Le luci messe dall'impresa nella piantina. centro = [x, z] della stanza (metri), k = temperatura (Kelvin).
    faretto = incasso a soffitto che illumina verso il basso; plafoniera = disco luminoso; sospensione = lampada appesa."""
    forza = 1.0
    for i, l in enumerate(elenco):
        x, y = l["centro"]
        col = colore_k(l.get("k", 3000))
        tipo = l.get("tipo", "faretto")
        if l.get("modello"):
            bpy.ops.object.empty_add(location=(x, y, 0.0))
            appiglio = bpy.context.active_object
            A = l.get("A", 0.1)
            basso = H - (l.get("calata", 70) / 100 if tipo == "sospensione" else A)
            try:
                pezzi = importa_modello(l["modello"], l.get("L", 0.1), l.get("P", 0.1), A, basso, appiglio,
                                        l.get("rotazione_modello", 0), l.get("scala_modello") == "esatte",
                                        sdraia=tipo in ("plafoniera", "faretto"))
                if tipo in ("plafoniera", "faretto"):
                    accendi_diffusore(pezzi, col)
                if tipo == "sospensione":
                    cilindro(f"filo{i}", 0.004, H - basso - A, (x, y, (H + basso + A) / 2), M_ACCENTO)
                bpy.ops.object.light_add(type="SPOT" if tipo == "faretto" else ("AREA" if tipo == "plafoniera" else "POINT"),
                                         location=(x, y, basso - 0.03))
                luce = bpy.context.active_object
                if tipo == "faretto":
                    luce.data.spot_size, luce.data.spot_blend, luce.data.energy = math.radians(70), 0.6, 12 * forza
                elif tipo == "plafoniera":
                    luce.data.shape, luce.data.size, luce.data.energy = "DISK", max(0.1, l.get("L", 0.4)), 28 * forza
                else:
                    luce.data.shadow_soft_size, luce.data.energy = 0.06, 22 * forza
                luce.data.color = col
                continue
            except Exception as e:  # noqa: BLE001  modello illeggibile: si usa la luce disegnata dal programma
                print(f"[PV] luce {l.get('modello')} non importata ({e})")
        if tipo == "plafoniera":
            cilindro(f"plafoniera{i}", 0.2, 0.05, (x, y, H - 0.025), materiale_luce(f"plaf{i}", col, 6))
            bpy.ops.object.light_add(type="AREA", location=(x, y, H - 0.06))
            luce = bpy.context.active_object
            luce.data.shape, luce.data.size = "DISK", 0.4
            luce.data.energy = 28 * forza
        elif tipo == "sospensione":
            basso = H - (l.get("calata", 70) / 100)
            cilindro(f"filo{i}", 0.004, H - basso - 0.18, (x, y, (H + basso + 0.18) / 2), M_ACCENTO)
            cilindro(f"paralume{i}", 0.16, 0.18, (x, y, basso + 0.09), principled(f"paralume{i}", "#2b2b2b", 0.5, 0.3))
            cilindro(f"lampadina{i}", 0.05, 0.03, (x, y, basso + 0.01), materiale_luce(f"lamp{i}", col, 20))
            bpy.ops.object.light_add(type="POINT", location=(x, y, basso - 0.02))
            luce = bpy.context.active_object
            luce.data.shadow_soft_size = 0.06
            luce.data.energy = 22 * forza
        else:
            cilindro(f"faretto{i}", 0.04, 0.008, (x, y, H - 0.004), faretto_acceso())
            bpy.ops.object.light_add(type="SPOT", location=(x, y, H - 0.02))
            luce = bpy.context.active_object
            luce.data.spot_size = math.radians(70)
            luce.data.spot_blend = 0.6
            luce.data.shadow_soft_size = 0.03
            luce.data.energy = 12 * forza
        luce.data.color = col
    # luce di riempimento invisibile, debole: gli angoli lontani dalle luci non diventano neri
    W, D = XR - XL, ZW - ZB
    bpy.ops.object.light_add(type="AREA", location=((XL + XR) / 2, (ZB + ZW) / 2, H - 0.05))
    riemp = bpy.context.active_object
    riemp.data.shape, riemp.data.size, riemp.data.size_y = "RECTANGLE", W * 0.7, D * 0.7
    riemp.data.energy = (1.2 if sera else 3) * W * D
    riemp.data.color = (1.0, 0.9, 0.8)
    for chiave in ("visible_camera", "visible_glossy"):
        try:
            setattr(riemp, chiave, False)
        except AttributeError:
            pass


def fotocamera():
    bpy.ops.object.camera_add(location=(0.0, 0.0, HC))
    cam = bpy.context.active_object
    cam.data.type = "PANO"
    try:
        cam.data.panorama_type = "EQUIRECTANGULAR"
    except (AttributeError, TypeError):
        cam.data.cycles.panorama_type = "EQUIRECTANGULAR"
    # guarda verso la direzione "yaw 0" della foto: nel sistema della stanza è (sin θ, cos θ)
    cam.rotation_euler = (math.pi / 2, 0.0, -S.get("theta", 0.0))
    bpy.context.scene.camera = cam


def imposta_render():
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    r = SCENA.get("render", {})
    sc.render.resolution_x = int(r.get("larghezza", 4096))
    sc.render.resolution_y = int(r.get("larghezza", 4096)) // 2
    sc.render.resolution_percentage = 100
    sc.cycles.samples = int(r.get("campioni", 128))
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.02
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
    except TypeError:
        pass
    sc.cycles.max_bounces = 8
    sc.cycles.diffuse_bounces = 4
    sc.cycles.glossy_bounces = 4
    sc.cycles.transmission_bounces = 8
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    # scheda video: OptiX (RTX) se c'è, altrimenti CUDA, altrimenti processore
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for tipo in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = tipo
            prefs.get_devices()
            dispositivi = [d for d in prefs.devices if d.type == tipo]
            if dispositivi:
                for d in prefs.devices:
                    d.use = d.type == tipo
                sc.cycles.device = "GPU"
                print(f"[PV] GPU: {tipo} {[d.name for d in dispositivi]}")
                break
        except TypeError:
            continue
    # look fotografico morbido
    try:
        sc.view_settings.view_transform = "AgX"
        looks = [i.identifier for i in sc.view_settings.bl_rna.properties["look"].enum_items]
        for l in ("AgX - Medium High Contrast", "AgX - Base Contrast", "Medium High Contrast"):
            if l in looks:
                sc.view_settings.look = l
                break
    except TypeError:
        pass
    sc.view_settings.exposure = float(r.get("esposizione", 0.0)) + (0.3 if SCENA.get("atmosfera") == "sera" else 0.0)
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_depth = "8"
    sc.render.filepath = USCITA


def main():
    pulisci_scena()
    prepara_materiali()
    pareti = stanza()
    mappa_pareti(pareti)
    finestre = apri(pareti, SCENA.get("fissi", []))
    for m in SCENA.get("mobili", []):
        mobile(m)
    luci(finestre)
    fotocamera()
    imposta_render()
    print(f"[PV] scena pronta in {time.time() - T0:.1f}s")
    t = time.time()
    bpy.ops.render.render(write_still=True)
    print(f"[PV] render in {time.time() - t:.1f}s -> {USCITA}")


main()
