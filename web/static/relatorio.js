async function fetchJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Erro ${res.status}`);
  return res.json();
}

function severityClass(value, warnAt, badAt) {
  if (value >= badAt) return "bad";
  if (value >= warnAt) return "warn";
  return "";
}

function renderReport(data) {
  const { meta, status, kpis, capacity_highlights, scheduling, recommendations, action_plan } = data;

  const pendingClass = kpis.pending_pods > 50 ? "bad" : kpis.pending_pods > 10 ? "warn" : "";
  const issuesClass = kpis.scheduling_issues > 50 ? "bad" : kpis.scheduling_issues > 20 ? "warn" : "";

  document.getElementById("report").innerHTML = `
    <header class="report-header">
      <div class="report-header-top">
        <span class="report-logo">Capacity Agent</span>
        <div class="status-badge ${status.level}">
          <span class="status-dot"></span>
          ${status.label}
        </div>
      </div>
      <h1 class="report-title">${meta.document_type}</h1>
      <p class="report-subtitle">Cluster ${meta.cluster} — Destinado a ${meta.audience}</p>
      <div class="report-meta">
        <div class="meta-item">
          <label>Data da Avaliação</label>
          <span>${meta.generated_at}</span>
        </div>
        <div class="meta-item">
          <label>Referência</label>
          <span>${meta.evaluation_id?.slice(0, 8) || "—"}…</span>
        </div>
        <div class="meta-item">
          <label>Monitoramento</label>
          <span>${kpis.health_ok ? "Operacional" : "Parcial — métricas incompletas"}</span>
        </div>
      </div>
    </header>

    <section class="report-section">
      <h2 class="section-title">Resumo Executivo</h2>
      <p class="section-text">${status.summary}</p>
      <p class="section-text" style="margin-top:12px">
        O cluster possui <strong>${kpis.nodes} nodes</strong> distribuídos em
        <strong>${kpis.node_pools} node pools</strong>, executando
        <strong>${kpis.pods} pods</strong>.
        ${kpis.pending_pods > 0
          ? `Atualmente <strong>${kpis.pending_pods} pods</strong> não conseguiram iniciar, o que pode impactar jobs e serviços.`
          : "Não há pods pendentes de inicialização."}
        ${kpis.recommendations_pending > 0
          ? ` Existem <strong>${kpis.recommendations_pending} ações</strong> aguardando análise da equipe DevOps, sendo <strong>${kpis.recommendations_high}</strong> de alta prioridade.`
          : ""}
      </p>
    </section>

    <section class="report-section">
      <h2 class="section-title">Indicadores Principais</h2>
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-value">${kpis.nodes}</div>
          <div class="kpi-label">Nodes</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-value">${kpis.pods}</div>
          <div class="kpi-label">Pods Totais</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-value ${pendingClass}">${kpis.pending_pods}</div>
          <div class="kpi-label">Pods Pendentes</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-value ${issuesClass}">${kpis.scheduling_issues}</div>
          <div class="kpi-label">Problemas Detectados</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-value">${kpis.node_pools}</div>
          <div class="kpi-label">Node Pools</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-value">${kpis.recommendations_total}</div>
          <div class="kpi-label">Recomendações</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-value ${kpis.recommendations_high > 0 ? "warn" : ""}">${kpis.recommendations_high}</div>
          <div class="kpi-label">Alta Prioridade</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-value">${kpis.pod_coverage}%</div>
          <div class="kpi-label">Cobertura Métricas</div>
        </div>
      </div>
    </section>

    <section class="report-section">
      <h2 class="section-title">Impactos Operacionais</h2>
      <div class="two-cols">
        <div>
          <h3 style="font-size:13px;margin-bottom:12px;color:var(--text-muted)">Principais Causas</h3>
          ${scheduling.causes.length ? `
            <table class="data-table">
              <thead><tr><th>Causa</th><th>Ocorrências</th></tr></thead>
              <tbody>
                ${scheduling.causes.map(c => `
                  <tr><td>${c.label}</td><td><strong>${c.count}</strong></td></tr>
                `).join("")}
              </tbody>
            </table>
          ` : `<p class="section-text">Nenhum impacto operacional identificado.</p>`}
        </div>
        <div>
          <h3 style="font-size:13px;margin-bottom:12px;color:var(--text-muted)">Áreas Mais Impactadas</h3>
          ${scheduling.namespaces.length ? `
            <table class="data-table">
              <thead><tr><th>Namespace</th><th>Problemas</th></tr></thead>
              <tbody>
                ${scheduling.namespaces.map(ns => `
                  <tr><td>${ns.namespace}</td><td><strong>${ns.total}</strong></td></tr>
                `).join("")}
              </tbody>
            </table>
          ` : `<p class="section-text">Nenhuma área com impacto significativo.</p>`}
        </div>
      </div>
    </section>

    <section class="report-section">
      <h2 class="section-title">Situação de Capacity</h2>
      ${capacity_highlights.length ? `
        <ul class="highlight-list">
          ${capacity_highlights.map(h => `
            <li class="highlight-item">
              <span class="highlight-severity ${h.severity}">${h.severity}</span>
              <div class="highlight-content">
                <strong>${h.pool} — ${h.label}</strong>
                <p>${h.detail}</p>
              </div>
            </li>
          `).join("")}
        </ul>
      ` : `<p class="section-text">Todos os node pools operam dentro dos limites esperados.</p>`}
    </section>

    <section class="report-section">
      <h2 class="section-title">Recomendações Prioritárias</h2>
      ${recommendations.length ? `
        <table class="data-table">
          <thead>
            <tr>
              <th>Prioridade</th>
              <th>Item</th>
              <th>Ação Recomendada</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            ${recommendations.map(r => `
              <tr>
                <td><span class="highlight-severity ${r.severity}">${r.severity}</span></td>
                <td>
                  <strong>${r.label}</strong>
                  ${r.pool ? `<br><small style="color:var(--text-muted)">Pool: ${r.pool}</small>` : ""}
                  ${r.affected_pods ? `<br><small style="color:var(--text-muted)">${r.affected_pods} pod(s) afetado(s)</small>` : ""}
                </td>
                <td>${r.action}</td>
                <td>${r.status === "pending" ? "Aguardando DevOps" : r.status}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      ` : `<p class="section-text">Nenhuma recomendação pendente nesta avaliação.</p>`}
    </section>

    <section class="report-section">
      <h2 class="section-title">Plano de Ação</h2>
      <ol class="action-steps">
        ${action_plan.next_steps.map(step => `<li>${step}</li>`).join("")}
      </ol>
    </section>

    <footer class="report-footer">
      Relatório gerado automaticamente pelo Capacity Agent em ${meta.generated_at}.<br>
      Documento informativo para gestão — alterações no ambiente requerem aprovação da equipe DevOps.
    </footer>
  `;
}

async function loadReportsList() {
  const data = await fetchJson("/api/reports");
  const select = document.getElementById("report-select");
  select.innerHTML = "";

  (data.reports || []).forEach((r, i) => {
    const opt = document.createElement("option");
    opt.value = r.evaluation_id;
    opt.textContent = `${r.created_at?.slice(0, 16).replace("T", " ") || "—"} — ${r.recommendations_count} rec.`;
    if (i === 0) opt.selected = true;
    select.appendChild(opt);
  });

  return select.value;
}

async function loadReport(evaluationId) {
  document.getElementById("loading").style.display = "block";
  document.getElementById("report").innerHTML = '<div class="loading" id="loading">Carregando relatório...</div>';

  try {
    const data = await fetchJson(
      evaluationId
        ? `/api/executive-report/${evaluationId}`
        : "/api/executive-report"
    );
    renderReport(data);
  } catch (e) {
    document.getElementById("report").innerHTML =
      `<div class="loading">Erro ao carregar relatório: ${e.message}</div>`;
  }
}

document.getElementById("btn-print").addEventListener("click", () => window.print());

document.getElementById("btn-refresh").addEventListener("click", async () => {
  const id = document.getElementById("report-select").value;
  await loadReport(id);
});

document.getElementById("report-select").addEventListener("change", (e) => {
  loadReport(e.target.value);
});

(async () => {
  try {
    const latestId = await loadReportsList();
    await loadReport(latestId);
  } catch (e) {
    document.getElementById("report").innerHTML =
      `<div class="loading">Nenhuma avaliação encontrada. Execute uma avaliação primeiro.</div>`;
  }
})();
