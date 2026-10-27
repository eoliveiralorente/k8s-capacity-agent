#!/usr/bin/env python3
"""Kit de entrega por cliente (uso do FORNECEDOR, não vai na imagem).

Gera em entregas/<cliente>/ tudo o que o cliente precisa para instalar:
  - licença assinada (.license.json)
  - chart Helm empacotado (.tgz) da versão entregue
  - values-<cliente>.yaml (nome do cluster, versão da imagem, pull secret)
  - instalar.sh (verifica o ambiente, pede o token sem gravá-lo, instala com helm ou kubectl
    e, se algo falhar, mostra o motivo provável), desinstalar.sh e diagnostico.sh
  - manifestos-<cliente>.yaml (instalação sem helm; gerado se houver helm nesta máquina)
  - GUIA_RAPIDO.md preenchido com os dados do cliente
  - ATUALIZACAO.md (como atualizar com um kit novo) e NOVIDADES.md (o changelog)
  - TERMOS_DE_USO.md e PRIVACIDADE.md (o instalar.sh pede o aceite dos termos)
  - um .zip com tudo, pronto para enviar

O TOKEN de leitura da imagem NÃO entra no kit: envie por outro canal (ex.: WhatsApp)
e oriente o cliente a colar quando o instalar.sh pedir.

Uso:
  python3 tools/kit_cliente.py --customer "Empresa X" --version 1.3.0 --pilot
  python3 tools/kit_cliente.py --customer "Empresa X" --version 1.3.0 --plan profissional --days 365
  python3 tools/kit_cliente.py --customer "Empresa X" --version 1.3.0 --plan enterprise \
      --clusters 6 --users 50 --nodes 150 --days 365
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

REGISTRY = "ghcr.io"
IMAGE = "ghcr.io/eoliveiralorente/k8s-capacity-agent"
PULL_SECRET = "capacity-agent-pull"
PILOT = {"plan": "enterprise", "clusters": 1, "users": 5, "days": 30, "nodes": 0}

TEMPLATES = Path(__file__).resolve().parent / "kit_templates"

VALUES = """# Capacity Agent — {customer}
clusterName: "{cluster_name}"

image:
  repository: {image}
  tag: "{version}"
imagePullSecrets:
  - name: {pull_secret}

# Somente leitura. Para permitir aplicar ajustes APÓS aprovação no painel, troque para true.
rbac:
  allowRightsizing: false
"""


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "cliente"


def package_chart(out_dir, version):
    chart_src = ROOT / "charts" / "capacity-agent"
    if shutil.which("helm"):
        subprocess.run(["helm", "package", str(chart_src), "--version", version, "--app-version", version,
                        "-d", str(out_dir)], check=True, capture_output=True)
        return next(out_dir.glob("capacity-agent-*.tgz")).name
    # Sem helm: empacota o diretório (helm aceita instalar de um .tgz com a pasta do chart)
    import tarfile

    name = f"capacity-agent-{version}.tgz"
    with tarfile.open(out_dir / name, "w:gz") as tar:
        tar.add(chart_src, arcname="capacity-agent")
    return name


def render_manifests(out, chart_file, slug):
    """Manifestos prontos para quem não tem helm (renderizados aqui, com a chave em Secret próprio)."""
    if not shutil.which("helm"):
        print("AVISO: helm não encontrado nesta máquina; o kit vai exigir helm no cliente.")
        return None
    result = subprocess.run(
        ["helm", "template", "capacity-agent", str(out / chart_file), "--namespace", "capacity-agent",
         "-f", str(out / f"values-{slug}.yaml"), "--set", "encryption.existingSecret=capacity-agent-encryption"],
        check=True, capture_output=True, text=True)
    path = out / f"manifestos-{slug}.yaml"
    path.write_text(result.stdout, encoding="utf-8")
    return path.name


def build_kit(args):
    from license_tool import issue_license

    slug = args.slug or slugify(args.customer)
    plan, clusters, users, days, nodes = args.plan, args.clusters, args.users, args.days, args.nodes
    if args.pilot:
        plan, clusters, users, days, nodes = (PILOT["plan"], PILOT["clusters"], PILOT["users"], PILOT["days"],
                                              PILOT["nodes"])
    if not plan:
        sys.exit("Informe --pilot ou --plan (essencial, profissional ou enterprise).")

    out = ROOT / "entregas" / slug
    if out.exists() and not args.force:
        sys.exit(f"{out} já existe. Use --force para gerar de novo (a licença anterior continua válida até expirar).")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    envelope, payload = issue_license(args.customer, plan, clusters, users, days, nodes=nodes)
    clusters, users = payload["max_clusters"], payload["max_users"]
    nodes_txt = f" · até {payload['max_nodes']} nodes (média do mês)" if payload.get("max_nodes") else ""
    license_file = f"{slug}.license.json"
    (out / license_file).write_text(json.dumps(envelope, indent=2), encoding="utf-8")

    chart_file = package_chart(out, args.version)
    fields = dict(customer=args.customer, slug=slug, version=args.version, image=IMAGE, registry=REGISTRY,
                  registry_user=args.registry_user, pull_secret=PULL_SECRET, chart_file=chart_file,
                  license_file=license_file, cluster_name=args.cluster_name or "Produção")
    (out / f"values-{slug}.yaml").write_text(VALUES.format(**fields), encoding="utf-8")
    for script in ("instalar.sh", "desinstalar.sh", "diagnostico.sh"):
        text = (TEMPLATES / script).read_text(encoding="utf-8")
        for key, value in fields.items():
            text = text.replace(f"__{key.upper()}__", str(value))
        (out / script).write_text(text, encoding="utf-8", newline="\n")
        (out / script).chmod(0o755)
    manifests = render_manifests(out, chart_file, slug)

    guide = (ROOT / "docs" / "cliente" / "GUIA_RAPIDO.md").read_text(encoding="utf-8")
    expires = payload["expires_at"][:10]
    guide = (guide.replace("{{CLIENTE}}", args.customer).replace("{{VERSAO}}", args.version)
             .replace("{{LICENCA}}", license_file).replace("{{VALIDADE}}", datetime.fromisoformat(expires).strftime("%d/%m/%Y"))
             .replace("{{SLUG}}", slug))
    (out / "GUIA_RAPIDO.md").write_text(guide, encoding="utf-8")

    # Guia de atualização e novidades: o mesmo kit serve para instalar e para atualizar.
    update = (ROOT / "docs" / "cliente" / "ATUALIZACAO.md").read_text(encoding="utf-8")
    (out / "ATUALIZACAO.md").write_text(update.replace("<sua-empresa>", slug), encoding="utf-8")
    for doc in ("TERMOS_DE_USO.md", "PRIVACIDADE.md"):
        shutil.copyfile(ROOT / "docs" / "cliente" / doc, out / doc)
    changelog = ROOT / "CHANGELOG.md"
    if changelog.is_file():
        shutil.copyfile(changelog, out / "NOVIDADES.md")

    zip_path = out.parent / f"capacity-agent-{slug}-{args.version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.iterdir()):
            z.write(f, f"capacity-agent-{slug}/{f.name}")

    print(f"Kit de {args.customer} gerado em {out}")
    print(f"  Plano {plan} · {clusters} cluster(s) · {users} usuário(s){nodes_txt} · válido até {expires}")
    print(f"  Arquivo para enviar: {zip_path}")
    if not manifests:
        print("  (sem manifestos para instalação sem helm: rode o kit numa máquina com helm)")
    print()
    print("Próximos passos (fornecedor):")
    print(f"  1. Crie um token SÓ DE LEITURA de pacotes para este cliente (veja docs/ENTREGA_CLIENTE.md)")
    print("  2. Envie o .zip por e-mail e o token por OUTRO canal (ex.: WhatsApp)")
    print("  3. Ao fim do piloto ou contrato, revogue o token no GitHub")
    return zip_path


def main():
    p = argparse.ArgumentParser(description="Gera o kit de entrega de um cliente (uso do fornecedor)")
    p.add_argument("--customer", required=True, help='Nome do cliente, ex.: "Empresa X"')
    p.add_argument("--slug", help="Identificador curto (padrão: derivado do nome)")
    p.add_argument("--version", required=True, help="Versão publicada da imagem, ex.: 1.3.0")
    p.add_argument("--pilot", action="store_true", help="Piloto: enterprise, 1 cluster, 5 usuários, 30 dias")
    p.add_argument("--plan", choices=["essencial", "profissional", "enterprise"])
    p.add_argument("--clusters", type=int, help="Padrão: do plano")
    p.add_argument("--users", type=int, help="Padrão: do plano")
    p.add_argument("--nodes", type=int, help="Nodes contratados, média do mês (só aviso). Padrão: do plano; 0 = sem limite")
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--cluster-name", help='Nome exibido no painel (padrão: "Produção")')
    p.add_argument("--registry-user", default="capacity-agent-bot",
                   help="Usuário do GitHub dono do token de leitura (padrão: capacity-agent-bot)")
    p.add_argument("--force", action="store_true")
    build_kit(p.parse_args())


if __name__ == "__main__":
    main()
