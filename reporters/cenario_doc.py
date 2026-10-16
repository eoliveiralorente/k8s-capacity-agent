import re
from pathlib import Path


DEFAULT_MD = Path(__file__).parent.parent / "docs" / "cenario-ambiente-cluster.md"
DEFAULT_CSS = Path(__file__).parent.parent / "web" / "static" / "cenario.css"


def _parse_meta(content):

    meta = {
        "title": "Cenário do Ambiente — Cluster GKE",
        "subtitle": "Análise de capacity e estabilidade operacional",
        "cluster": "—",
        "region": "—",
        "project": "—",
        "evaluated_at": "—",
        "reference": "—",
        "author": "Capacity Agent",
        "status_label": "Instabilidade",
        "status_level": "critical",
    }

    lines = content.splitlines()

    if lines and lines[0].startswith("# "):
        meta["title"] = lines[0][2:].strip().replace("`", "")

    field_map = {
        "Documento": "subtitle",
        "Situação": "situation_line",
        "Cluster": "cluster_line",
        "Data da avaliação": "evaluated_at",
        "Período de custos": "cost_period",
        "Referência": "reference",
        "Elaborado por": "author",
        "Público-alvo": "audience",
    }

    for line in lines[1:20]:
        if not line.startswith("**"):
            continue

        match = re.match(r"\*\*(.+?):\*\*\s*(.+)", line.strip())
        if not match:
            continue

        label, value = match.groups()
        key = field_map.get(label.strip())
        if not key:
            continue

        value = value.strip().strip("`")
        if key == "cluster_line":
            parts = [part.strip().strip("`") for part in value.split("|")]
            if parts:
                meta["cluster"] = parts[0]
            for part in parts[1:]:
                if part.lower().startswith("região:"):
                    meta["region"] = part.split(":", 1)[1].strip()
                elif part.lower().startswith("projeto:"):
                    meta["project"] = part.split(":", 1)[1].strip()
        elif key == "situation_line":
            meta["situation_line"] = value
            lower = value.lower()
            if "instabilidade" in lower or "crítico" in lower:
                meta["status_label"] = "Instabilidade"
                meta["status_level"] = "critical"
            elif "atenção" in lower or "oportunidade" in lower:
                meta["status_label"] = "Atenção"
                meta["status_level"] = "attention"
        else:
            meta[key] = value

    if meta.get("situation_line") is None:
        if "Instabilidade" in content:
            meta["status_label"] = "Instabilidade"
            meta["status_level"] = "critical"
        elif "Atenção" in content[:2000]:
            meta["status_label"] = "Atenção"
            meta["status_level"] = "attention"
        else:
            meta["status_label"] = "Estável"
            meta["status_level"] = "healthy"

    title_lower = meta["title"].lower()
    if "proposta" in title_lower:
        meta["doc_type"] = "Proposta Executiva"
    elif "cenário" in title_lower or "cenario" in title_lower:
        meta["doc_type"] = "Relatório de Cenário"
    else:
        meta["doc_type"] = "Relatório Gerencial"

    meta.setdefault("audience", "—")
    meta.setdefault("cost_period", "—")

    return meta


def _prepare_body_html(markdown_text):

    html = _markdown_to_html(markdown_text)
    has_mermaid = "```mermaid" in markdown_text

    if has_mermaid:
        html = re.sub(
            r'<pre><code class="language-mermaid">(.*?)</code></pre>',
            r'<pre class="mermaid">\1</pre>',
            html,
            flags=re.DOTALL,
        )

    return html, has_mermaid


def _body_markdown(content):

    lines = content.splitlines()
    start = 0

    for index, line in enumerate(lines):
        if line.startswith("## "):
            start = index
            break

    return "\n".join(lines[start:]).strip()


def _markdown_to_html(markdown_text):

    try:
        import markdown
    except ImportError as exc:
        raise RuntimeError(
            "Módulo 'markdown' não encontrado. Instale com: "
            "python3 -m pip install markdown"
        ) from exc

    return markdown.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "nl2br"],
    )


def write_cenario_html(md_path=None, output_path=None):

    md_path = Path(md_path or DEFAULT_MD)
    output_path = Path(
        output_path or md_path.with_suffix(".html"),
    )

    content = md_path.read_text(encoding="utf-8")
    meta = _parse_meta(content)
    body_html, has_mermaid = _prepare_body_html(_body_markdown(content))

    css_path = DEFAULT_CSS
    css = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    mermaid_head = ""
    mermaid_script = ""
    if has_mermaid:
        mermaid_head = (
            '<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js">'
            "</script>"
        )
        mermaid_script = """
  <script>
    mermaid.initialize({ startOnLoad: true, theme: "neutral", securityLevel: "loose" });
  </script>"""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{meta['title']}</title>
  <style>{css}</style>
  {mermaid_head}
</head>
<body>
  <div class="toolbar no-print">
    <div class="toolbar-title">Documento gerencial — pronto para PDF</div>
    <div class="toolbar-right">
      <button class="btn btn-primary" onclick="window.print()">Exportar PDF / Imprimir</button>
    </div>
  </div>

  <article class="document">
    <header class="doc-header">
      <div class="doc-header-top">
        <div class="doc-logo">Capacity Agent · {meta['doc_type']}</div>
        <div class="status-badge {meta['status_level']}">
          <span class="status-dot"></span>
          {meta['status_label']}
        </div>
      </div>
      <h1 class="doc-title">{meta['title']}</h1>
      <p class="doc-subtitle">{meta['subtitle']}</p>
      <div class="doc-meta">
        <div class="meta-item">
          <label>Cluster</label>
          <span>{meta['cluster']}</span>
        </div>
        <div class="meta-item">
          <label>Região / Projeto</label>
          <span>{meta['region']} · {meta['project']}</span>
        </div>
        <div class="meta-item">
          <label>Data da avaliação</label>
          <span>{meta['evaluated_at']}</span>
        </div>
        <div class="meta-item">
          <label>Público-alvo</label>
          <span>{meta['audience']}</span>
        </div>
        <div class="meta-item">
          <label>Período de custos</label>
          <span>{meta['cost_period']}</span>
        </div>
        <div class="meta-item">
          <label>Referência</label>
          <span>{meta['reference']}</span>
        </div>
      </div>
    </header>

    <div class="doc-body">
      {body_html}
    </div>

    <footer class="doc-footer">
      <p>Documento elaborado com base na avaliação {meta['reference']} · Projeto {meta['project']}.</p>
      <p>Confidencial — uso interno.</p>
    </footer>
  </article>{mermaid_script}
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    return output_path
