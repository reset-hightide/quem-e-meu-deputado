#!/usr/bin/env python3
"""Atualiza deputados.json com os indicadores dos deputados federais (Câmara dos Deputados).

Fonte: Dados Abertos da Câmara (https://dadosabertos.camara.leg.br). Sem dependências externas.
Uso:   python atualizar.py                  # legislatura inteira (2023 até o ano atual)
       python atualizar.py --anos 2025      # só alguns anos (testes)
Sai com código != 0 se algo estiver errado (o workflow usa isso para avisar).
"""
import argparse, bisect, csv, datetime as dt, json, os, statistics, sys, tempfile, time, urllib.request, urllib.error

API = "https://dadosabertos.camara.leg.br/api/v2"
ARQ = "https://dadosabertos.camara.leg.br/arquivos"
LEGISLATURA = 57                      # 2023-2027
INICIO_LEGISLATURA = 2023
TIPOS = {"PL", "PLP", "PEC", "PDL"}   # proposições que viram norma (exclui requerimentos, emendas etc.)

SIT_LEI = {"Transformado em Norma Jurídica"}
SIT_APROVADA_CAMARA = {                # já aprovadas na Câmara e a caminho de virar lei
    "Aguardando Apreciação pelo Senado Federal", "Aguardando Sanção", "Aguardando Envio ao Senado Federal",
    "Aguardando Autógrafos na Mesa", "Aguardando Redação Final", "Aguardando Envio à Redação Final",
}
SIT_ENCERRADA = {"Arquivada", "Retirado pelo(a) Autor(a)", "Devolvida ao(à) Autor(a)"}

csv.field_size_limit(10 ** 9)
AQUI = os.path.dirname(os.path.abspath(__file__))


def log(*a):
    print(*a, flush=True)


def baixar(url, destino, tentativas=5):
    for n in range(1, tentativas + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "monitor-deputados/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r, open(destino, "wb") as f:
                while True:
                    bloco = r.read(1 << 20)
                    if not bloco:
                        break
                    f.write(bloco)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            err = e
        except Exception as e:  # rede instável
            err = e
        log("  tentativa %d/%d falhou: %s" % (n, tentativas, err))
        time.sleep(5 * n)
    raise RuntimeError("não consegui baixar " + url)


def api_json(url):
    for n in range(1, 6):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "monitor-deputados/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:
            log("  API tentativa %d falhou: %s" % (n, e))
            time.sleep(4 * n)
    raise RuntimeError("API sem resposta: " + url)


def linhas(caminho):
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f, delimiter=";")


def roster():
    """Deputados em exercício hoje (titulares)."""
    out, url = {}, "%s/deputados?itens=100&ordem=ASC&ordenarPor=nome" % API
    while url:
        j = api_json(url)
        for d in j["dados"]:
            out[str(d["id"])] = {"id": d["id"], "nome": d["nome"], "partido": d["siglaPartido"], "uf": d["siglaUf"],
                                  "foto": d.get("urlFoto", "")}
        url = next((l["href"] for l in j.get("links", []) if l["rel"] == "next"), None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anos", nargs="*", type=int)
    ap.add_argument("--saida", default=os.path.join(AQUI, "deputados.json"))
    a = ap.parse_args()
    hoje = dt.date.today()
    anos = a.anos or list(range(INICIO_LEGISLATURA, min(hoje.year, 2026) + 1))
    espectro = json.load(open(os.path.join(AQUI, "espectro.json"), encoding="utf-8"))
    mapa = espectro["partidos"]

    log("Roster...")
    ros = roster()
    log("  %d deputados em exercício" % len(ros))
    tmp = tempfile.mkdtemp(prefix="camara_")

    # --- sessões deliberativas do plenário (para faltas) e votações nominais
    sess_data = {}                       # idEvento -> data
    presenca = {}                        # idDep -> set(idEvento)
    datas_dep = {}                       # idDep -> [min, max] (datas ISO)
    votos_dep = {}                       # idDep -> set(idVotacao)
    votacao_data = {}                    # idVotacao -> data
    props = {}                           # idProposicao -> (tipo, situacao)
    proj = {}                            # idDep -> {tipo/status contadores}

    def marca(dep, data):
        r = datas_dep.setdefault(dep, [data, data])
        if data < r[0]: r[0] = data
        if data > r[1]: r[1] = data

    for ano in anos:
        log("== %d" % ano)
        def pega(nome, subdir, obrigatorio=True):
            destino = os.path.join(tmp, "%s-%d.csv" % (nome, ano))
            ok = baixar("%s/%s/csv/%s-%d.csv" % (ARQ, subdir, nome, ano), destino)
            if not ok and obrigatorio and ano < hoje.year:
                raise RuntimeError("arquivo ausente: %s %d" % (nome, ano))
            return destino if ok else None

        f = pega("eventos", "eventos", True)
        delib = set()
        if f:
            for r in linhas(f):
                if r["descricaoTipo"] == "Sessão Deliberativa" and r["situacao"] != "Cancelada":
                    delib.add(r["id"]); sess_data[r["id"]] = r["dataHoraInicio"][:10]
        f = pega("eventosPresencaDeputados", "eventosPresencaDeputados", True)
        if f:
            for r in linhas(f):
                if r["idEvento"] in delib:
                    presenca.setdefault(r["idDeputado"], set()).add(r["idEvento"])
                    marca(r["idDeputado"], r["dataHoraInicio"][:10])
        f = pega("votacoesVotos", "votacoesVotos", True)
        if f:
            for r in linhas(f):
                d = r["dataHoraVoto"][:10]
                votos_dep.setdefault(r["deputado_id"], set()).add(r["idVotacao"])
                votacao_data.setdefault(r["idVotacao"], d)
                marca(r["deputado_id"], d)
        f = pega("proposicoes", "proposicoes", True)
        if f:
            for r in linhas(f):
                if r["siglaTipo"] in TIPOS:
                    props[r["id"]] = (r["siglaTipo"], r["ultimoStatus_descricaoSituacao"].strip())
        f = pega("proposicoesAutores", "proposicoesAutores", True)
        if f:
            for r in linhas(f):
                if r["idDeputadoAutor"] and r["proponente"] == "1" and r["idProposicao"] in props:
                    p = proj.setdefault(r["idDeputadoAutor"], {"total": 0, "lei": 0, "aprovada_camara": 0, "encerrada": 0, "PL": 0, "PLP": 0, "PEC": 0, "PDL": 0})
                    tipo, sit = props[r["idProposicao"]]
                    p["total"] += 1; p[tipo] += 1
                    if sit in SIT_LEI: p["lei"] += 1
                    elif sit in SIT_APROVADA_CAMARA: p["aprovada_camara"] += 1
                    elif sit in SIT_ENCERRADA: p["encerrada"] += 1
        for fn in os.listdir(tmp):
            os.remove(os.path.join(tmp, fn))

    # --- cálculo por deputado
    com_presenca = set().union(*presenca.values()) if presenca else set()
    datas_sess = sorted(sess_data[e] for e in sess_data if e in com_presenca)
    datas_vot = sorted(votacao_data.values())
    fim = max(datas_sess) if datas_sess else hoje.isoformat()
    out, sem_dados = [], 0
    for id_, d in ros.items():
        reg = datas_dep.get(id_)
        part = d["partido"]
        esp = mapa.get(part, "centro")
        item = dict(d, espectro=esp)
        if reg:
            ini = reg[0]
            n_sess = bisect.bisect_right(datas_sess, fim) - bisect.bisect_left(datas_sess, ini)
            pres = len(presenca.get(id_, ()))
            n_vot = bisect.bisect_right(datas_vot, fim) - bisect.bisect_left(datas_vot, ini)
            vot = len(votos_dep.get(id_, ()))
            item.update(sessoes=n_sess, presencas=min(pres, n_sess), faltas=max(n_sess - pres, 0),
                        presenca_pct=round(100 * min(pres, n_sess) / n_sess, 1) if n_sess else None,
                        votacoes=n_vot, votou=min(vot, n_vot),
                        votou_pct=round(100 * min(vot, n_vot) / n_vot, 1) if n_vot else None,
                        desde=ini)
        else:
            sem_dados += 1
            item.update(sessoes=0, presencas=0, faltas=0, presenca_pct=None, votacoes=0, votou=0, votou_pct=None, desde=None)
        p = proj.get(id_, {"total": 0, "lei": 0, "aprovada_camara": 0, "encerrada": 0, "PL": 0, "PLP": 0, "PEC": 0, "PDL": 0})
        aprov = p["lei"] + p["aprovada_camara"]
        item.update(projetos=p["total"], leis=p["lei"], aprovados_camara=p["aprovada_camara"], aprovados=aprov,
                    encerrados=p["encerrada"], tramitando=p["total"] - aprov - p["encerrada"],
                    pl=p["PL"], plp=p["PLP"], pec=p["PEC"], pdl=p["PDL"],
                    aprovados_pct=round(100 * aprov / p["total"], 1) if p["total"] else None,
                    leis_pct=round(100 * p["lei"] / p["total"], 1) if p["total"] else None)
        out.append(item)
    out.sort(key=lambda x: x["nome"])

    # --- validações: se algo estiver estranho, falha (o workflow avisa)
    erros = []
    if len(out) < 450: erros.append("poucos deputados no roster: %d" % len(out))
    if sem_dados > 0.1 * len(out): erros.append("deputados sem presença/votos: %d" % sem_dados)
    if sum(x["projetos"] for x in out) < 3000: erros.append("poucos projetos: %d" % sum(x["projetos"] for x in out))
    if len(datas_sess) < 100: erros.append("poucas sessões deliberativas: %d" % len(datas_sess))
    if len(datas_vot) < 100: erros.append("poucas votações nominais: %d" % len(datas_vot))
    if erros:
        log("VALIDAÇÃO FALHOU:\n - " + "\n - ".join(erros))
        sys.exit(2)

    def med(lst):
        v = [x for x in lst if x is not None]
        return round(statistics.median(v), 1) if v else None
    grupos = {}
    for g in ("esquerda", "centro", "direita"):
        s = [x for x in out if x["espectro"] == g]
        grupos[g] = {"deputados": len(s), "projetos_total": sum(x["projetos"] for x in s),
                     "projetos_mediana": med([x["projetos"] for x in s]), "presenca_mediana": med([x["presenca_pct"] for x in s]),
                     "aprovados_total": sum(x["aprovados"] for x in s), "leis_total": sum(x["leis"] for x in s),
                     "votou_mediana": med([x["votou_pct"] for x in s])}
    meta = {"atualizado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "dados_ate": fim, "anos": anos, "legislatura": LEGISLATURA,
            "sessoes_deliberativas": len(datas_sess), "votacoes_nominais": len(datas_vot),
            "fonte": "Dados Abertos da Câmara dos Deputados", "espectro_nota": espectro.get("nota", ""),
            "grupos": grupos, "total_deputados": len(out)}
    with open(a.saida, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "deputados": out}, fh, ensure_ascii=False, separators=(",", ":"))
    log("OK: %d deputados, %d sessões, %d votações, %d projetos -> %s" % (len(out), len(datas_sess), len(datas_vot), sum(x["projetos"] for x in out), a.saida))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log("ERRO:", repr(e))
        sys.exit(1)
