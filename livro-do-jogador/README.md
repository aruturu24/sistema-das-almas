# Sistema das Almas — Livro do Jogador

Markdown + CSS para exportar um PDF no estilo livro do jogador (Alpha / playtest).

## Arquivos

| Arquivo | Uso |
| --- | --- |
| `livro-do-jogador.md` | Conteúdo completo |
| `styles/livro.css` | Tipografia, `@page`, callouts, tabelas |
| `export_pdf.py` | Gera o PDF no Windows (recomendado) |
| `../_build_livro.py` | Regenera o `.md` a partir do `index.html` |

## Exportar PDF (Windows — recomendado)

```powershell
cd livro-do-jogador
python export_pdf.py
```

Gera capa ilustrada + interiores com ornamentos. Saída: `livro-do-jogador.pdf`.

Primeira vez (deps):

```powershell
pip install markdown playwright
python -m playwright install chromium
```

## Alternativa: Pandoc

Se o `pandoc` não for reconhecido no PowerShell, feche e abra o terminal (o PATH só atualiza em novas sessões), ou use o caminho completo:

```powershell
& "$env:LOCALAPPDATA\Pandoc\pandoc.exe" livro-do-jogador.md -o livro-do-jogador.pdf --css=styles/livro.css --pdf-engine=weasyprint
```

No Windows, WeasyPrint costuma falhar sem GTK. Prefira `export_pdf.py`.

## Regenerar a partir do site

Se o `index.html` mudar:

```powershell
python ..\_build_livro.py
python export_pdf.py
```

## Notas

- Conteúdo de regras: documentação Alpha do Sistema das Almas.
- Prefácio, introdução e glossário: texto original mínimo.
- Layout inspirado na hierarquia de um PHB clássico — **não** copia texto de D&D 5e.
