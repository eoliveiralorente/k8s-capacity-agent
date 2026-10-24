#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import subprocess
import sys

from config import AUTO_EXECUTE, CLUSTER, REQUIRE_APPROVAL, WEB_HOST, WEB_PORT

from approval.gate import (
    approve,
    can_execute,
    gate_summary,
    list_by_status,
    mark_executed,
    reject,
)
from approval.store import (
    list_reports,
    load_report,
)
from engine.evaluation import run_evaluation, summarize_report_for_api
from executors.gke import execute_operation
from reporters.cenario_doc import write_cenario_html
from reporters.executive import build_executive_report, write_executive_html


def _python_has_uvicorn(python_exe):

    if not python_exe or not os.path.isfile(python_exe):
        return False

    result = subprocess.run(
        [python_exe, "-c", "import uvicorn"],
        capture_output=True,
    )

    return result.returncode == 0


def _resolve_python_for_serve():

    candidates = []

    for candidate in (
        os.environ.get("CAPACITY_AGENT_PYTHON"),
        sys.executable,
        shutil.which("python3"),
        os.path.expanduser("~/.oci/bin/python3"),
        "/root/.oci/bin/python3",
    ):
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    for python_exe in candidates:
        if _python_has_uvicorn(python_exe):
            return python_exe

    return None


def cmd_serve(args):

    python_exe = _resolve_python_for_serve()

    if python_exe is None:
        print("ERRO: uvicorn não encontrado no Python em uso.")
        print()
        print(f"  Python atual.....: {sys.executable}")
        print(f"  pip instalado em.: ~/.oci/ (Python separado do python3 do sistema)")
        print()
        print("  Soluções:")
        print("    1. Use o Python que tem as dependências:")
        print("       ~/.oci/bin/python3 agent.py serve --port 8080 --reload")
        print()
        print("    2. Ou instale no Python atual:")
        print(f"       {sys.executable} -m pip install -r requirements.txt")
        print()
        print("    3. Ou use o script pronto:")
        print("       ./serve.sh")
        return 1

    host = args.host or WEB_HOST
    port = args.port or WEB_PORT

    print("=" * 80)
    print("CAPACITY AGENT — DASHBOARD WEB")
    print("=" * 80)
    print()
    print(f"  Cluster.: {CLUSTER}")
    print(f"  Python..: {python_exe}")
    print(f"  URL.....: http://{host}:{port}")
    print(f"  Relatório: http://{host}:{port}/relatorio")
    print()
    print("  Pressione Ctrl+C para encerrar.")
    print()

    cmd = [
        python_exe,
        "-m",
        "uvicorn",
        "web.app:app",
        "--host",
        str(host),
        "--port",
        str(port),
    ]

    if args.reload:
        cmd.append("--reload")

    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0


def cmd_evaluate(args):

    print("=" * 80)
    print("CAPACITY AGENT — AVALIAÇÃO DO CLUSTER")
    print("=" * 80)
    print()
    print(f"Cluster: {CLUSTER}")
    print()

    print("[1/2] Coletando dados e executando análises...")

    report = run_evaluation(source="cli")
    evaluation_id = report["evaluation_id"]
    result = report
    report_path = f".capacity-agent/reports/{evaluation_id}.json"

    summary = result["summary"]
    health = result["health"]
    decision = result["decision"]

    print()
    print("[2/2] Resultado da avaliação")
    print()
    print(f"  Nodes................: {summary['nodes']}")
    print(f"  Pods.................: {summary['pods']}")
    print(f"  Node pools...........: {summary['node_pools']}")
    print(f"  Pods Pending.........: {summary['pending_pods']}")
    print(f"  Problemas scheduling.: {summary['scheduling_issues']}")
    print()
    print(f"  Cobertura métricas nodes: {health['node_coverage']}%")
    print(f"  Cobertura métricas pods.: {health['pod_coverage']}%")
    print(f"  Health OK..............: {'SIM' if health['decision_allowed'] else 'NÃO'}")
    print()
    print(f"  Recomendações geradas..: {summary['recommendations_count']}")
    print(f"  Executáveis............: {decision['executable_recommendations']}")
    print(f"  Decisão permitida......: {'SIM' if decision['allowed'] else 'NÃO'}")

    if decision["reasons"]:
        print()
        print("  Observações:")
        for reason in decision["reasons"]:
            print(f"    - {reason}")

    print()
    print("-" * 80)
    print("RECOMENDAÇÕES")
    print("-" * 80)

    for rec in result["recommendations"]:
        executable = rec["operation"]["executable"]
        tag = "EXECUTÁVEL" if executable else "MANUAL"

        print()
        print(f"  [{rec['severity']}] {rec['type']} ({tag})")
        print(f"  ID...........: {rec['id']}")
        print(f"  Fonte........: {rec['source']}")

        if rec.get("pool"):
            print(f"  Pool.........: {rec['pool']}")

        if rec.get("affected_pods"):
            print(f"  Pods afetados: {rec['affected_pods']}")

        print(f"  Ação.........: {rec['action']}")

        if executable:
            params = rec["operation"]["params"]
            print(
                f"  Operação.....: {rec['operation']['kind']} "
                f"({params.get('current_nodes')} → {params.get('target_nodes')} nodes)"
            )

        print(f"  Status.......: {rec['status']}")

    print()
    print("=" * 80)
    print("GATE DE APROVAÇÃO DEVOPS")
    print("=" * 80)
    print()
    print(f"  Approval required.....: {'SIM' if REQUIRE_APPROVAL else 'NÃO'}")
    print(f"  Auto execute..........: {'SIM' if AUTO_EXECUTE else 'NÃO'}")
    print()
    print("  Próximos passos:")
    print("    agent.py list                    — ver recomendações pendentes")
    print("    agent.py approve <id> --by <nome> — aprovar alteração")
    print("    agent.py reject <id> --by <nome>  — rejeitar alteração")
    print("    agent.py execute --dry-run        — simular execução")
    print("    agent.py execute --force          — executar aprovadas")
    print("    agent.py serve                    — iniciar dashboard web")
    print()
    print(f"  Relatório salvo em: {report_path}")
    print(f"  Evaluation ID......: {evaluation_id}")

    if args.json:
        print()
        print(json.dumps(report, indent=2, ensure_ascii=False))

    return 0


def cmd_list(args):

    status = args.status
    evaluation_id, items = list_by_status(status)

    print("=" * 80)
    print("RECOMENDAÇÕES")
    print("=" * 80)
    print()
    print(f"Evaluation ID: {evaluation_id or 'nenhuma avaliação'}")
    print(f"Filtro status: {status or 'todos'}")
    print()

    if not items:
        print("Nenhuma recomendação encontrada.")
        print("Execute: agent.py evaluate")
        return 0

    for rec in items:
        executable = rec["operation"]["executable"]
        tag = "EXECUTÁVEL" if executable else "MANUAL"

        print(f"[{rec['status'].upper()}] {rec['id']} — {rec['type']} ({tag})")
        print(f"  Severidade: {rec['severity']}")
        print(f"  Ação......: {rec['action']}")

        if rec.get("approved_by"):
            print(f"  Aprovado por: {rec['approved_by']} em {rec['approved_at']}")

        if rec.get("rejected_by"):
            print(f"  Rejeitado por: {rec['rejected_by']} — {rec.get('rejection_reason', '')}")

        print()

    return 0


def cmd_approve(args):

    result = approve(args.id, args.by)

    if not result["success"]:
        print(f"ERRO: {result['error']}")
        return 1

    item = result["item"]

    print("=" * 80)
    print("APROVAÇÃO REGISTRADA")
    print("=" * 80)
    print()
    print(f"  ID...........: {item['id']}")
    print(f"  Tipo.........: {item['type']}")
    print(f"  Aprovado por.: {item['approved_by']}")
    print(f"  Status.......: {item['status']}")
    print()
    print("  Para executar:")
    print(f"    agent.py execute --id {item['id']} --dry-run")
    print(f"    agent.py execute --id {item['id']} --force")

    return 0


def cmd_reject(args):

    result = reject(args.id, args.by, args.reason or "")

    if not result["success"]:
        print(f"ERRO: {result['error']}")
        return 1

    item = result["item"]

    print("=" * 80)
    print("REJEIÇÃO REGISTRADA")
    print("=" * 80)
    print()
    print(f"  ID...........: {item['id']}")
    print(f"  Tipo.........: {item['type']}")
    print(f"  Rejeitado por: {item['rejected_by']}")

    if args.reason:
        print(f"  Motivo.......: {args.reason}")

    return 0


def cmd_execute(args):

    _, items = list_by_status("approved")

    if args.id:
        items = [i for i in items if i["id"] == args.id]

    if not items:
        print("Nenhuma recomendação aprovada para execução.")
        print("Aprove primeiro: agent.py approve <id> --by <nome>")
        return 1

    print("=" * 80)
    print("EXECUÇÃO" + (" (DRY-RUN)" if args.dry_run else ""))
    print("=" * 80)
    print()

    executed = 0

    for item in items:

        allowed, reason = can_execute(item, force=args.force or args.dry_run)

        if not allowed and not args.dry_run:
            print(f"  SKIP {item['id']}: {reason}")
            continue

        print(f"  Executando: {item['id']} — {item['type']}")

        result = execute_operation(
            item["operation"],
            dry_run=args.dry_run,
        )

        if args.dry_run:
            print(f"    Preview: {result['output']}")
        else:
            status = "OK" if result["success"] else "FALHA"
            print(f"    Resultado: {status}")
            print(f"    Output: {result.get('output', '')[:200]}")
            mark_executed(item["id"], result)

        executed += 1
        print()

    if executed == 0:
        print("Nenhuma operação executada.")
        return 1

    return 0


def cmd_status(args):

    summary = gate_summary()

    print("=" * 80)
    print("STATUS DO AGENT")
    print("=" * 80)
    print()
    print(f"Cluster..............: {CLUSTER}")
    print(f"Evaluation ID........: {summary['evaluation_id'] or 'nenhuma'}")
    print(f"Última atualização...: {summary['updated_at'] or '-'}")
    print()
    print(f"Approval required....: {'SIM' if summary['require_approval'] else 'NÃO'}")
    print(f"Auto execute.........: {'SIM' if summary['auto_execute'] else 'NÃO'}")
    print()
    print("Recomendações por status:")

    for status, count in sorted(summary["counts"].items()):
        print(f"  {status:<12}: {count}")

    reports = list_reports()

    if reports:
        print()
        print("Últimas avaliações:")
        for report in reports[:5]:
            print(
                f"  {report['evaluation_id'][:8]}... "
                f"— {report['recommendations_count']} recs "
                f"— {report.get('created_at', '-')[:19]}"
            )

    return 0


def cmd_report(args):

    try:
        report = load_report(args.id)
    except FileNotFoundError:
        print(f"Relatório {args.id} não encontrado.")
        return 1

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Evaluation ID: {report['evaluation_id']}")
        print(f"Cluster.......: {report['cluster']}")
        print(f"Criado em.....: {report['created_at']}")
        print(f"Recomendações.: {len(report['recommendations'])}")
        print(f"Decisão.......: {'permitida' if report['decision']['allowed'] else 'bloqueada'}")

    return 0


def cmd_relatorio(args):

    reports = list_reports()

    if not reports:
        print("Nenhuma avaliação encontrada. Execute: agent.py evaluate")
        return 1

    evaluation_id = args.id or reports[0]["evaluation_id"]

    try:
        report = load_report(evaluation_id)
    except FileNotFoundError:
        print(f"Relatório {evaluation_id} não encontrado.")
        return 1

    if args.json:
        print(json.dumps(
            build_executive_report(summarize_report_for_api(report)),
            indent=2,
            ensure_ascii=False,
        ))
        return 0

    output = args.output or (
        f".capacity-agent/reports/executive-{evaluation_id[:8]}.html"
    )

    path = write_executive_html(report, output)
    executive = build_executive_report(summarize_report_for_api(report))

    print("=" * 80)
    print("RELATÓRIO EXECUTIVO GERADO")
    print("=" * 80)
    print()
    print(f"  Cluster........: {executive['meta']['cluster']}")
    print(f"  Status.........: {executive['status']['label']}")
    print(f"  Data...........: {executive['meta']['generated_at']}")
    print()
    print(f"  Arquivo HTML...: {path}")
    print()
    print("  Compartilhamento:")
    print(f"    • Dashboard web: http://localhost:{WEB_PORT}/relatorio")
    print("    • Exportar PDF.: Ctrl+P no navegador")

    return 0


def cmd_cenario_doc(args):

    md_path = args.input or "docs/cenario-ambiente-cluster.md"
    output = args.output

    try:
        path = write_cenario_html(md_path, output)
    except FileNotFoundError:
        print(f"Arquivo não encontrado: {md_path}")
        return 1
    except RuntimeError as exc:
        print(exc)
        return 1

    print("=" * 80)
    print("DOCUMENTO DE CENÁRIO — HTML GERADO")
    print("=" * 80)
    print()
    print(f"  Origem (MD)....: {md_path}")
    print(f"  Arquivo HTML...: {path}")
    print()
    print("  Exportar PDF:")
    print("    1. Abra o HTML no Chrome ou Edge")
    print("    2. Clique em 'Exportar PDF / Imprimir' (ou Ctrl+P)")
    print("    3. Destino: Salvar como PDF · Tamanho: A4 · Gráficos de fundo: ativado")
    print()
    print(f"  Caminho absoluto: {os.path.abspath(path)}")

    return 0


def cmd_collect(args):
    """Coletor in-cluster (modo agente): envia snapshots ao painel."""
    from collectors.snapshot import run_collector

    panel_url = args.panel_url or os.environ.get("CAPACITY_AGENT_PANEL_URL", "")
    token = os.environ.get("CAPACITY_AGENT_INGEST_TOKEN", "")
    interval = args.interval or int(os.environ.get("CAPACITY_AGENT_COLLECT_SECONDS", "900"))
    print(f"[collector] painel={panel_url or '(não definido)'} intervalo={interval}s once={args.once}", flush=True)
    return run_collector(panel_url, token, interval_seconds=interval, once=args.once)


def cmd_demo(args):
    """Ambiente de demonstração com dados fictícios (nunca usa um cluster real)."""
    from support.demo import DEMO_CLUSTER, DEMO_COMPANY, seed_demo

    result = seed_demo(email=args.email, password=args.password)
    print(f"Ambiente demo pronto: {DEMO_COMPANY} · cluster {DEMO_CLUSTER}")
    print(f"  Login: {result['email']}")
    if result["password"]:
        print(f"  Senha: {result['password']}   (guarde agora; não será exibida de novo)")
    else:
        print("  Conta já existia: use a mesma senha de antes (ou rode com --password para uma conta nova)")
    print("  Rode de novo quando quiser renovar os dados (o histórico de 7 dias é refeito).")
    return 0


def cmd_support_bundle(args):
    """Gera o pacote de suporte pela linha de comando (útil se o painel não abre)."""
    from support.bundle import build_bundle

    data = build_bundle()
    if args.output == "-":
        sys.stdout.buffer.write(data)
    else:
        with open(args.output, "wb") as handle:
            handle.write(data)
        print(f"Pacote de suporte gravado em {args.output} ({len(data) // 1024} KB)")
    return 0


def build_parser():

    parser = argparse.ArgumentParser(
        description=(
            "Capacity Agent — avalia o cluster GKE, recomenda ações "
            "e exige aprovação DevOps antes de executar alterações."
        ),
    )

    subparsers = parser.add_subparsers(dest="command")

    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="Avaliar cluster e gerar recomendações",
    )
    evaluate_parser.add_argument(
        "--json",
        action="store_true",
        help="Imprimir relatório completo em JSON",
    )

    list_parser = subparsers.add_parser(
        "list",
        help="Listar recomendações",
    )
    list_parser.add_argument(
        "--status",
        choices=["pending", "approved", "rejected", "executed", "failed"],
        help="Filtrar por status",
    )

    approve_parser = subparsers.add_parser(
        "approve",
        help="Aprovar recomendação (gate DevOps)",
    )
    approve_parser.add_argument("id", help="ID da recomendação")
    approve_parser.add_argument(
        "--by",
        required=True,
        help="Nome do analista DevOps que aprova",
    )

    reject_parser = subparsers.add_parser(
        "reject",
        help="Rejeitar recomendação",
    )
    reject_parser.add_argument("id", help="ID da recomendação")
    reject_parser.add_argument(
        "--by",
        required=True,
        help="Nome do analista DevOps que rejeita",
    )
    reject_parser.add_argument(
        "--reason",
        default="",
        help="Motivo da rejeição",
    )

    execute_parser = subparsers.add_parser(
        "execute",
        help="Executar recomendações aprovadas",
    )
    execute_parser.add_argument(
        "--id",
        help="Executar apenas uma recomendação específica",
    )
    execute_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simular execução sem alterar o cluster",
    )
    execute_parser.add_argument(
        "--force",
        action="store_true",
        help="Executar mesmo com AUTO_EXECUTE=False",
    )

    subparsers.add_parser(
        "status",
        help="Status do agent e gate de aprovação",
    )

    serve_parser = subparsers.add_parser(
        "serve",
        help="Iniciar dashboard web DevOps",
    )
    serve_parser.add_argument(
        "--host",
        default=None,
        help=f"Host (padrão: {WEB_HOST})",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Porta (padrão: {WEB_PORT})",
    )
    serve_parser.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload em desenvolvimento",
    )

    report_parser = subparsers.add_parser(
        "report",
        help="Visualizar relatório de avaliação",
    )
    report_parser.add_argument("id", help="Evaluation ID")
    report_parser.add_argument(
        "--json",
        action="store_true",
        help="Saída em JSON",
    )

    relatorio_parser = subparsers.add_parser(
        "relatorio",
        help="Gerar relatório executivo para gerentes",
    )
    relatorio_parser.add_argument(
        "--id",
        help="Evaluation ID (padrão: última avaliação)",
    )
    relatorio_parser.add_argument(
        "--output", "-o",
        help="Caminho do arquivo HTML de saída",
    )
    relatorio_parser.add_argument(
        "--json",
        action="store_true",
        help="Saída em JSON no terminal",
    )

    cenario_doc_parser = subparsers.add_parser(
        "cenario-doc",
        help="Gerar HTML do cenário do ambiente para PDF gerencial",
    )
    cenario_doc_parser.add_argument(
        "--input", "-i",
        help="Arquivo Markdown de entrada (padrão: docs/cenario-ambiente-cluster.md)",
    )
    cenario_doc_parser.add_argument(
        "--output", "-o",
        help="Arquivo HTML de saída (padrão: mesmo nome do .md com extensão .html)",
    )

    collect_parser = subparsers.add_parser(
        "collect",
        help="Coletor in-cluster: envia snapshots ao painel (token em CAPACITY_AGENT_INGEST_TOKEN)",
    )
    collect_parser.add_argument("--panel-url", help="URL do painel (ou CAPACITY_AGENT_PANEL_URL)")
    collect_parser.add_argument("--interval", type=int, help="Segundos entre envios (padrão 900)")
    collect_parser.add_argument("--once", action="store_true", help="Envia um snapshot e sai")

    demo_parser = subparsers.add_parser("demo", help="Criar/atualizar o ambiente de demonstração (dados fictícios)")
    demo_parser.add_argument("--email", default="demo@capacity-agent.local")
    demo_parser.add_argument("--password", default=None, help="Senha da conta demo (gerada se omitida)")

    bundle_parser = subparsers.add_parser("support-bundle", help="Gerar pacote de suporte (.zip sem segredos)")
    bundle_parser.add_argument("-o", "--output", default="capacity-agent-suporte.zip",
                               help="Arquivo de saída (use - para stdout)")

    return parser


def main():

    parser = build_parser()
    args = parser.parse_args()

    commands = {
        "evaluate": cmd_evaluate,
        "list": cmd_list,
        "approve": cmd_approve,
        "reject": cmd_reject,
        "execute": cmd_execute,
        "status": cmd_status,
        "serve": cmd_serve,
        "report": cmd_report,
        "relatorio": cmd_relatorio,
        "cenario-doc": cmd_cenario_doc,
        "collect": cmd_collect,
        "support-bundle": cmd_support_bundle,
        "demo": cmd_demo,
    }

    if args.command is None:
        parser.print_help()
        return 0

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
