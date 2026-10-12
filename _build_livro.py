# -*- coding: utf-8 -*-
"""Build livro-do-jogador.md + styles from index.html."""
from __future__ import annotations

import ast
import html as htmlmod
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "livro-do-jogador"
STYLES = OUT / "styles"
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = htmlmod.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


def extract_section(html: str, sid: str) -> str:
    m = re.search(rf'<section id="{sid}"[^>]*>', html)
    if not m:
        raise SystemExit(f"missing section {sid}")
    start = m.start()
    i = m.end()
    depth = 1
    while i < len(html) and depth:
        ns = html.find("<section", i)
        ne = html.find("</section>", i)
        if ne < 0:
            break
        if ns >= 0 and ns < ne:
            depth += 1
            i = ns + 8
        else:
            depth -= 1
            if depth == 0:
                return html[start : ne + 10]
            i = ne + 10
    raise SystemExit(f"unclosed section {sid}")


def table_md(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    # normalize cols
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    # escape pipes
    rows = [[c.replace("|", "\\|").replace("\n", " ") for c in r] for r in rows]
    head = rows[0]
    body = rows[1:] if len(rows) > 1 else []
    lines = [
        "| " + " | ".join(head) + " |",
        "| " + " | ".join("---" for _ in head) + " |",
    ]
    for r in body:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def tables_from(section: str) -> list[list[list[str]]]:
    out = []
    for t in re.findall(r"<table[^>]*>(.*?)</table>", section, re.S | re.I):
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S | re.I):
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S | re.I)
            rows.append([strip_tags(c).replace("\n", " ") for c in cells])
        if rows:
            out.append(rows)
    return out


def load_perk_descriptions() -> dict[str, str]:
    m = re.search(r"const PERK_DESCRIPTIONS\s*=\s*(\{[\s\S]*?\});", HTML)
    if not m:
        return {}
    # JS object with JSON-like strings — use JSON after fixing
    raw = m.group(1)
    try:
        import json

        return json.loads(raw)
    except Exception:
        return ast.literal_eval(raw)


class _El:
    __slots__ = ("tag", "attrs", "children", "text")

    def __init__(self) -> None:
        self.tag: str | None = None
        self.attrs: dict[str, str] = {}
        self.children: list[_El] = []
        self.text = ""

    def has_class(self, c: str) -> bool:
        return c in self.attrs.get("class", "").split()

    def direct(self, classname: str) -> list[_El]:
        return [c for c in self.children if c.tag == "div" and c.has_class(classname)]

    def find_all(self, pred) -> list[_El]:
        out: list[_El] = []
        for ch in self.children:
            if pred(ch):
                out.append(ch)
            out.extend(ch.find_all(pred))
        return out


class _DomBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.root = _El()
        self.root.tag = "root"
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        n = _El()
        n.tag = tag
        n.attrs = dict(attrs)
        self.stack[-1].children.append(n)
        if tag not in ("br", "img", "hr", "input", "meta", "link"):
            self.stack.append(n)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                break

    def handle_data(self, data):
        self.stack[-1].text += data


def _sn_field(el: _El, cls: str) -> str:
    for c in el.children:
        if c.has_class(cls):
            return strip_tags(c.text + "".join(x.text for x in c.children))
    return ""


def _parse_html_fragment(frag: str) -> _El:
    b = _DomBuilder()
    b.feed(frag)
    return b.root


def _skill_from_el(el: _El, descs: dict[str, str]) -> dict:
    name = _sn_field(el, "sn-name")
    return {
        "name": name,
        "cost": _sn_field(el, "sn-cost"),
        "req": _sn_field(el, "sn-req"),
        "detail": _sn_field(el, "node-detail"),
        "long": descs.get(name, ""),
        "children": [],
    }


def _attach_child(parent: dict, child) -> None:
    if not child or not parent:
        return
    if isinstance(child, list):
        parent["children"].extend(child)
    else:
        parent["children"].append(child)


def _parse_sub(sub_el: _El, descs: dict[str, str]):
    rows = sub_el.direct("tree-row")
    row = rows[0] if rows else None
    if not row:
        for c in sub_el.children:
            if c.has_class("tree-row"):
                row = c
                break
    if not row:
        return None
    node_els = [c for c in row.children if c.has_class("skill-node")]
    nested = sub_el.direct("tree-sub")
    if len(nested) == len(node_els) and len(node_els) > 1:
        out = []
        for i, el in enumerate(node_els):
            n = _skill_from_el(el, descs)
            child = _parse_sub(nested[i], descs)
            _attach_child(n, child)
            out.append(n)
        return out
    return _build_chain(node_els, nested, "nested", descs)


def _build_chain(node_els: list[_El], sub_els: list[_El], mode: str, descs: dict[str, str]):
    if not node_els:
        return None
    nodes = [_skill_from_el(el, descs) for el in node_els]
    if mode == "top":
        rootn = nodes[0]
        for i in range(1, len(nodes)):
            if i - 1 < len(sub_els):
                _attach_child(nodes[i], _parse_sub(sub_els[i - 1], descs))
            rootn["children"].append(nodes[i])
        for i in range(len(nodes) - 1, len(sub_els)):
            _attach_child(nodes[-1] if nodes else rootn, _parse_sub(sub_els[i], descs))
        return rootn
    for i, sub in enumerate(sub_els):
        idx = len(nodes) - len(sub_els) + i
        if 0 <= idx < len(nodes):
            _attach_child(nodes[idx], _parse_sub(sub, descs))
    for i in range(len(nodes) - 2, -1, -1):
        nodes[i]["children"].append(nodes[i + 1])
    return nodes[0]


def _branch_tree_from_html(branch_html: str, descs: dict[str, str]) -> dict | None:
    root = _parse_html_fragment(branch_html)
    found = root.find_all(lambda n: n.has_class("tree-branch"))
    branch_el = found[0] if found else root
    rows = branch_el.direct("tree-row")
    if not rows:
        return None
    main_nodes = [c for c in rows[0].children if c.has_class("skill-node")]
    top_subs = branch_el.direct("tree-sub")
    return _build_chain(main_nodes, top_subs, "top", descs)


def _flatten_nodes(node: dict) -> list[dict]:
    out = [
        {
            "name": node["name"],
            "cost": node["cost"],
            "req": node["req"],
            "detail": node["detail"],
            "long": node["long"],
        }
    ]
    for c in node.get("children") or []:
        out.extend(_flatten_nodes(c))
    return out


def _render_tree_print(node: dict, is_root: bool = True) -> str:
    """HTML árvore legível no PDF (forks como irmãos)."""
    meta_bits = []
    if node.get("cost"):
        meta_bits.append(node["cost"])
    if node.get("req"):
        meta_bits.append(node["req"])
    meta = " · ".join(meta_bits)
    detail = node.get("detail") or ""
    kids = node.get("children") or []
    cls = "stp-node stp-root" if is_root else "stp-node"
    parts = [f'<div class="{cls}">']
    parts.append(f'<div class="stp-name">{node["name"]}</div>')
    if meta:
        parts.append(f'<div class="stp-meta">{meta}</div>')
    if detail:
        parts.append(f'<div class="stp-detail">{detail}</div>')
    parts.append("</div>")
    if kids:
        parts.append('<div class="stp-children">')
        for c in kids:
            parts.append('<div class="stp-branch">')
            parts.append(_render_tree_print(c, False))
            parts.append("</div>")
        parts.append("</div>")
    return "".join(parts)


def parse_domains(disc: str, descs: dict[str, str]) -> list[dict]:
    domains = []
    parts = re.split(r'<div class="discipline-card[^"]*"[^>]*>', disc)[1:]
    for part in parts:
        name_m = re.search(r'class="discipline-name"[^>]*>(.*?)</', part, re.S | re.I)
        desc_m = re.search(r'class="discipline-desc"[^>]*>(.*?)</p>', part, re.S | re.I)
        attrs = [
            strip_tags(a)
            for a in re.findall(r'class="attr-tag[^"]*"[^>]*>(.*?)</span>', part, re.S | re.I)
        ]
        header = part.split('class="skill-tree-visual"', 1)[0]
        pillars = [
            strip_tags(p)
            for p in re.findall(r'class="pillar-tag[^"]*"[^>]*>(.*?)</span>', header, re.S | re.I)
        ]
        branches = []
        for bm in re.finditer(
            r'(<div class="tree-branch"[^>]*>[\s\S]*?<h4 class="branch-name"[^>]*>(.*?)</h4>[\s\S]*?)(?=<div class="tree-branch"|$)',
            part,
            re.I,
        ):
            btitle = strip_tags(bm.group(2))
            btitle = re.sub(r"\s+", " ", btitle).strip()
            bpillar_m = re.search(r"branch-pillar[^>]*>(.*?)</", bm.group(0), re.I)
            bpillar = strip_tags(bpillar_m.group(1)) if bpillar_m else ""
            if bpillar and btitle.endswith(bpillar):
                btitle = btitle[: -len(bpillar)].strip()
            tree = _branch_tree_from_html(bm.group(1), descs)
            nodes = _flatten_nodes(tree) if tree else []
            branches.append(
                {"name": btitle, "pillar": bpillar, "tree": tree, "nodes": nodes}
            )
        domains.append(
            {
                "name": strip_tags(name_m.group(1)) if name_m else "?",
                "desc": strip_tags(desc_m.group(1)) if desc_m else "",
                "attrs": attrs,
                "pillars": pillars,
                "branches": branches,
            }
        )
    return domains


def md_table_from_section_nth(section: str, n: int = 0) -> str:
    tables = tables_from(section)
    if n >= len(tables):
        return ""
    return table_md(tables[n])


def callout(kind: str, text: str) -> str:
    return f'\n<div class="{kind}">\n\n{text}\n\n</div>\n'


def build_domains_md(domains: list[dict]) -> str:
    parts = []
    parts.append(
        """# CAPÍTULO 3: OS 8 DOMÍNIOS · PERÍCIAS VIVAS

Os domínios substituem as perícias tradicionais de mesa: combate, ofício, arte, estudo, viagem e palavra — não só agressão.

**Pré-requisito:** Raiz + nó anterior no caminho. O **REQ** de cada nó lista o superior (ex.: `REQ Lâmina · DES 5`) e, se houver, atributos.
**Forks** são caminhos paralelos: pegar um não impede pegar outro depois — basta seguir a ordem de cada linha (cada nó custa **1 PD**).

Cada domínio abaixo lista seus ramos (caminhos). O primeiro nó de cada ramo é a **Raiz**. A árvore mostra forks como ramos irmãos.
"""
    )
    for d in domains:
        parts.append(f"\n## {d['name']}\n")
        if d["pillars"]:
            parts.append("**Pilares:** " + ", ".join(d["pillars"]) + "\n")
        if d["attrs"]:
            parts.append("**Atributos:** " + ", ".join(d["attrs"]) + "\n")
        if d["desc"]:
            parts.append(f"\n{d['desc']}\n")
        for b in d["branches"]:
            title = b["name"]
            if b["pillar"]:
                title = f"{title} ({b['pillar']})"
            parts.append(f"\n### {title}\n")
            if b.get("tree"):
                parts.append(
                    '\n<div class="skill-tree-print">\n'
                    + _render_tree_print(b["tree"])
                    + "\n</div>\n"
                )
            elif not b["nodes"]:
                continue
            for n in b["nodes"]:
                if n["long"]:
                    parts.append(f"\n**{n['name']}.** {n['long']}\n")
    return "\n".join(parts)


def parse_conditions(section: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(
        r'class="condition-name"[^>]*>(.*?)</h3>\s*<p>(.*?)</p>',
        section,
        re.S | re.I,
    ):
        out.append((strip_tags(m.group(1)), strip_tags(m.group(2))))
    return out


def parse_builds(section: str) -> list[dict]:
    out = []
    for m in re.finditer(
        r'class="build-name"[^>]*>(.*?)</h3>\s*'
        r'<div class="build-archetype"[^>]*>(.*?)</div>\s*'
        r'<div class="build-progression"[^>]*>(.*?)</div>\s*'
        r'<div class="build-result"[^>]*>(.*?)</div>',
        section,
        re.S | re.I,
    ):
        levels = [
            strip_tags(x)
            for x in re.findall(r'class="build-level"[^>]*>(.*?)</span>', m.group(3), re.S | re.I)
        ]
        out.append(
            {
                "name": strip_tags(m.group(1)),
                "archetype": strip_tags(m.group(2)),
                "levels": levels,
                "result": strip_tags(m.group(4)),
            }
        )
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    STYLES.mkdir(exist_ok=True)
    descs = load_perk_descriptions()
    print("perk descs", len(descs))

    disc = extract_section(HTML, "disciplinas")
    domains = parse_domains(disc, descs)
    print("domains", len(domains), "branches", sum(len(d["branches"]) for d in domains),
          "nodes", sum(len(b["nodes"]) for d in domains for b in d["branches"]))

    criacao = extract_section(HTML, "criacao")
    atributos = extract_section(HTML, "atributos")
    nucleo = extract_section(HTML, "nucleo")
    pericias = extract_section(HTML, "pericias")
    combo = extract_section(HTML, "combo")
    condicoes = extract_section(HTML, "condicoes")
    oportunidade = extract_section(HTML, "oportunidade")
    grid = extract_section(HTML, "grid")
    equipamento = extract_section(HTML, "equipamento")
    progressao = extract_section(HTML, "progressao")
    bestiario = extract_section(HTML, "bestiario")
    oneshot = extract_section(HTML, "oneshot")
    gerais = extract_section(HTML, "gerais")
    builds_sec = extract_section(HTML, "builds")
    pilares = extract_section(HTML, "pilares")

    conditions = parse_conditions(condicoes)
    builds = parse_builds(builds_sec)

    attr_tables = tables_from(atributos)
    nucleo_tables = tables_from(nucleo)
    pericias_tables = tables_from(pericias)
    combo_tables = tables_from(combo)
    grid_tables = tables_from(grid)
    eq_tables = tables_from(equipamento)
    prog_tables = tables_from(progressao)
    best_tables = tables_from(bestiario)
    oneshot_tables = tables_from(oneshot)
    gerais_tables = tables_from(gerais)
    pilares_tables = tables_from(pilares)

    md: list[str] = []
    md.append(
        """---
title: "Sistema das Almas — Livro do Jogador"
subtitle: "Alpha · Playtest"
lang: pt-BR
---

<div class="titlepage">

# SISTEMA DAS ALMAS

## Livro do Jogador

**Edição Alpha · Playtest**

*Crie, teste regras, anote o que falhou.*

</div>

<div class="pagebreak"></div>

# Sumário

**Prefácio**

**Introdução** — Como Jogar · Usando Este Livro · Os Três Pilares

**Parte 1 — O Personagem**

1. Criação de Personagens
2. Atributos
3. Os 8 Domínios · Perícias Vivas
4. Habilidades Gerais e Builds Híbridas
5. Equipamento e Armas
6. Progressão de Nível

**Parte 2 — Jogando a Mesa**

7. Perícias (Lookup)
8. Núcleo de Regras
9. Combate
10. Magia e Pontos de Magia

**Apêndices**

- A. Condições
- B. Bestiário (Nível Baixo)
- C. Kit One-shot
- D. Glossário

<div class="pagebreak"></div>

# Prefácio

Este livro reúne as regras jogáveis do **Sistema das Almas** na versão Alpha de playtest. O objetivo é simples: sentar à mesa, criar personagens em cerca de meia hora e descobrir o que funciona — e o que precisa mudar.

Não há raças ou classes tradicionais. Em vez disso, cada aventureiro escolhe **Raízes** em **domínios** (caminhos de perícia viva) e gasta **Pontos de Disciplina (PD)** para crescer nesses caminhos. Combate, viagem, ofício e palavra pesam igualmente nos três pilares do sistema.

Se algo quebrar na sua mesa, anote. Esta edição existe para ser testada.

<div class="pagebreak"></div>

# Introdução

## Como Jogar

Uma pessoa assume o papel de **Mestre** (descreve o mundo, interpreta personagens secundários, arbitra regras). As demais interpretam **personagens jogadores**.

Quando o resultado de uma ação é incerto, role um **d20** e some o atributo relevante — e, se fizer sentido, a **proficiência** do domínio. Compare com uma **CD** (Classe de Dificuldade) definida pelo mestre.

Em combate, cada personagem tem um **pool de ações** por turno e **1 resposta** por rodada (fora do turno — AO, bloqueio, etc., sem gastar ações). Fora de combate, o pool regenera no início de cada **cena**. Movimento no grid = **3 + ⌊DES/2⌋**. Habilidades vêm dos nós desbloqueados nas árvores de domínio.

## Usando Este Livro

- **Parte 1** ensina a criar e evoluir um personagem.
- **Parte 2** traz o miolo da mesa: testes, combate, combo e magia.
- Os **Apêndices** concentram condições, inimigos de playtest, um kit one-shot e o glossário.

Leia o Capítulo 1 e o Capítulo 8 antes da primeira sessão. Os domínios (Capítulo 3) podem ser consultados sob demanda.

## Os Três Pilares

"""
    )
    # pilares intro text
    md.append(
        """| Pilar | O que cobre | Regeneração de ações |
| --- | --- | --- |
| **Combate** | Encontros hostis no grid: dano, defesa, posição, moral | Por **turno** |
| **Mundo** | Viagem, sobrevivência, ofício, infiltração, investigação de locais | Por **cena** |
| **Almas** | Negociação, espírito, leitura de pessoas, performance, política | Por **cena** |

"""
    )
    if pilares_tables:
        md.append("### Regras fora do combate\n\n")
        md.append(table_md(pilares_tables[0]) + "\n")

    md.append(
        """
<div class="pagebreak"></div>

# PARTE 1

<div class="pagebreak"></div>

# CAPÍTULO 1: CRIAÇÃO DE PERSONAGENS

De conceito a personagem jogável em **20–30 minutos**. Não pense em classes nem em roles de combate — pense em quem a pessoa é.

## Passo 1 — Conceito (5 min)

Pense em quem é seu personagem narrativamente. Pergunte-se:

- *Como ele resolve conflito?* (força, distância, magia, palavra…)
- *Como se move no mundo?* (viagem, ofício, infiltração, estudo…)
- *Como influencia pessoas e espíritos?* (medo, cura, política, performance…)

## Passo 2 — Atributos (10 min)

Distribua **10 pontos** entre 6 atributos. Máximo **+4** no nível 1.

**FOR** · **DES** · **CON** · **INT** · **SAB** · **CAR**

Detalhes e custo progressivo estão no Capítulo 2.

## Passo 3 — Escolha 1 Raiz (5 min)

No nível 1, escolha **1 Raiz** (caminho grátis). Exemplos civis: Artes, Artesanato, Herbário, Comércio (Ofício), Erudição, Palco, Caminho. Exemplos de conflito: Duelista, Evocação, Sombra, Muralha. A cada nível seguinte: **+1 PD**.

## Passo 4 — Habilidades Iniciais

Sua Raiz concede a **habilidade inicial do ramo**. Além disso, escolha **1 habilidade geral** (Capítulo 4).

## Passo 5 — Definir Stats

| Stat | Regra |
| --- | --- |
| **PV** | 8 + CON no nv1; depois +5 + CON por nível |
| **Ações** | 1 no nível 1; sobe conforme a tabela de progressão |
| **PM** | INT × 3 |
| **CA** | 10 + DES + armadura + escudo |
| **Proficiência** | +1 (nv1–2); +1 a cada 2 níveis (Núcleo) |

"""
    )

    md.append(
        """
<div class="pagebreak"></div>

# CAPÍTULO 2: ATRIBUTOS

Cada atributo ganha funções ativas e passivas.

"""
    )
    if len(attr_tables) >= 1:
        md.append(table_md(attr_tables[0]) + "\n\n")
    md.append("## Custo Progressivo de Atributos\n\n")
    md.append(
        "Personagens altamente especializados pagam um preço real. Um personagem com FOR +8 sacrificou 17 pontos de atributo.\n\n"
    )
    if len(attr_tables) >= 2:
        md.append(table_md(attr_tables[1]) + "\n\n")
    md.append("## Ações por Nível · PM\n\n")
    if len(attr_tables) >= 3:
        md.append(table_md(attr_tables[2]) + "\n\n")
    md.append(
        '<div class="nota">\n\nAções: +1/nível até nv7; depois +1 em 9, 12 e 16 (teto 10). PM não cresce com nível — só com INT.\n\n</div>\n'
    )

    md.append("\n<div class=\"pagebreak\"></div>\n\n")
    md.append(build_domains_md(domains))

    md.append(
        """
<div class="pagebreak"></div>

# CAPÍTULO 4: HABILIDADES GERAIS E BUILDS HÍBRIDAS

## Habilidades Gerais

Escolha **1** no nível 1 — não pertencem a nenhum domínio. Gerais **não** gastam PD. PD (todo nível) só compra nós/Raízes de domínio. No nv7 e nv14 o mestre pode premiar +1 Geral opcional.

"""
    )
    if gerais_tables:
        md.append(table_md(gerais_tables[0]) + "\n\n")

    md.append("## Builds Híbridas\n\nMisture domínios nos três pilares — não só no combate.\n\n")
    for b in builds:
        md.append(f"### {b['name']}\n\n")
        md.append(f"*{b['archetype']}*\n\n")
        if b["levels"]:
            md.append(" → ".join(b["levels"]) + "\n\n")
        md.append(f"{b['result']}\n\n")

    md.append(
        """
<div class="pagebreak"></div>

# CAPÍTULO 5: EQUIPAMENTO E ARMAS

"""
    )
    md.append("## Armas\n\n")
    if len(eq_tables) >= 1:
        md.append(table_md(eq_tables[0]) + "\n\n")
    md.append(
        '<div class="nota">\n\nEscalamento: armas leves e ranged ganham +1d6 de dano a cada 5 níveis; pesadas a cada 4 níveis. Magias escalam a cada 3 níveis.\n\n</div>\n\n'
    )
    md.append("## Armaduras\n\n")
    if len(eq_tables) >= 2:
        md.append(table_md(eq_tables[1]) + "\n\n")

    md.append(
        """
<div class="pagebreak"></div>

# CAPÍTULO 6: PROGRESSÃO DE NÍVEL

Todo nível: **+1 atributo** e **+1 ponto de disciplina (PD)**.

**Ponto de Disciplina (PD):** gaste 1 PD para desbloquear **1 nó** de qualquer ramo cuja Raiz você já tenha — ou para comprar uma **Nova Raiz** (novo ramo/caminho). Nós com fork (ex.: Chama / Raio / Gelo) são escolhas: pegar um não bloqueia os outros, mas cada um custa 1 PD.

**Ações:** recurso do seu turno (ataques, habilidades de turno). Respostas fora do turno não gastam ações. Começa em **1** no nível 1 e sobe rápido no início; depois os ganhos espaçam (+1/nível até o 7; depois +1 nos níveis 9, 12 e 16 — teto 10).

"""
    )
    if prog_tables:
        md.append(table_md(prog_tables[0]) + "\n\n")
    md.append(
        '<div class="nota">\n\nTotal: 19 PD (nv2–20) + Raiz e Geral no nv1. Atributo máximo +10. PV: 8+CON, depois +5+CON/nível. Morte: 0 PV → 1 rodada para cura ou morre.\n\n</div>\n'
    )

    md.append(
        """
<div class="pagebreak"></div>

# PARTE 2

<div class="pagebreak"></div>

# CAPÍTULO 7: PERÍCIAS

Lookup rápido: o que o mestre pediu → domínio e atributo.

**Fórmula:** `d20 + atributo + proficiência` (se tiver a **Raiz** do domínio) + **afinidade +2** fora de combate. O mestre escolhe o atributo pela situação; a tabela sugere o típico.

"""
    )
    if pericias_tables:
        md.append(table_md(pericias_tables[0]) + "\n\n")

    md.append(
        """
<div class="pagebreak"></div>

# CAPÍTULO 8: NÚCLEO DE REGRAS

O miolo que a mesa precisa para jogar sem improvisar.

## Resolução de Testes

**Teste:** d20 + atributo + proficiência (se o domínio cobrir a ação) + afinidade (+2 se tiver a Raiz, só fora de combate) vs **CD**.

"""
    )
    # nucleo tables order from earlier read:
    # 0 CD, 1 turno, 2 ataque, 3 morte, 4 descanso, 5 proficiencia
    if len(nucleo_tables) >= 1:
        md.append(table_md(nucleo_tables[0]) + "\n\n")
    md.append(
        """**Vantagem:** role 2d20, use o maior. **Desvantagem:** role 2d20, use o menor. Não empilham: 1 vantagem + 1 desvantagem = normal. Vantagens múltiplas = ainda 1 vantagem.

**Concentração:** efeitos que exigem Concentração caem se você: (a) ficar Atordoado/Paralisado/inconsciente, (b) falhar TDD CON CD 10 + metade do dano recebido (mín. 10) ao tomar dano, ou (c) ativar outro efeito de Concentração.

## Ações

**Ação** é o recurso do **seu turno**: ataques básicos, habilidades de turno, desengajar, ajudar, usar item. No combate regenera no **início do turno**; fora dele, no início de cada **cena**. O pool sobe com o nível (começa em 1 — ver Progressão). Habilidades com **gatilho fora do turno** (quando atacado, AO, etc.) **não** gastam ações — usam 1 **resposta** por rodada (e PM se o nó pedir).

## Descanso e PV

"""
    )
    # find descanso table - index 4 typically
    if len(nucleo_tables) >= 5:
        md.append(table_md(nucleo_tables[4]) + "\n\n")
    md.append("## Proficiência\n\n")
    if len(nucleo_tables) >= 6:
        md.append(table_md(nucleo_tables[5]) + "\n\n")
    md.append(
        "Fórmula: `1 + ⌊(nível − 1) / 2⌋`. Aplica-se a ataques com arma/magia treinada e a testes cobertos por um domínio em que você tenha ao menos a Raiz.\n"
    )

    md.append(
        """
<div class="pagebreak"></div>

# CAPÍTULO 9: COMBATE

## Turno de Combate

"""
    )
    if len(nucleo_tables) >= 2:
        md.append(table_md(nucleo_tables[1]) + "\n\n")

    md.append("## Ataque Básico\n\n")
    if len(nucleo_tables) >= 3:
        md.append(table_md(nucleo_tables[2]) + "\n\n")
    md.append(
        "Desengajar (sair sem provocar AO): **1 ação**. Ajudar aliado (+vantagem no próximo teste dele): **1 ação**.\n\n"
    )

    md.append(
        """## Ação Reservada

No **fim do seu turno**, declare quantas ações não gastas ficam **reservadas** até o início do seu próximo turno (máx. = suas ações de nível). Ação reservada **não** vira gasto de turno nem resposta — só alimenta efeitos como **Muralha** (bônus de CA = ação reservada × 1,5, arredondado para baixo). Ao iniciar o próximo turno, a ação reservada some e você recupera o pool cheio normalmente.

## Queda e Morte

"""
    )
    if len(nucleo_tables) >= 4:
        md.append(table_md(nucleo_tables[3]) + "\n\n")
    md.append(
        callout(
            "exemplo",
            "Exemplo: Kael cai a 0 PV no turno do orc. Todos os combatentes ainda vão agir nessa rodada e na seguinte. Se ninguém curar Kael até o fim da rodada seguinte, Kael morre.",
        )
    )

    md.append(
        """
## Ataques de Oportunidade

| Aspecto | Regra |
| --- | --- |
| **Quando** | Quando um inimigo **sai do seu alcance corpo a corpo** sem usar a ação de desengajamento. |
| **Custo** | **Sem custo de ação** — usa sua **1 resposta** da rodada. Limite de 1 AO por rodada. |
| **Efeito** | Um ataque corpo a corpo imediato com **−2 de penalidade** no acerto. |

"""
    )
    md.append(
        callout(
            "nota",
            "**Trilha muda o jogo:** Escapismo e Sombra permitem sair sem provocar AO. Contra um especialista em Trilha, ataques de oportunidade raramente conectam — e é por isso que Precisão ganha valor real no grid.",
        )
    )

    md.append("\n## Grid e Posicionamento\n\n### Alcances\n\n")
    if len(grid_tables) >= 1:
        md.append(table_md(grid_tables[0]) + "\n\n")
    md.append("### Terreno e Cobertura\n\n")
    if len(grid_tables) >= 2:
        md.append(table_md(grid_tables[1]) + "\n\n")

    md.append(
        """
## Barra de Combo

Cada **acerto** (ataque ou magia ofensiva) enche **1 slot**. Errar **não** esvazia a barra. Com slots suficientes para um tier, você pode usar um **Finalizador**: execute um ataque ou habilidade ofensiva, pague o **mesmo custo de ações** dessa habilidade (ataque básico = 1 ação; magia = custo listado), escolha **1 opção** do tier, aplique o efeito em cima do ataque/magia, e **zere** a barra. Sem ações suficientes, não pode gastar. A barra persiste entre rodadas e reseta ao fim do combate.

### Tiers de Finalizador — escolha 1 ao usar

"""
    )
    if len(combo_tables) >= 1:
        md.append(table_md(combo_tables[0]) + "\n\n")
    md.append(
        '<div class="nota">\n\nCapacidade da barra: nv1–4 = 3 slots; nv5–8 = 4; nv9–12 = 5; nv13+ = 6. Você gasta o maior tier cujo requisito de slots preencheu. Role acerto normalmente (salvo efeito que diga o contrário); crítico ainda em 20.\n\n</div>\n\n'
    )

    md.append(
        """### Ataque Conjunto

Todos os participantes devem estar **adjacentes ao alvo** e gastar **2 ações** cada. Um **líder** rola o acerto; o dano é o da arma/habilidade do líder + o bônus da tabela. Os outros não rolam ataque — só pagam o custo e habilitam o bônus.

"""
    )
    if len(combo_tables) >= 2:
        md.append(table_md(combo_tables[1]) + "\n\n")

    md.append(
        """
<div class="pagebreak"></div>

# CAPÍTULO 10: MAGIA E PONTOS DE MAGIA

Neste sistema não há lista separada de “magias de nível”. A magia é um conjunto de **nós** no domínio **Arcana** (e, em menor grau, efeitos espirituais em **Voz — Elo** e utilidades em **Guarda / Ofício**).

## Pontos de Magia (PM)

- **Pool:** INT × 3.
- **Não cresce com nível** — só com o atributo INT.
- Habilidades mágicas listam custo em **ações** e, quando aplicável, em **PM** no texto do nó (Capítulo 3 · Arcana).
- **Descanso curto:** recupera metade do PM (arredondado para cima).
- **Descanso longo:** PM no máximo.

## Conjurar

1. Declara a habilidade do nó que você possui.
2. Paga o custo de ações (e PM, se houver).
3. Resolve acerto (`d20 + INT` ou atributo indicado + proficiência vs CA) **ou** força um TDD no alvo, conforme o nó.
4. Aplica dano/efeito; críticos e combo seguem as regras do Capítulo 9.

## Concentração

Alguns efeitos pedem Concentração. Veja Capítulo 8. Ativar outro efeito de Concentração derruba o anterior.

## Onde achar as magias

Consulte o domínio **Arcana** no Capítulo 3: Evocação (e forks Chama / Raio / Gelo), Invocação, Erudição e Véu. Cada nó traz efeito curto na tabela e descrição expandida abaixo dela.

"""
    )

    # Appendices
    md.append(
        """
<div class="pagebreak"></div>

# APÊNDICE A: CONDIÇÕES

Efeitos de status com mecânicas definidas.

"""
    )
    for name, text in conditions:
        md.append(f"### {name}\n\n{text}\n\n")
    # regras gerais from condicoes
    rg = re.search(
        r"Regras Gerais</h3>\s*<p[^>]*>(.*?)</p>",
        condicoes,
        re.S | re.I,
    )
    if rg:
        md.append("## Regras Gerais\n\n")
        md.append(strip_tags(rg.group(1)) + "\n\n")

    md.append(
        """
<div class="pagebreak"></div>

# APÊNDICE B: BESTIÁRIO (NÍVEL BAIXO)

Inimigos para playtest · fichas compactas · XP ao morrer.

## XP e nível

Some o XP dos inimigos derrotados. A mesa pode usar a tabela abaixo *ou* avançar 1 nível por arco — escolha uma regra e mantenha.

"""
    )
    if len(best_tables) >= 1:
        md.append(table_md(best_tables[0]) + "\n\n")
    md.append(
        '<div class="nota">\n\nInimigos morrem a 0 PV (sem a regra de 1 rodada dos jogadores).\n\n</div>\n\n'
    )
    md.append("## Fichas\n\n")
    if len(best_tables) >= 2:
        md.append(table_md(best_tables[1]) + "\n\n")

    md.append(
        """
<div class="pagebreak"></div>

# APÊNDICE C: KIT ONE-SHOT (PLAYTEST)

3 fichas nv3 · inimigos do Bestiário · 3 cenas — ~3–4 horas.

## Personagens prontos (nv 3)

"""
    )
    if oneshot_tables:
        md.append(table_md(oneshot_tables[0]) + "\n\n")
    md.append(
        '<div class="nota">\n\nCada um também pegou 1 upgrade de domínio no nv3 (ex.: Ryn → Ataque Furtivo; Sera → Negociação; Tor → Vigília). Ajuste à mesa.\n\n</div>\n\n'
    )
    md.append(
        """## Inimigos

Use as fichas do Bestiário: **4× Capanga** (50 XP cada) + **1× Capitão da Guarda** (300 XP). Total do combate: **500 XP** (dividir pelo grupo se usar XP).

## Três cenas

1. **Almas** — Negociar passagem no portão (Capitão). CD CAR/SAB 14; falha → combate ou suborno caro.
2. **Mundo** — Seguir rastros até o armazém (Rastreador/Investigação). CD 14; sucesso: emboscada invertida (vantagem no 1º turno).
3. **Combate** — 4 Capangas + Capitão no grid 8×8. Objetivo: capturar ou matar o Capitão. Testa combo, AO, queda a 0 PV.

Após a cena 2: 1 descanso curto. Anote o que atrapalhou a mesa e ajuste.

"""
    )

    md.append(
        """
<div class="pagebreak"></div>

# APÊNDICE D: GLOSSÁRIO

| Termo | Significado |
| --- | --- |
| **Ação** | Recurso do seu turno (combate) ou da cena (fora dele). Ataques e habilidades de turno custam ações; respostas fora do turno não. |
| **Afinidade** | +2 em testes de um domínio fora de combate, se você tiver a Raiz desse domínio. |
| **AO** | Ataque de Oportunidade — resposta (−2 acerto) quando alguém sai do seu corpo a corpo sem desengajar. Sem custo de ação. |
| **CA** | Classe de Armadura. Base 10 + DES + armadura + escudo (+ outros bônus). |
| **CD** | Classe de Dificuldade do teste ou TDD. |
| **Cena** | Unidade narrativa fora de combate definida pelo mestre; regenera o pool de ações. |
| **Combo** | Barra de slots enchida por acertos; gasta-se num Finalizador. |
| **Concentração** | Estado que mantém certos efeitos; cai com atordoamento, falha em TDD CON ao tomar dano, ou novo efeito de Concentração. |
| **Domínio** | Um dos 8 eixos de Perícia Viva (Corpo, Precisão, Arcana, Guarda, Trilha, Insight, Voz, Ofício). |
| **Fork** | Caminho paralelo na árvore; comprar um não bloqueia os outros. |
| **Grid** | Quadrado do tabuleiro; movimento = **3 + ⌊DES/2⌋** grid por turno. |
| **PD** | Ponto de Disciplina — 1 por nível (após o 1º) para comprar nó ou nova Raiz. |
| **PM** | Pontos de Magia — INT × 3. |
| **Proficiência** | Bônus por nível: `1 + ⌊(nível − 1) / 2⌋` (+1 no nv1–2 … +10 no nv19–20), em ataques e testes com Raiz. |
| **PV** | Pontos de Vida. A 0 PV o personagem cai; tem 1 rodada para receber cura ou morre. |
| **Raiz** | Primeiro nó de um ramo; concede afinidade e acesso à árvore. |
| **Reservada** | Ação não gasta no fim do turno, usada só para efeitos como Muralha. |
| **Resposta** | 1×/rodada fora do seu turno (AO, bloqueio, esquiva…). Não gasta ações; pode custar PM. |
| **TDD** | Teste de Dificuldade / teste de resistência: d20 + atributo vs CD. |

---

✦ **Sistema das Almas** · Alpha · Playtest · +1 PD/nível · 32 caminhos

*Texto de regras baseado na documentação Alpha do sistema. Layout inspirado na hierarquia de um livro do jogador clássico — conteúdo original.*
"""
    )

    book_path = OUT / "livro-do-jogador.md"
    book_path.write_text("".join(md), encoding="utf-8")
    print("wrote", book_path, "chars", book_path.stat().st_size)


if __name__ == "__main__":
    main()
