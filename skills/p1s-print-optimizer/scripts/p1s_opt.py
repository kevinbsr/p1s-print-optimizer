#!/usr/bin/env python3
"""Otimiza projetos 3MF para a Bambu Lab P1S usando a CLI do Bambu Studio.

Subcomandos:
  inspect   resume impressora, perfis, filamentos, placas e pinturas de 3MFs
  presets   gera perfis completos (máquina/processo/filamento) a partir dos perfis oficiais
  slice     fatia um 3MF (como está, ou convertido com um perfil) e mede o resultado
  analyze   mede tempo e gramas por tipo de extrusão de pastas fatiadas
  render    desenha projeções do G-code com os suportes em vermelho
  objset    grava ajustes por objeto (ex.: altura de camada) no model_settings.config
  setproj   altera chaves do project_settings.config de um 3MF
  strip-paint  remove pintura (cor, suporte ou costura) de um 3MF
  finalize  marca os ajustes alterados no projeto fatiado e copia para o destino
  auto      fluxo completo: base, variantes (suporte × camada), escolha por custo, verificação e relatório

Os 3MF baixados são dados não confiáveis: o script nunca executa nada que venha
deles e as configurações de máquina e filamento vêm sempre dos perfis oficiais
instalados pelo Bambu Studio.
"""
import argparse
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
DEFAULT_PROFILE = os.path.join(SKILL_DIR, "profiles", "qualidade-baixo-custo.json")
SYSTEM_DIR = os.environ.get("P1S_SYSTEM_DIR", os.path.expanduser("~/.config/BambuStudio/system/BBL"))
BAMBU = os.environ.get("BAMBU_STUDIO", "bambu-studio")
META_KEYS = {"name", "inherits", "from", "setting_id", "instantiation", "type", "description",
             "include", "compatible_printers", "compatible_printers_condition", "compatible_prints",
             "compatible_prints_condition", "filament_id", "url", "model_id", "print_settings_id",
             "print_extruder_id", "print_extruder_variant"}
# Chaves que não aparecem na cadeia dos perfis do sistema; valor padrão do Bambu Studio.
IMPLICIT_DEFAULTS = {"ensure_vertical_shell_thickness": "enabled"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- perfis do sistema
_INDEX = None


def index():
    global _INDEX
    if _INDEX is None:
        _INDEX = {}
        if not os.path.isdir(SYSTEM_DIR):
            sys.exit(f"Perfis do sistema não encontrados em {SYSTEM_DIR}. "
                     "Abra o Bambu Studio uma vez ou defina P1S_SYSTEM_DIR.")
        for t in ("machine", "process", "filament"):
            for f in glob.glob(os.path.join(SYSTEM_DIR, t, "*.json")):
                try:
                    d = json.load(open(f, encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if "name" in d:
                    _INDEX[(t, d["name"])] = d
    return _INDEX


def flat(t, name):
    """Resolve a herança (inherits/include) de um perfil do sistema."""
    idx = index()
    if (t, name) not in idx:
        raise KeyError(f"perfil {t} '{name}' não existe em {SYSTEM_DIR}")
    d = idx[(t, name)]
    out = {}
    if d.get("inherits"):
        out.update(flat(t, d["inherits"]))
    for inc in d.get("include", []) or []:
        if (t, inc) in idx:
            out.update(flat(t, inc))
    out.update(d)
    return out


def map_filament(src_name, machine, fallback):
    """Encontra o perfil oficial equivalente compatível com a máquina alvo."""
    base = src_name.split(" @")[0].strip()
    names = [n for (t, n) in index() if t == "filament" and n.split(" @")[0].strip() == base]
    exact = [n for n in names if machine in (flat("filament", n).get("compatible_printers") or [])]
    if exact:
        exact.sort(key=lambda n: ("P1S" not in n, len(n)))
        return exact[0], None
    return fallback, f"filamento '{src_name}' sem equivalente oficial para {machine}; usando '{fallback}'"


def write_preset(t, name, path, overrides=None):
    d = flat(t, name)
    d.pop("inherits", None)
    d.pop("include", None)
    d["from"] = "system"
    d["name"] = name
    for k, v in (overrides or {}).items():
        old = d.get(k)
        d[k] = [str(v)] * len(old) if isinstance(old, list) else str(v)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    return path


LAYER_PRESET_ORDER = ("Optimal", "Standard", "Fine", "Extra Fine", "Draft")


def process_for_layer(proc, layer):
    """Processo oficial da mesma família (sufixo @...) com a altura de camada pedida."""
    try:
        if abs(float(flat("process", proc).get("layer_height", 0)) - float(layer)) < 1e-6:
            return proc
    except (KeyError, ValueError):
        pass
    suffix = proc.split(" @", 1)[1] if " @" in proc else ""
    pre = f"{float(layer):.2f}mm "
    names = [n for (t, n) in index() if t == "process" and n.startswith(pre) and n.endswith(" @" + suffix)]
    if not names:
        return None

    def rank(n):
        label = n[len(pre):n.rfind(" @")]
        return (LAYER_PRESET_ORDER.index(label) if label in LAYER_PRESET_ORDER else 99, n)
    return sorted(names, key=rank)[0]


def load_profile(path):
    with open(path or DEFAULT_PROFILE, encoding="utf-8") as f:
        return json.load(f)


def build_presets(profile, outdir, candidate=None, extra=None, layer=None):
    """Gera máquina e processo. Com `layer` (ou layer_height em extra), a base passa a ser
    o processo oficial dessa camada, que já traz as camadas de topo/fundo adequadas."""
    os.makedirs(outdir, exist_ok=True)
    extra = dict(extra or {})
    layer = layer or extra.pop("layer_height", None)
    proc = profile["process"]
    if layer:
        alt = process_for_layer(proc, layer)
        if alt:
            proc = alt
        else:
            log(f"aviso: sem processo oficial de {layer} mm na família de '{proc}'; só layer_height muda")
            extra["layer_height"] = layer
    ov = dict(profile["overrides"])
    if candidate:
        ov.update(profile["support_candidates"][candidate])
    ov.update(extra)
    m = write_preset("machine", profile["machine"], os.path.join(outdir, "machine.json"))
    tag = (candidate or "base") + (f"@{layer}" if layer else "")
    p = write_preset("process", proc, os.path.join(outdir, f"process_{tag}.json"), ov)
    return m, p


# ---------------------------------------------------------------- 3MF
def read_entry(path, name):
    with zipfile.ZipFile(path) as z:
        return z.read(name)


def entries(path):
    with zipfile.ZipFile(path) as z:
        return z.namelist()


def rewrite_3mf(src, dst, replace):
    """Copia o 3MF trocando entradas: replace = {nome: bytes | função(bytes)->bytes}."""
    tmp = dst + ".tmp"
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zo:
        for info in zi.infolist():
            data = zi.read(info.filename)
            if info.filename in replace:
                r = replace[info.filename]
                data = r(data) if callable(r) else r
            zo.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    os.replace(tmp, dst)


def project_settings(path):
    return json.loads(read_entry(path, "Metadata/project_settings.config"))


def model_entries(path):
    return [n for n in entries(path) if n.startswith("3D/Objects/") and n.endswith(".model")] or ["3D/3dmodel.model"]


def paint_counts(path):
    counts = {"paint_color": 0, "paint_supports": 0, "paint_seam": 0}
    pat = re.compile(rb' (paint_color|paint_supports|paint_seam)="')
    keep = 32  # bytes reaproveitados entre blocos para não perder ocorrências na fronteira
    with zipfile.ZipFile(path) as z:
        for n in model_entries(path):
            with z.open(n) as f:
                tail = b""
                while True:
                    chunk = f.read(1 << 24)
                    buf = tail + chunk
                    limit = len(buf) - keep if chunk else len(buf)
                    for m in pat.finditer(buf):
                        if m.start() < limit:
                            counts[m.group(1).decode()] += 1
                    if not chunk:
                        break
                    tail = buf[limit:]
    return counts


def inspect(path):
    ps = project_settings(path)
    info = {
        "arquivo": os.path.basename(path),
        "impressora": ps.get("printer_model"),
        "perfil_maquina": ps.get("printer_settings_id"),
        "perfil_processo": ps.get("print_settings_id"),
        "filamentos": ps.get("filament_settings_id"),
        "cores": ps.get("filament_colour"),
        "camada": ps.get("layer_height"),
        "preenchimento": f'{ps.get("sparse_infill_density")} {ps.get("sparse_infill_pattern")}',
        "suporte": f'{ps.get("enable_support")} {ps.get("support_type")} {ps.get("support_style")} limiar={ps.get("support_threshold_angle")}',
        "mesa": ps.get("curr_bed_type"),
        "versao": ps.get("version"),
        "pintura": paint_counts(path),
    }
    try:
        ms = read_entry(path, "Metadata/model_settings.config").decode("utf-8", "replace")
        info["placas"] = len(re.findall(r"<plate>", ms))
        objs = re.findall(r'<object id="(\d+)">\s*<metadata key="name" value="([^"]*)"/>', ms)
        info["objetos"] = [f"{i}:{n}" for i, n in objs]
        info["ajustes_por_objeto"] = sorted(set(re.findall(r'<object id="\d+">(?:(?!</object>).)*?<metadata key="(layer_height|support_[a-z_]+|wall_loops|sparse_infill_[a-z_]+)"', ms, re.S)))
    except KeyError:
        pass
    return info


# ---------------------------------------------------------------- CLI do Bambu Studio
def run_bambu(src, outdir, datadir, settings=None, filaments=None, slice_=True, export="out.3mf", extra=()):
    os.makedirs(outdir, exist_ok=True)
    cmd = [BAMBU, "--datadir", datadir, "--debug", "2", *extra]
    if settings:
        cmd += ["--load-settings", ";".join(settings)]
    if filaments:
        cmd += ["--load-filaments", ";".join(filaments)]
    if slice_:
        cmd += ["--slice", "0"]
    cmd += ["--export-3mf", export, "--outputdir", outdir, os.path.abspath(src)]
    with open(os.path.join(outdir, "log.txt"), "w") as lf:
        rc = subprocess.call(cmd, cwd=outdir, stdout=lf, stderr=subprocess.STDOUT)
    if rc != 0:
        raise RuntimeError(f"bambu-studio terminou com código {rc}; veja {outdir}/log.txt")
    return os.path.join(outdir, export)


def log_warnings(outdir):
    out = []
    try:
        for line in open(os.path.join(outdir, "log.txt"), errors="replace"):
            if ("[error]" in line and "ZFiller" not in line) or "disable prime tower" in line:
                out.append(line.split("]", 3)[-1].strip()[:200])
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- análise do G-code
NUM = re.compile(r" E(-?[\d.]+)")


XY = re.compile(r" ([XY])(-?[\d.]+)")
NO_PATH = ("Prime tower", "Custom", "Flush", "?")  # purga e movimentos da troca não são peça
TINY_PER_NOZZLE = 3.75   # trecho menor que 3,75 × bico (1,5 mm no bico 0,4) = detalhe que o bico não desenha bem


def analyze_gcode(path):
    feat, rel, last, maxz = "?", True, 0.0, 0.0
    retracted = 0.0  # filamento recolhido; o avanço que o devolve não é extrusão nova
    ext, hdr = {}, {}
    density, diam, nozzle = [1.24], 1.75, 0.4
    # qualidade: trechos minúsculos, recolhimentos por camada, camadas com troca de cor
    x = y = 0.0
    path_len, z, tiny_layer = 0.0, 0.0, {}
    retr_layer, change_layers, changes, objects = {}, set(), 0, set()
    with open(path, errors="replace") as f:
        for line in f:
            c = line[0]
            if c == ";":
                if line.startswith("; FEATURE: "):
                    feat = line[11:].strip()
                elif line.startswith("; start printing object, unique label id: "):
                    objects.add(line.rsplit(":", 1)[1].strip())
                elif line.startswith("; Z_HEIGHT: "):
                    z = float(line[12:])
                    maxz = max(maxz, z)
                elif line.startswith("; filament_density"):
                    density = [float(x) for x in re.split(r"[,;]", re.split(r"[:=]", line, maxsplit=1)[1]) if x.strip()]
                elif line.startswith("; nozzle_diameter"):
                    nozzle = float(re.split(r"[,;]", re.split(r"[:=]", line, maxsplit=1)[1])[0])
                elif line.startswith("; filament_diameter"):
                    diam = float(re.split(r"[,;]", re.split(r"[:=]", line, maxsplit=1)[1])[0])
                elif line.startswith("; model printing time"):
                    m = re.match(r"; model printing time: (.*); total estimated time: (.*)", line)
                    if m:
                        hdr["tempo"] = m.group(2).strip()
                elif line.startswith("; total filament weight"):
                    hdr["peso_g"] = [float(x) for x in line.split(":", 1)[1].split(",") if x.strip()]
                elif line.startswith("; total layer number"):
                    hdr["camadas"] = int(line.split(":", 1)[1])
                continue
            if c == "M":
                if line.startswith("M620 S") and line[6:7].isdigit() and not line.startswith("M620 S255"):
                    changes += 1
                    change_layers.add(round(z, 2))
                if line.startswith("M83"):
                    rel = True
                elif line.startswith("M82"):
                    rel = False
            elif c == "G":
                if line.startswith(("G0 ", "G1 ", "G2 ", "G3 ")):
                    nx, ny = x, y
                    for ax, v in XY.findall(line):
                        if ax == "X":
                            nx = float(v)
                        else:
                            ny = float(v)
                    m = NUM.search(line)
                    extruding = False
                    if m:
                        e = float(m.group(1))
                        if not rel:
                            e, last = e - last, e
                        if e < 0:
                            if retracted < 0.01:   # conta o evento, não cada pedaço do wipe
                                retr_layer[round(z, 2)] = retr_layer.get(round(z, 2), 0) + 1
                            retracted -= e
                        elif e > 0:
                            back = min(e, retracted)
                            retracted -= back
                            if e > back:
                                ext[feat] = ext.get(feat, 0.0) + e - back
                                extruding = (nx, ny) != (x, y)
                    if extruding and feat not in NO_PATH:
                        path_len += math.hypot(nx - x, ny - y)
                    elif (nx, ny) != (x, y):   # deslocamento sem extrusão fecha o trecho
                        if 0 < path_len < TINY_PER_NOZZLE * nozzle:
                            tiny_layer[round(z, 2)] = tiny_layer.get(round(z, 2), 0) + 1
                        path_len = 0.0
                    x, y = nx, ny
                elif line.startswith("G92") and " E" in line:
                    last = 0.0
    k = math.pi * (diam / 2) ** 2 * (sum(density) / len(density)) / 1000
    feats = {a: round(v * k, 2) for a, v in sorted(ext.items(), key=lambda x: -x[1])}
    return {
        "tempo": hdr.get("tempo"),
        "segundos": parse_time(hdr.get("tempo")),
        "peso_g": round(sum(hdr.get("peso_g", [sum(feats.values())])), 2),
        "camadas": hdr.get("camadas"),
        "altura_mm": round(maxz, 2),
        "suporte_g": round(sum(v for a, v in feats.items() if a.startswith("Support")), 2),
        "torre_g": feats.get("Prime tower", 0.0),
        "por_tipo_g": feats,
        "qualidade": {
            "pecas": max(len(objects), 1),
            "bico_mm": nozzle,
            "trocas_de_cor": max(0, changes - 1),   # a primeira carga não é troca
            "camadas_com_troca": len(change_layers),
            "recolhimentos_max_camada": max(retr_layer.values(), default=0),
            "trechos_minusculos": sum(tiny_layer.values()),
            "trechos_minusculos_max_camada": max(tiny_layer.values(), default=0),
        },
    }


def quality_notes(name, p):
    """Avisos de acabamento tirados do G-code: o que costuma virar bolinha, falha, fiapo ou respingo."""
    q, n = p.get("qualidade") or {}, []
    layers = max(p.get("camadas") or 1, 1)
    pecas = q.get("pecas", 1)
    # limites por peça e por camada, calibrados em 2026-10-15: aros lisos ≈ 6 trechos e 16 recolhimentos;
    # escudos com detalhe que saíram com falhas e fiapos ≈ 60–140 de cada
    # calibrado no bico 0,4; no 0,2 os detalhes finos são impressos de verdade e geram muitos trechos curtos
    if q.get("bico_mm", 0.4) >= 0.4 and q.get("trechos_minusculos_max_camada", 0) > 40 * pecas:
        n.append(f"{name}: até {q['trechos_minusculos_max_camada']} trechos de extrusão curtos (< {TINY_PER_NOZZLE * q.get('bico_mm', 0.4):g} mm) numa camada "
                 f"({pecas} peças) — detalhes menores que o bico saem como bolinhas e falhas; engrosse-os para "
                 "0,8 mm (2 linhas) ou aumente a peça")
    if q.get("recolhimentos_max_camada", 0) > 40 * pecas:
        n.append(f"{name}: até {q['recolhimentos_max_camada']} recolhimentos numa camada ({pecas} peças) — risco de fiapos; "
                 "use o perfil relevo-multicor (evitar cruzar paredes), filamento seco e 5–10 °C a menos")
    if q.get("trocas_de_cor", 0) > 30 and q.get("camadas_com_troca", 0) > 0.6 * layers:
        n.append(f"{name}: troca de cor em {q['camadas_com_troca']} de {layers} camadas — peças de uma cor só (aros, bases) "
                 "na placa de peças multicor somam trocas e recebem respingos de outras cores; separe-as por cor")
    gap = p.get("por_tipo_g", {}).get("Gap infill", 0)
    if gap > 0.03 * max(p.get("peso_g", 0) - p.get("torre_g", 0), 0.1):
        n.append(f"{name}: {gap:.1f} g de preenchimento de vãos — áreas estreitas; mantenha gap_infill_speed baixo (≤ 50 mm/s)")
    return n


def parse_time(s):
    if not s:
        return 0
    t = 0
    for n, u in re.findall(r"(\d+)\s*([dhms])", s):
        t += int(n) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[u]
    return t


def fmt_time(sec):
    h, m = divmod(round(sec / 60), 60)
    return f"{h}h{m:02d}"


def analyze_dir(d):
    plates = {}
    for g in sorted(glob.glob(os.path.join(d, "plate_*.gcode")), key=lambda p: int(re.findall(r"\d+", os.path.basename(p))[0])):
        plates[os.path.basename(g)[:-6]] = analyze_gcode(g)
    tot = {"peso_g": round(sum(p["peso_g"] for p in plates.values()), 2),
           "segundos": sum(p["segundos"] for p in plates.values()),
           "suporte_g": round(sum(p["suporte_g"] for p in plates.values()), 2),
           "torre_g": round(sum(p["torre_g"] for p in plates.values()), 2)}
    return {"placas": plates, "total": tot}


def describe(res, label=""):
    t = res["total"]
    lines = [f"{label}{t['peso_g']:.1f} g · {fmt_time(t['segundos'])} · suporte {t['suporte_g']:.1f} g"
             + (f" · torre {t['torre_g']:.1f} g" if t["torre_g"] else "")]
    for n, p in res["placas"].items():
        top = "  ".join(f"{a}={v:.1f}g" for a, v in list(p["por_tipo_g"].items())[:8] if v >= 0.3)
        lines.append(f"   {n}: {p['peso_g']:.1f} g · {p['tempo']} · {p['camadas']} camadas · {p['altura_mm']} mm | {top}")
        q = p.get("qualidade") or {}
        if q:
            lines.append(f"      qualidade: {q['trocas_de_cor']} trocas em {q['camadas_com_troca']} camadas · "
                         f"até {q['recolhimentos_max_camada']} recolhimentos e {q['trechos_minusculos_max_camada']} trechos curtos "
                         f"por camada · {q['pecas']} peças")
        lines += [f"      ⚠ {w}" for w in quality_notes(n, p)]
    return "\n".join(lines)


# ---------------------------------------------------------------- render
def render(d, out):
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        log("render: este Python não tem numpy/Pillow; use scripts/p1s-opt ou /usr/bin/python3")
        return None
    imgs = []
    for g in sorted(glob.glob(os.path.join(d, "plate_*.gcode"))):
        pts = {"m": [], "s": []}
        feat, x, y, z = "", 0.0, 0.0, 0.0
        num = re.compile(r"([XYE])(-?[\d.]+)")
        with open(g, errors="replace") as f:
            for line in f:
                if line.startswith("; FEATURE: "):
                    feat = line[11:].strip()
                elif line.startswith("; start printing object, unique label id: "):
                    objects.add(line.rsplit(":", 1)[1].strip())
                elif line.startswith("; Z_HEIGHT: "):
                    z = float(line[12:])
                elif line.startswith(("G1 ", "G2 ", "G3 ")):
                    e = None
                    for a, v in num.findall(line.split(";")[0]):
                        if a == "X":
                            x = float(v)
                        elif a == "Y":
                            y = float(v)
                        else:
                            e = float(v)
                    if e and e > 0 and feat not in ("Custom", "Prime tower"):
                        pts["s" if feat.startswith("Support") else "m"].append((x, y, z))
        m = np.array(pts["m"]) if pts["m"] else np.zeros((1, 3))
        s = np.array(pts["s"]) if pts["s"] else np.zeros((0, 3))
        sc, W = 3, 256 * 3
        H = int(max(m[:, 2].max(), 1) * sc) + 20
        panels = []
        for ax in (0, 1):
            im = np.full((H, W, 3), 255, np.uint8)
            for arr, col in ((m, (170, 170, 170)), (s, (220, 30, 30))):
                if len(arr):
                    u = (arr[:, ax] * sc).astype(int).clip(0, W - 1)
                    v = (H - 10 - arr[:, 2] * sc).astype(int).clip(0, H - 1)
                    im[v, u] = col
            panels.append(im)
        imgs.append(np.concatenate(panels, 1))
    if not imgs:
        return None
    w = max(i.shape[1] for i in imgs)
    full = np.concatenate([np.pad(i, ((0, 0), (0, w - i.shape[1]), (0, 0)), constant_values=255) for i in imgs], 0)
    Image.fromarray(full).save(out)
    return out


# ---------------------------------------------------------------- edição de projeto
def set_project(src, dst, kv):
    def patch(data):
        p = json.loads(data)
        for k, v in kv.items():
            old = p.get(k)
            p[k] = [str(v)] * len(old) if isinstance(old, list) and not isinstance(v, list) else v
        return json.dumps(p, indent=4, ensure_ascii=False).encode()
    rewrite_3mf(src, dst, {"Metadata/project_settings.config": patch})


def set_objects(src, dst, objs):
    """objs = {object_id: {chave: valor}} gravado em model_settings.config."""
    def patch(data):
        s = data.decode("utf-8")
        for oid, kv in objs.items():
            m = re.search(r'<object id="%s">\n' % re.escape(str(oid)), s)
            if not m:
                raise SystemExit(f"objeto {oid} não existe no model_settings.config")
            block_end = s.index("</object>", m.end())
            block = s[m.end():block_end]
            for k, v in kv.items():
                block = re.sub(r'\s*<metadata key="%s" value="[^"]*"/>' % re.escape(k), "", block)
            ins = "".join(f'    <metadata key="{k}" value="{v}"/>\n' for k, v in kv.items())
            s = s[:m.end()] + ins + block.lstrip("\n") + s[block_end:]
        return s.encode("utf-8")
    rewrite_3mf(src, dst, {"Metadata/model_settings.config": patch})


def strip_paint(src, dst, kinds=("paint_color",)):
    pat = re.compile(rb' (%s)="[^"]*"' % b"|".join(k.encode() for k in kinds))
    rewrite_3mf(src, dst, {n: (lambda data: pat.sub(b"", data)) for n in model_entries(src)})


def finalize(sliced, dst, profile=None):
    """Recalcula different_settings_to_system para o Bambu Studio mostrar o que mudou."""
    prof = load_profile(profile)
    diff_holder = {}

    def patch(data):
        p = json.loads(data)
        s = flat("process", p["print_settings_id"])
        for k, v in IMPLICIT_DEFAULTS.items():
            s.setdefault(k, v)

        def norm(v):
            v = v[0] if isinstance(v, list) and v else v
            v = str(v)
            try:
                return repr(float(v.rstrip("%"))) + ("%" if v.endswith("%") else "")
            except ValueError:
                return v
        diff = {k for k, v in s.items() if k not in META_KEYS and k in p and norm(p[k]) != norm(v)}
        diff |= {k for k in prof["overrides"] if k not in s and k in p}
        d = p.get("different_settings_to_system") or [""]
        d[0] = ";".join(sorted(diff))
        p["different_settings_to_system"] = d
        diff_holder["diff"] = sorted(diff)
        return json.dumps(p, indent=4, ensure_ascii=False).encode()
    rewrite_3mf(sliced, dst, {"Metadata/project_settings.config": patch})
    return diff_holder.get("diff", [])


# ---------------------------------------------------------------- fluxo automático
def plate_filament_usage(sliced_3mf):
    xml = read_entry(sliced_3mf, "Metadata/slice_info.config").decode("utf-8", "replace")
    plates = re.split(r"<plate>", xml)[1:]
    return [len(re.findall(r"<filament id=", p)) for p in plates]


def slice_variant(src, wdir, datadir, settings, filaments, need_tower):
    """Converte e fatia; se houver troca de cor, reativa a torre que a conversão desliga."""
    if not need_tower:
        out = run_bambu(src, wdir, datadir, settings, filaments)
        return out, wdir
    conv = run_bambu(src, os.path.join(wdir, "conv"), datadir, settings, filaments, slice_=False, export="conv.3mf")
    fixed = os.path.join(wdir, "conv", "tower.3mf")
    set_project(conv, fixed, {"enable_prime_tower": "1"})
    out = run_bambu(fixed, wdir, datadir)
    return out, wdir


MESH_EXTS = (".stl", ".obj", ".step", ".stp", ".amf")
# Linha de base para malhas soltas: o que a P1S faria com o perfil padrão do Bambu Studio.
MESH_BASE_PROCESS = "0.20mm Standard @BBL X1C"
MESH_BASE_SUPPORT = {"enable_support": "1", "support_type": "tree(auto)"}


def import_mesh(src, outdir, datadir, prof):
    """Monta um projeto 3MF da P1S a partir de STL/OBJ/STEP, na orientação do arquivo."""
    os.makedirs(outdir, exist_ok=True)
    m = write_preset("machine", prof["machine"], os.path.join(outdir, "machine.json"))
    p = write_preset("process", MESH_BASE_PROCESS, os.path.join(outdir, "process.json"), MESH_BASE_SUPPORT)
    f = write_preset("filament", prof["default_filament"], os.path.join(outdir, "filament.json"))
    out = run_bambu(src, outdir, datadir, [m, p], [f], slice_=False, export="import.3mf",
                    extra=("--arrange", "1", "--orient", "0"))
    if "can not be arranged inside plate" in open(os.path.join(outdir, "log.txt"), errors="replace").read():
        raise RuntimeError(f"{os.path.basename(src)} não cabe na mesa da P1S (área útil ~250 × 250 mm)")
    return out


def is_support_key(k):
    return k.startswith(("support_", "tree_support_")) or k == "enable_support"


def score(total, g_per_hour):
    """Custo comparável: gramas + suporte (de novo, pelo trabalho de remoção e marcas)
    + horas de máquina convertidas em gramas."""
    return total["peso_g"] + total["suporte_g"] + g_per_hour * total["segundos"] / 3600


def plan_variants(prof, info, names, support_mode):
    """Lista (nome, candidato, camada, extras) a fatiar."""
    support_off = support_mode == "off" or (support_mode == "auto" and str(info.get("enable_support")) == "0")
    extra = {"enable_support": "0"} if support_off else {}
    if support_off and all(all(is_support_key(k) for k in prof["support_candidates"][n]) for n in names):
        names = names[:1]  # sem suporte, candidatos que só mudam suporte dão o mesmo resultado
    layers = [None]
    try:
        orig = float(info.get("camada") or 0)
        mine = float(flat("process", prof["process"]).get("layer_height", 0))
        if orig > mine + 1e-6 and process_for_layer(prof["process"], orig):
            layers.append(f"{orig:.2f}")
    except (KeyError, ValueError):
        pass
    out = []
    for n in names:
        for lay in layers:
            label = ("sem-suporte" if support_off and len(names) == 1 else n) + (f"@{lay}" if lay else "")
            out.append((label, n, lay, extra))
    return out, support_off


def auto(args):
    prof = load_profile(args.profile)
    g_per_hour = args.g_por_hora if args.g_por_hora is not None else prof.get("gramas_por_hora", 10)
    user_extra = kv_list(args.set)
    if args.robusto:
        user_extra.update({"sparse_infill_pattern": "gyroid", "sparse_infill_density": "10%"})
    work = os.path.abspath(args.work)
    dest = os.path.abspath(args.dest)
    rep_dir = os.path.join(dest, "_relatorio")
    os.makedirs(rep_dir, exist_ok=True)
    datadir = os.path.join(work, "_datadir")
    os.makedirs(datadir, exist_ok=True)
    report = []
    for src in args.files:
        src = os.path.abspath(src)
        label_file = os.path.basename(src)
        name = os.path.splitext(label_file)[0]
        key = re.sub(r"[^\w.-]+", "_", name)
        log(f"\n=== {name}")
        notes = []
        w = os.path.join(work, key)
        shutil.rmtree(w, ignore_errors=True)
        if src.lower().endswith(MESH_EXTS):
            ext = os.path.splitext(src)[1].lstrip(".").upper()
            src = import_mesh(src, os.path.join(w, "import"), datadir, prof)
            notes.append(f"arquivo {ext} sem projeto: linha de base = {MESH_BASE_PROCESS} com suporte em árvore, "
                         "na orientação do arquivo. Se for peça articulada, refaça com --support off")
        info = inspect(src)
        info["enable_support"] = project_settings(src).get("enable_support")

        base = run_bambu(src, os.path.join(w, "base"), datadir)
        base_res = analyze_dir(os.path.join(w, "base"))
        log(describe(base_res, "base: "))
        multi = any(n > 1 for n in plate_filament_usage(base))
        if info["impressora"] != "Bambu Lab P1S":
            notes.append(f"projeto estava configurado para {info['impressora']}; convertido para P1S")

        fil = []
        for fname in info["filamentos"] or [prof["default_filament"]]:
            mapped, warn = map_filament(fname, prof["machine"], prof["default_filament"])
            if warn:
                notes.append(warn)
            fdir = os.path.join(work, "_presets")
            os.makedirs(fdir, exist_ok=True)
            fil.append(write_preset("filament", mapped, os.path.join(fdir, re.sub(r"[^\w.-]+", "_", mapped) + ".json")))

        names = args.candidates.split(",") if args.candidates else list(prof["support_candidates"])
        variants, support_off = plan_variants(prof, info, names, args.support)
        if support_off and args.support == "auto":
            notes.append("o original não usa suporte (talvez peça articulada/print-in-place); "
                         "suporte mantido desligado. Use --support on para testar com suporte")
        cands, spec = {}, {}
        for label, cand, lay, extra in variants:
            m, p = build_presets(prof, os.path.join(work, "_presets"), cand, {**extra, **user_extra}, layer=lay)
            out, d = slice_variant(src, os.path.join(w, re.sub(r"[^\w.-]+", "_", label)), datadir, [m, p], fil, multi)
            res = analyze_dir(d)
            res["warnings"] = log_warnings(d)
            res["custo"] = round(score(res["total"], g_per_hour), 1)
            cands[label] = (out, res)
            spec[label] = (cand, lay, extra)
            log(describe(res, f"{label}: ") + f"  [custo {res['custo']}]")
        best = min(cands, key=lambda c: cands[c][1]["custo"])
        out, res = cands[best]

        final = os.path.join(dest, name + ".3mf")
        diff = finalize(out, final, args.profile)
        ver_dir = os.path.join(w, "verify")
        run_bambu(final, ver_dir, datadir)
        ver = analyze_dir(ver_dir)
        ok = abs(ver["total"]["peso_g"] - res["total"]["peso_g"]) <= max(0.5, 0.01 * res["total"]["peso_g"])
        if not ok:
            notes.append(f"verificação divergiu: {ver['total']['peso_g']} g vs {res['total']['peso_g']} g")
        img = render(os.path.dirname(out), os.path.join(rep_dir, f"{key}-suportes.png")) if not args.no_render else None

        for pn, p in res["placas"].items():
            if p["altura_mm"] and p["altura_mm"] < 25 and p["suporte_g"] < 1:
                notes.append(f"{pn} tem só {p['altura_mm']} mm: considere 0,20 mm por objeto (objset) para ganhar tempo")
        if multi:
            notes.append(f"troca de cor: torre de purga {res['total']['torre_g']:.1f} g; avalie a versão de 1 cor")
        for pn, p in res["placas"].items():
            notes += quality_notes(pn, p)
        bt, at = base_res["total"]["segundos"], res["total"]["segundos"]
        if bt and at > 1.10 * bt:
            notes.append(f"tempo subiu {100 * (at - bt) / bt:.0f}% ({fmt_time(bt)} → {fmt_time(at)}); "
                         f"escolha feita com {g_per_hour:g} g por hora de máquina (--g-por-hora)")

        entry = {"arquivo": label_file, "info": info, "base": base_res, "escolhido": best,
                 "otimizado": res, "gramas_por_hora": g_per_hour,
                 "candidatos": {c: {**r[1]["total"], "custo": r[1]["custo"]} for c, r in cands.items()},
                 "ajustes_alterados": diff, "verificado": ok, "render": img, "notas": notes}
        report.append(entry)

        if args.mono and info["pintura"]["paint_color"]:
            mono_src = os.path.join(w, "mono_src.3mf")
            strip_paint(src, mono_src)
            cand, lay, extra = spec[best]
            m, p = build_presets(prof, os.path.join(work, "_presets"), cand, {**extra, **user_extra}, layer=lay)
            mout = run_bambu(mono_src, os.path.join(w, "mono"), datadir, [m, p], fil)
            mres = analyze_dir(os.path.join(w, "mono"))
            mfinal = os.path.join(dest, f"{name} (1 cor).3mf")
            finalize(mout, mfinal, args.profile)
            entry["mono"] = mres["total"]
            log(describe(mres, "1 cor: "))

    with open(os.path.join(rep_dir, "relatorio.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    md = write_markdown(report)
    with open(os.path.join(rep_dir, "relatorio.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md)


def write_markdown(report):
    L = ["# Otimização para Bambu Lab P1S", "",
         "| Peça | Antes | Depois | Suporte | Escolha | Verificado |", "|---|---|---|---|---|---|"]
    tb = ta = sb = sa = 0
    for e in report:
        b, a = e["base"]["total"], e["otimizado"]["total"]
        tb += b["peso_g"]; ta += a["peso_g"]; sb += b["segundos"]; sa += a["segundos"]
        L.append(f"| {e['arquivo']} | {b['peso_g']:.1f} g · {fmt_time(b['segundos'])} | {a['peso_g']:.1f} g · {fmt_time(a['segundos'])} "
                 f"| {b['suporte_g']:.1f} → {a['suporte_g']:.1f} g | {e['escolhido']} | {'sim' if e['verificado'] else 'NÃO'} |")
    if tb:
        L.append(f"| **Total** | **{tb:.0f} g · {fmt_time(sb)}** | **{ta:.0f} g · {fmt_time(sa)}** | | | |")
        L += ["", f"Filamento {100 * (ta - tb) / tb:+.0f}% · tempo {100 * (sa - sb) / max(sb, 1):+.0f}%"]
    for e in report:
        L += ["", f"**{e['arquivo']}** — variantes (custo = g + suporte + {e['gramas_por_hora']:g} g/h):", "",
              "| Variante | Peso | Tempo | Suporte | Custo |", "|---|---|---|---|---|"]
        for c, t in sorted(e["candidatos"].items(), key=lambda x: x[1]["custo"]):
            mark = " ✓" if c == e["escolhido"] else ""
            L.append(f"| {c}{mark} | {t['peso_g']:.1f} g | {fmt_time(t['segundos'])} | {t['suporte_g']:.1f} g | {t['custo']:.1f} |")
    for e in report:
        extra = e["notas"] + ([f"versão 1 cor: {e['mono']['peso_g']:.1f} g · {fmt_time(e['mono']['segundos'])}"] if e.get("mono") else [])
        if extra:
            L += ["", f"**{e['arquivo']}**"] + [f"- {n}" for n in extra]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- main
def kv_list(items):
    out = {}
    for it in items:
        k, _, v = it.partition("=")
        out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    a = sp.add_parser("inspect"); a.add_argument("files", nargs="+")
    a = sp.add_parser("presets"); a.add_argument("--out", required=True); a.add_argument("--profile")
    a.add_argument("--candidate"); a.add_argument("--set", nargs="*", default=[])
    a = sp.add_parser("slice"); a.add_argument("src"); a.add_argument("--out", required=True)
    a.add_argument("--profile"); a.add_argument("--candidate", default="org25")
    a.add_argument("--filament", action="append", help="perfil oficial de filamento (repetir por slot)")
    a.add_argument("--raw", action="store_true", help="fatiar como está, sem converter")
    a.add_argument("--tower", action="store_true", help="reativar a torre de purga após a conversão")
    a.add_argument("--set", nargs="*", default=[]); a.add_argument("--datadir")
    a = sp.add_parser("analyze"); a.add_argument("dirs", nargs="+"); a.add_argument("--json", action="store_true")
    a = sp.add_parser("render"); a.add_argument("dir"); a.add_argument("--out", required=True)
    a = sp.add_parser("objset"); a.add_argument("src"); a.add_argument("dst")
    a.add_argument("--object", action="append", nargs="+", metavar=("ID", "CHAVE=VALOR"), required=True)
    a = sp.add_parser("setproj"); a.add_argument("src"); a.add_argument("dst"); a.add_argument("kv", nargs="+")
    a = sp.add_parser("strip-paint"); a.add_argument("src"); a.add_argument("dst")
    a.add_argument("--kind", action="append", choices=["paint_color", "paint_supports", "paint_seam"])
    a = sp.add_parser("finalize"); a.add_argument("sliced"); a.add_argument("dst"); a.add_argument("--profile")
    a = sp.add_parser("auto"); a.add_argument("files", nargs="+"); a.add_argument("--dest", required=True)
    a.add_argument("--work", required=True); a.add_argument("--profile"); a.add_argument("--candidates")
    a.add_argument("--mono", action="store_true", help="gerar também versão de 1 cor quando houver pintura de cor")
    a.add_argument("--no-render", action="store_true")
    a.add_argument("--support", choices=["auto", "on", "off"], default="auto",
                   help="auto: desliga se o original não usa suporte (padrão)")
    a.add_argument("--g-por-hora", type=float, help="gramas que 1 h de máquina vale na escolha (padrão 10)")
    a.add_argument("--robusto", action="store_true", help="gyroid 10%% em vez de lightning (peças que caem/apanham)")
    a.add_argument("--set", nargs="*", default=[], help="chave=valor aplicados a todas as variantes")
    args = ap.parse_args()

    if args.cmd == "inspect":
        for f in args.files:
            print(json.dumps(inspect(f), indent=1, ensure_ascii=False))
    elif args.cmd == "presets":
        prof = load_profile(args.profile)
        print("\n".join(build_presets(prof, args.out, args.candidate, kv_list(args.set))))
    elif args.cmd == "slice":
        args.out = os.path.abspath(args.out)   # a CLI do Bambu roda em outro diretório e não acharia presets relativos
        datadir = args.datadir or os.path.join(os.path.abspath(args.out), "_datadir")
        os.makedirs(datadir, exist_ok=True)
        if args.raw:
            run_bambu(args.src, args.out, datadir)
        else:
            prof = load_profile(args.profile)
            m, p = build_presets(prof, os.path.join(args.out, "_presets"), args.candidate, kv_list(args.set))
            fil = []
            names = args.filament or project_settings(args.src).get("filament_settings_id") or [prof["default_filament"]]
            for n in names:
                mapped, warn = map_filament(n, prof["machine"], prof["default_filament"])
                if warn:
                    log("aviso:", warn)
                fil.append(write_preset("filament", mapped, os.path.join(args.out, "_presets", f"fil{len(fil)}.json")))
            slice_variant(args.src, args.out, datadir, [m, p], fil, args.tower)
        for w in log_warnings(args.out):
            log("log:", w)
        print(describe(analyze_dir(args.out)))
    elif args.cmd == "analyze":
        for d in args.dirs:
            r = analyze_dir(d)
            print(json.dumps(r, indent=1, ensure_ascii=False) if args.json else describe(r, f"{d}: "))
    elif args.cmd == "render":
        print(render(args.dir, args.out))
    elif args.cmd == "objset":
        set_objects(args.src, args.dst, {o[0]: kv_list(o[1:]) for o in args.object})
    elif args.cmd == "setproj":
        set_project(args.src, args.dst, kv_list(args.kv))
    elif args.cmd == "strip-paint":
        strip_paint(args.src, args.dst, tuple(args.kind or ["paint_color"]))
    elif args.cmd == "finalize":
        diff = finalize(args.sliced, args.dst, args.profile)
        print(f"gravado {args.dst}\najustes marcados como alterados ({len(diff)}): {', '.join(diff)}")
    elif args.cmd == "auto":
        auto(args)


if __name__ == "__main__":
    main()
