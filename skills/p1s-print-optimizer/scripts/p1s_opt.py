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
  auto      fluxo completo: base, candidatos de suporte, escolha, verificação e relatório

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


def load_profile(path):
    with open(path or DEFAULT_PROFILE, encoding="utf-8") as f:
        return json.load(f)


def build_presets(profile, outdir, candidate=None, extra=None):
    os.makedirs(outdir, exist_ok=True)
    ov = dict(profile["overrides"])
    if candidate:
        ov.update(profile["support_candidates"][candidate])
    ov.update(extra or {})
    m = write_preset("machine", profile["machine"], os.path.join(outdir, "machine.json"))
    p = write_preset("process", profile["process"], os.path.join(outdir, f"process_{candidate or 'base'}.json"), ov)
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
def run_bambu(src, outdir, datadir, settings=None, filaments=None, slice_=True, export="out.3mf"):
    os.makedirs(outdir, exist_ok=True)
    cmd = [BAMBU, "--datadir", datadir, "--debug", "2"]
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


def analyze_gcode(path):
    feat, rel, last, maxz = "?", True, 0.0, 0.0
    ext, hdr = {}, {}
    density, diam = [1.24], 1.75
    with open(path, errors="replace") as f:
        for line in f:
            c = line[0]
            if c == ";":
                if line.startswith("; FEATURE: "):
                    feat = line[11:].strip()
                elif line.startswith("; Z_HEIGHT: "):
                    maxz = max(maxz, float(line[12:]))
                elif line.startswith("; filament_density"):
                    density = [float(x) for x in re.split(r"[,;]", re.split(r"[:=]", line, maxsplit=1)[1]) if x.strip()]
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
                if line.startswith("M83"):
                    rel = True
                elif line.startswith("M82"):
                    rel = False
            elif c == "G":
                if line.startswith(("G1 ", "G2 ", "G3 ")):
                    m = NUM.search(line)
                    if m:
                        e = float(m.group(1))
                        if not rel:
                            e, last = e - last, e
                        if e > 0:
                            ext[feat] = ext.get(feat, 0.0) + e
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
    }


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


def auto(args):
    prof = load_profile(args.profile)
    work = os.path.abspath(args.work)
    dest = os.path.abspath(args.dest)
    rep_dir = os.path.join(dest, "_relatorio")
    os.makedirs(rep_dir, exist_ok=True)
    datadir = os.path.join(work, "_datadir")
    os.makedirs(datadir, exist_ok=True)
    report = []
    for src in args.files:
        src = os.path.abspath(src)
        name = os.path.splitext(os.path.basename(src))[0]
        key = re.sub(r"[^\w.-]+", "_", name)
        log(f"\n=== {name}")
        info = inspect(src)
        notes = []
        w = os.path.join(work, key)
        shutil.rmtree(w, ignore_errors=True)

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

        cands = {}
        names = args.candidates.split(",") if args.candidates else list(prof["support_candidates"])
        for cand in names:
            m, p = build_presets(prof, os.path.join(work, "_presets"), cand)
            out, d = slice_variant(src, os.path.join(w, cand), datadir, [m, p], fil, multi)
            res = analyze_dir(d)
            res["warnings"] = log_warnings(d)
            cands[cand] = (out, res)
            log(describe(res, f"{cand}: "))
        best = min(cands, key=lambda c: (cands[c][1]["total"]["suporte_g"], cands[c][1]["total"]["peso_g"]))
        out, res = cands[best]

        final = os.path.join(dest, os.path.basename(src))
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

        entry = {"arquivo": os.path.basename(src), "info": info, "base": base_res, "escolhido": best,
                 "otimizado": res, "candidatos": {c: r[1]["total"] for c, r in cands.items()},
                 "ajustes_alterados": diff, "verificado": ok, "render": img, "notas": notes}
        report.append(entry)

        if args.mono and info["pintura"]["paint_color"]:
            mono_src = os.path.join(w, "mono_src.3mf")
            strip_paint(src, mono_src)
            m, p = build_presets(prof, os.path.join(work, "_presets"), best)
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
    args = ap.parse_args()

    if args.cmd == "inspect":
        for f in args.files:
            print(json.dumps(inspect(f), indent=1, ensure_ascii=False))
    elif args.cmd == "presets":
        prof = load_profile(args.profile)
        print("\n".join(build_presets(prof, args.out, args.candidate, kv_list(args.set))))
    elif args.cmd == "slice":
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
        print(";".join(finalize(args.sliced, args.dst, args.profile)))
    elif args.cmd == "auto":
        auto(args)


if __name__ == "__main__":
    main()
