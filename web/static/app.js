const state = {
  status: null,
  user: null,
  clusters: [],
  selectedClusterId: "",
  cluster: null,
  clusterError: null,
  pods: [],
  podNamespaces: [],
  podTotal: 0,
  podError: null,
  podNamespace: "",
  podSearch: "",
  podRequestId: 0,
  podLogTarget: null,
  podLogRequestId: 0,
  recommendations: [],
  filterStatus: "",
  currentTab: "overview",
  selectedSchedulingNamespace: null,
};

const API = {
  async get(path) {
    const sep = path.includes("?") ? "&" : "?";
    const res = await fetch(`/api${path}${sep}_=${Date.now()}`, {
      headers: state.selectedClusterId ? { "X-Cluster-Id": state.selectedClusterId } : {},
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (res.status === 401) showAuthScreen();
      throw new Error(err.detail || `Erro ${res.status}`);
    }
    return res.json();
  },

  async post(path, body = {}) {
    const res = await fetch(`/api${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(state.selectedClusterId ? { "X-Cluster-Id": state.selectedClusterId } : {}),
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (res.status === 401) showAuthScreen();
      throw new Error(err.detail || `Erro ${res.status}`);
    }
    return res.json();
  },

  async patch(path, body = {}) {
    const res = await fetch(`/api${path}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        ...(state.selectedClusterId ? { "X-Cluster-Id": state.selectedClusterId } : {}),
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (res.status === 401) showAuthScreen();
      throw new Error(err.detail || `Erro ${res.status}`);
    }
    return res.json();
  },

  async delete(path) {
    const res = await fetch(`/api${path}`, {
      method: "DELETE",
      headers: state.selectedClusterId ? { "X-Cluster-Id": state.selectedClusterId } : {},
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (res.status === 401) showAuthScreen();
      throw new Error(err.detail || `Erro ${res.status}`);
    }
    return res.json();
  },
};

function showAuthScreen(message = "") {
  document.getElementById("auth-screen").classList.remove("hidden");
  document.getElementById("app-shell").classList.add("hidden");
  document.getElementById("auth-feedback").textContent = message;
}

const ROLE_RANK = { leitor: 1, operador: 2, admin: 3 };
function can(role) {
  return (ROLE_RANK[state.user?.role] || 0) >= ROLE_RANK[role];
}

function applyRoleUi() {
  document.getElementById("nav-users").classList.toggle("hidden", !can("admin"));
  document.getElementById("nav-support").classList.toggle("hidden", !can("operador"));
  document.getElementById("btn-support-bundle").classList.toggle("hidden", !can("admin"));
  const evaluate = document.getElementById("btn-evaluate");
  if (evaluate) evaluate.classList.toggle("hidden", !can("operador"));
  const clusterForm = document.getElementById("cluster-form");
  if (clusterForm) clusterForm.classList.toggle("hidden", !can("admin"));
  const agentForm = document.getElementById("agent-cluster-form");
  if (agentForm) agentForm.classList.toggle("hidden", !can("admin"));
}

function showApp(user) {
  state.user = user;
  if (state.inviteToken) {
    state.inviteToken = null;
    history.replaceState(null, "", "/");
  }
  applyRoleUi();
  document.getElementById("auth-screen").classList.add("hidden");
  document.getElementById("app-shell").classList.remove("hidden");
  document.getElementById("company-name").textContent = user.company_name;
  document.getElementById("header-company").textContent = user.company_name;
}

document.querySelectorAll("[data-auth-view]").forEach((tab) => {
  tab.addEventListener("click", () => {
    const isRegister = tab.dataset.authView === "register";
    document.querySelectorAll("[data-auth-view]").forEach((item) => {
      item.classList.toggle("active", item === tab);
    });
    document.getElementById("login-form").classList.toggle("hidden", isRegister);
    document.getElementById("register-form").classList.toggle("hidden", !isRegister);
    document.getElementById("auth-feedback").textContent = "";
  });
});

async function submitAuthForm(event, endpoint) {
  event.preventDefault();
  const feedback = document.getElementById("auth-feedback");
  feedback.textContent = "";
  const body = Object.fromEntries(new FormData(event.currentTarget));
  if (endpoint === "register" && state.inviteToken) {
    endpoint = "accept-invite";
    delete body.company_name;
    body.token = state.inviteToken;
  }
  try {
    const user = await API.post(`/auth/${endpoint}`, body);
    showApp(user);
    await refresh();
  } catch (error) {
    feedback.textContent = error.message;
  }
}

document.getElementById("login-form").addEventListener("submit", (event) => {
  submitAuthForm(event, "login");
});
document.getElementById("register-form").addEventListener("submit", (event) => {
  submitAuthForm(event, "register");
});
document.getElementById("btn-logout").addEventListener("click", async () => {
  try {
    await API.post("/auth/logout");
  } finally {
    state.user = null;
    state.clusters = [];
    state.selectedClusterId = "";
    showAuthScreen();
  }
});

function toast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function severityBadge(severity) {
  const cls = severity?.toLowerCase() || "medium";
  return `<span class="badge badge-${cls}">${severity || "—"}</span>`;
}

function statusBadge(status) {
  return `<span class="badge badge-${status}">${status}</span>`;
}

function barClass(pct) {
  if (pct >= 85) return "bad";
  if (pct >= 70) return "warn";
  return "ok";
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR");
}

function formatPct(val) {
  return val != null ? `${val}%` : "—";
}

function formatAge(isoDate) {
  if (!isoDate) return "—";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(isoDate).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  if (seconds < 31536000) return `${Math.floor(seconds / 86400)}d`;
  return `${Math.floor(seconds / 31536000)}y`;
}

// ── Navigation ──────────────────────────────────────────────

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    switchTab(btn.dataset.tab);
  });
});

document.querySelectorAll("[data-goto]").forEach((btn) => {
  btn.addEventListener("click", () => {
    switchTab(btn.dataset.goto);
  });
});

function switchTab(tab) {
  state.currentTab = tab;
  document.querySelectorAll(".nav-item").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tab);
  });
  document.querySelectorAll(".tab-panel").forEach((p) => {
    p.classList.toggle("active", p.id === `tab-${tab}`);
  });

  const titles = {
    overview: "Visão Geral",
    cluster: "Cluster",
    recommendations: "Recomendações",
    capacity: "Capacity",
    scheduling: "Scheduling",
    audit: "Auditoria",
    users: "Usuários",
    assistant: "Assistente IA",
    support: "Suporte",
  };
  document.getElementById("page-title").textContent = titles[tab] || tab;
  if (tab === "users" && can("admin")) {
    loadUsers().catch((e) => toast(e.message, "error"));
    loadCosts();
    loadAlertsConfig();
  }
  if (tab === "assistant") loadAssistantConfig().catch(() => {});
  if (tab === "support") loadSupportHealth();
  if (tab === "cluster" && state.selectedClusterId) {
    loadClusterPods().catch((error) => {
      state.podError = error.message;
      renderClusterPods();
    });
  }
}

// ── Filters ─────────────────────────────────────────────────

document.querySelectorAll(".filter-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.filterStatus = btn.dataset.status;
    await loadRecommendations();
  });
});

// ── Modal ───────────────────────────────────────────────────

const modalOverlay = document.getElementById("modal-overlay");

document.getElementById("modal-close").addEventListener("click", closeModal);
modalOverlay.addEventListener("click", (e) => {
  if (e.target === modalOverlay) closeModal();
});

function openModal(title, bodyHtml, footerHtml) {
  openModalWithSize(title, bodyHtml, footerHtml, false);
}

function openModalWithSize(title, bodyHtml, footerHtml, wide) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").innerHTML = bodyHtml;
  document.getElementById("modal-footer").innerHTML = footerHtml;
  document.querySelector(".modal").classList.toggle("modal-wide", wide);
  modalOverlay.classList.remove("hidden");
}

function closeModal() {
  modalOverlay.classList.add("hidden");
  state.podLogTarget = null;
  document.querySelector(".modal").classList.remove("modal-wide");
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !modalOverlay.classList.contains("hidden")) closeModal();
});

function recDetailHtml(rec) {
  const op = rec.operation || {};
  const params = op.params || {};
  let opHtml = "";

  if (op.executable && op.kind === "k8s_set_resources") {
    opHtml = `
      <dt>Operação</dt>
      <dd>Ajustar requests de ${escapeHtml(params.kind)}/${escapeHtml(params.name)} (container ${escapeHtml(params.container)}):
        CPU ${escapeHtml(params.current?.cpu || "—")} → ${escapeHtml(params.target?.cpu)},
        memória ${escapeHtml(params.current?.memory || "—")} → ${escapeHtml(params.target?.memory)}</dd>
    `;
  } else if (op.executable && op.kind === "k8s_scale") {
    opHtml = `<dt>Operação</dt><dd>Escalar ${escapeHtml(params.kind)}/${escapeHtml(params.name)}: ${params.current_replicas} → ${params.target_replicas} réplicas</dd>`;
  } else if (op.executable && op.kind === "k8s_create_hpa") {
    opHtml = `<dt>Operação</dt><dd>Criar HPA para ${escapeHtml(params.kind)}/${escapeHtml(params.name)}: min ${params.min_replicas}, max ${params.max_replicas}, alvo ${params.cpu_percent}% CPU</dd>`;
  } else if (op.executable && op.kind === "k8s_patch_hpa_max") {
    opHtml = `<dt>Operação</dt><dd>HPA ${escapeHtml(params.hpa)}: maxReplicas ${params.current_max} → ${params.target_max}</dd>`;
  } else if (op.executable) {
    opHtml = `
      <dt>Operação</dt>
      <dd>${op.kind} — ${params.current_nodes ?? "?"} → ${params.target_nodes ?? "?"} nodes</dd>
    `;
  }

  return `
    <dl class="rec-detail">
      <dt>Tipo</dt><dd>${rec.type}</dd>
      <dt>Severidade</dt><dd>${severityBadge(rec.severity)}</dd>
      <dt>Fonte</dt><dd>${rec.source}</dd>
      ${rec.pool ? `<dt>Pool</dt><dd>${rec.pool}</dd>` : ""}
      <dt>Ação</dt><dd>${rec.action}</dd>
      ${opHtml}
    </dl>
  `;
}

function showApproveModal(rec) {
  openModal(
    "Aprovar Recomendação",
    recDetailHtml(rec) + `
      <p class="muted">A aprovação será registrada no seu usuário autenticado.</p>
    `,
    `
      <button class="btn btn-ghost" onclick="closeModal()">Cancelar</button>
      <button class="btn btn-success" id="confirm-approve">Aprovar</button>
    `
  );

  document.getElementById("confirm-approve").addEventListener("click", async () => {
    try {
      await API.post(`/recommendations/${rec.id}/approve`, {});
      toast("Recomendação aprovada", "success");
      closeModal();
      await refresh();
    } catch (e) {
      toast(e.message, "error");
    }
  });
}

function showRejectModal(rec) {
  openModal(
    "Rejeitar Recomendação",
    recDetailHtml(rec) + `
      <div class="form-group">
        <label>Motivo (opcional)</label>
        <textarea id="input-reason" placeholder="Motivo da rejeição"></textarea>
      </div>
    `,
    `
      <button class="btn btn-ghost" onclick="closeModal()">Cancelar</button>
      <button class="btn btn-danger" id="confirm-reject">Rejeitar</button>
    `
  );

  document.getElementById("confirm-reject").addEventListener("click", async () => {
    const reason = document.getElementById("input-reason").value.trim();
    try {
      await API.post(`/recommendations/${rec.id}/reject`, { reason });
      toast("Recomendação rejeitada", "success");
      closeModal();
      await refresh();
    } catch (e) {
      toast(e.message, "error");
    }
  });
}

function showExecuteModal(rec, dryRun = false) {
  openModal(
    dryRun ? "Simular Execução" : "Executar Alteração",
    recDetailHtml(rec) + `
      <p style="font-size:13px;color:var(--text-muted)">
        ${dryRun
          ? "Nenhuma alteração será feita no cluster."
          : "Esta ação irá alterar o cluster. Confirme com cuidado."}
      </p>
    `,
    `
      <button class="btn btn-ghost" onclick="closeModal()">Cancelar</button>
      <button class="btn ${dryRun ? "btn-ghost" : "btn-primary"}" id="confirm-execute">
        ${dryRun ? "Simular" : "Executar"}
      </button>
    `
  );

  document.getElementById("confirm-execute").addEventListener("click", async () => {
    try {
      const result = await API.post(`/recommendations/${rec.id}/execute`, {
        dry_run: dryRun,
        force: true,
      });
      toast(
        dryRun
          ? (result.success ? "Simulação validada pelo cluster" : "Simulação falhou")
          : (result.success ? "Execução concluída" : "Execução falhou"),
        result.success ? "success" : "error"
      );
      const r = result.result || {};
      openModal(
        dryRun ? "Resultado da simulação" : "Resultado da execução",
        `<dl class="rec-detail">
           <dt>Comando</dt><dd class="mono">${escapeHtml(r.command || "—")}</dd>
           <dt>Saída</dt><dd class="mono">${escapeHtml(r.output || "—")}</dd>
           ${r.rollback_command ? `<dt>Como reverter</dt><dd class="mono">${escapeHtml(r.rollback_command)}</dd>` : ""}
         </dl>`,
        `<button class="btn btn-primary" onclick="closeModal()">Fechar</button>`
      );
      await refresh();
    } catch (e) {
      toast(e.message, "error");
    }
  });
}

// ── Render ──────────────────────────────────────────────────

function renderOverview() {
  const report = state.status?.latest_report;
  const gate = state.status?.gate || {};
  const counts = gate.counts || {};
  const summary = report?.summary || {};

  document.getElementById("overview-cards").innerHTML = `
    <div class="card">
      <div class="card-label">Nodes</div>
      <div class="card-value">${summary.nodes ?? "—"}</div>
      <div class="card-sub" title="Pools com nodes registrados no cluster (API Kubernetes)">${summary.node_pools ?? 0} node pools ativos no cluster</div>
    </div>
    <div class="card">
      <div class="card-label">Pods</div>
      <div class="card-value">${summary.pods ?? "—"}</div>
      <div class="card-sub">${summary.pending_pods ?? 0} pending</div>
    </div>
    <div class="card">
      <div class="card-label">Pendentes</div>
      <div class="card-value warn">${counts.pending ?? 0}</div>
      <div class="card-sub">aguardando aprovação</div>
    </div>
    <div class="card">
      <div class="card-label">Aprovadas</div>
      <div class="card-value ok">${counts.approved ?? 0}</div>
      <div class="card-sub">prontas para execução</div>
    </div>
    <div class="card">
      <div class="card-label">Problemas</div>
      <div class="card-value ${summary.scheduling_issues > 0 ? "bad" : "ok"}">
        ${summary.scheduling_issues ?? 0}
      </div>
      <div class="card-sub">scheduling issues</div>
    </div>
    <div class="card">
      <div class="card-label">Recomendações</div>
      <div class="card-value">${summary.recommendations_count ?? 0}</div>
      <div class="card-sub">última avaliação</div>
    </div>
    <div class="card">
      <div class="card-label">Economia potencial</div>
      <div class="card-value ok">${summary.cost_settings && (summary.cost_settings.cpu_month || summary.cost_settings.gb_month)
        ? formatBRL(summary.estimated_savings_monthly || 0) : "—"}</div>
      <div class="card-sub">${summary.cost_settings && (summary.cost_settings.cpu_month || summary.cost_settings.gb_month)
        ? "por mês, recomendações abertas" : "configure custos em Usuários"}</div>
    </div>
  `;
  renderConnectionSummary();
  loadLicense();
  renderNodesUsage();
  renderRoadmap();

  const health = report?.health;
  if (health) {
    document.getElementById("health-checks").innerHTML = (health.checks || []).map((c) => `
      <div class="metric-bar">
        <div class="metric-bar-header">
          <span>${c.type.replace("_", " ")}</span>
          <span class="${c.status === "OK" ? "decision-ok" : "decision-blocked"}">
            ${c.coverage}% — ${c.status}
          </span>
        </div>
        <div class="metric-bar-track">
          <div class="metric-bar-fill ${c.status === "OK" ? "ok" : "bad"}" style="width:${Math.min(c.coverage, 100)}%"></div>
        </div>
      </div>
    `).join("");
  } else {
    document.getElementById("health-checks").innerHTML =
      `<div class="empty-state"><p>Execute uma avaliação para ver health checks</p></div>`;
  }

  const decision = report?.decision;
  if (decision) {
    const reasons = (decision.reasons || []).map((r) => `<li>${r}</li>`).join("");
    document.getElementById("decision-panel").innerHTML = `
      <p class="${decision.allowed ? "decision-ok" : "decision-blocked"}" style="font-weight:600">
        ${decision.allowed ? "✓ Decisão permitida" : "✗ Decisão bloqueada"}
      </p>
      ${reasons ? `<ul class="reason-list">${reasons}</ul>` : ""}
      <p style="margin-top:12px;font-size:12px;color:var(--text-muted)">
        Executáveis: ${decision.executable_recommendations ?? 0} |
        HIGH severity: ${decision.high_severity_count ?? 0}
      </p>
    `;
  } else {
    document.getElementById("decision-panel").innerHTML =
      `<div class="empty-state"><p>Sem dados de decisão</p></div>`;
  }

  const pending = state.recommendations.filter((r) => r.status === "pending").slice(0, 5);
  if (pending.length) {
    document.getElementById("pending-preview").innerHTML = buildRecTable(pending, true);
  } else {
    document.getElementById("pending-preview").innerHTML =
      `<div class="empty-state"><p>Nenhuma recomendação pendente</p></div>`;
  }
}

function renderConnectionSummary() {
  const element = document.getElementById("overview-connection");
  const active = state.clusters.find((cluster) => cluster.id === state.selectedClusterId);
  if (!active) {
    element.innerHTML = `
      <div class="connection-summary-copy">
        <span class="connection-summary-label">Conexão ativa</span>
        <strong>Nenhum cluster selecionado</strong>
      </div>
      <button class="btn btn-ghost btn-sm" data-goto="cluster">Cadastrar conexão</button>
    `;
    element.querySelector("[data-goto]").addEventListener("click", () => switchTab("cluster"));
    return;
  }

  const nodes = state.cluster?.nodes || [];
  const ready = nodes.filter((node) => node.status === "Ready").length;
  const connectionStatus = state.clusterError
    ? "Falha na conexão"
    : nodes.length ? `${ready}/${nodes.length} nodes Ready` : "Conectando...";
  element.innerHTML = `
    <div class="connection-summary-copy">
      <span class="connection-summary-label">Conexão ativa</span>
      <strong>${escapeHtml(active.name)}</strong>
      <span>${escapeHtml(active.context_name)} · ${escapeHtml(connectionStatus)}</span>
    </div>
    <button class="btn btn-ghost btn-sm" data-goto="cluster">Gerenciar conexões</button>
  `;
  element.querySelector("[data-goto]").addEventListener("click", () => switchTab("cluster"));
}

function buildRecTable(items, compact = false) {
  if (!items.length) {
    return `<div class="empty-state"><p>Nenhuma recomendação encontrada</p></div>`;
  }

  const actionCol = compact ? "" : "<th>Ações</th>";

  const rows = items.map((rec) => {
    const executable = rec.operation?.executable;
    const tag = executable
      ? `<span class="badge badge-approved">EXECUTÁVEL</span>`
      : `<span class="badge badge-manual">MANUAL</span>`;

    let actions = "";
    if (!compact) {
      const btns = [];
      if (rec.status === "pending" && executable && can("operador")) {
        btns.push(`<button class="btn btn-success btn-sm" data-action="approve" data-id="${rec.id}">Aprovar</button>`);
      }
      if (rec.status === "pending" && can("operador")) {
        btns.push(`<button class="btn btn-danger btn-sm" data-action="reject" data-id="${rec.id}">Rejeitar</button>`);
      }
      if (rec.status === "approved" && executable && can("operador")) {
        btns.push(`<button class="btn btn-ghost btn-sm" data-action="dry-run" data-id="${rec.id}">Simular</button>`);
      }
      if (rec.status === "approved" && executable && can("admin")) {
        btns.push(`<button class="btn btn-primary btn-sm" data-action="execute" data-id="${rec.id}">Executar</button>`);
      }
      actions = `<td><div class="actions-cell">${btns.join("")}</div></td>`;
    }

    return `
      <tr>
        <td>${statusBadge(rec.status)}</td>
        <td>${severityBadge(rec.severity)}</td>
        <td class="mono">${rec.id}</td>
        <td>${rec.type}</td>
        <td>${escapeHtml(rec.pool || "—")}</td>
        <td>${tag}</td>
        <td style="max-width:280px">${escapeHtml(rec.action)}</td>
        ${actions}
      </tr>
    `;
  }).join("");

  return `
    <table>
      <thead>
        <tr>
          <th>Status</th><th>Severidade</th><th>ID</th><th>Tipo</th>
          <th>Pool</th><th>Modo</th><th>Ação</th>${actionCol}
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderRecommendations() {
  const el = document.getElementById("recommendations-table");
  el.innerHTML = buildRecTable(state.recommendations);

  el.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const rec = state.recommendations.find((r) => r.id === btn.dataset.id);
      if (!rec) return;
      const action = btn.dataset.action;
      if (action === "approve") showApproveModal(rec);
      else if (action === "reject") showRejectModal(rec);
      else if (action === "execute") showExecuteModal(rec, false);
      else if (action === "dry-run") showExecuteModal(rec, true);
    });
  });
}

function renderCapacity() {
  const capacity = state.status?.latest_report?.capacity || {};
  const reportDate = state.status?.latest_report?.created_at;

  const evalHint = document.getElementById("capacity-eval-time");
  if (evalHint) {
    evalHint.textContent = reportDate
      ? `Dados de ${formatDate(reportDate)}`
      : "";
  }

  const pools = Object.values(capacity).sort((a, b) =>
    (a.pool || "").localeCompare(b.pool || "")
  );

  if (!pools.length) {
    document.getElementById("capacity-table").innerHTML =
      `<div class="empty-state"><p>Sem dados de capacity — execute Nova Avaliação</p></div>`;
    return;
  }

  const rows = pools.map((p) => {
    const m = p.metrics || {};
    const c = p.capacity || {};
    const gke = p.gke || {};
    const kubernetes = p.kubernetes || {};
    const nodes = c.node_count ?? gke.actual_nodes ?? 0;
    const configured = gke.configured_nodes ?? nodes;
    const status = gke.status || kubernetes.status || "—";
    const version = gke.version || kubernetes.version || "—";
    const machine = gke.machine_type || kubernetes.machine_type || "—";
    const statusClass = ["RUNNING", "Ready"].includes(status) ? "badge-executed" : "badge-pending";
    const statusLabel = status === "RUNNING" ? "Ok" : status;

    return `
      <tr>
        <td><strong>${p.pool}</strong></td>
        <td><span class="badge ${statusClass}">${statusLabel}</span></td>
        <td class="mono" style="font-size:12px">${version !== "—" ? version : "—"}</td>
        <td style="font-size:12px">${machine}</td>
        <td><strong>${nodes}</strong>${configured !== nodes ? ` <span style="color:var(--text-muted);font-size:11px">(GKE: ${configured})</span>` : ""}</td>
        <td>${c.pod_count ?? 0}</td>
        <td>
          <div class="metric-bar" style="margin:0">
            <div class="metric-bar-header"><span>CPU usage</span><span>${formatPct(m.cpu_usage_vs_alloc_pct)}</span></div>
            <div class="metric-bar-track"><div class="metric-bar-fill ${barClass(m.cpu_usage_vs_alloc_pct)}" style="width:${Math.min(m.cpu_usage_vs_alloc_pct||0,100)}%"></div></div>
          </div>
        </td>
        <td>
          <div class="metric-bar" style="margin:0">
            <div class="metric-bar-header"><span>CPU requests</span><span>${formatPct(m.cpu_req_vs_alloc_pct)}</span></div>
            <div class="metric-bar-track"><div class="metric-bar-fill ${barClass(m.cpu_req_vs_alloc_pct)}" style="width:${Math.min(m.cpu_req_vs_alloc_pct||0,100)}%"></div></div>
          </div>
        </td>
        <td>
          <div class="metric-bar" style="margin:0">
            <div class="metric-bar-header"><span>Mem usage</span><span>${formatPct(m.mem_usage_vs_alloc_pct)}</span></div>
            <div class="metric-bar-track"><div class="metric-bar-fill ${barClass(m.mem_usage_vs_alloc_pct)}" style="width:${Math.min(m.mem_usage_vs_alloc_pct||0,100)}%"></div></div>
          </div>
        </td>
        <td>
          <div class="metric-bar" style="margin:0">
            <div class="metric-bar-header"><span>Mem requests</span><span>${formatPct(m.mem_req_vs_alloc_pct)}</span></div>
            <div class="metric-bar-track"><div class="metric-bar-fill ${barClass(m.mem_req_vs_alloc_pct)}" style="width:${Math.min(m.mem_req_vs_alloc_pct||0,100)}%"></div></div>
          </div>
        </td>
      </tr>
    `;
  }).join("");

  document.getElementById("capacity-table").innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Pool</th><th>Status</th><th>Versão</th><th>Máquina</th>
          <th>Nodes</th><th>Pods</th>
          <th>CPU Usage</th><th>CPU Requests</th>
          <th>Mem Usage</th><th>Mem Requests</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderScheduling() {
  const sched = state.status?.latest_report?.scheduling || {};
  const causes = sched.causes || {};
  const maxCause = Math.max(...Object.values(causes), 1);

  const causeEntries = Object.entries(causes).sort((a, b) => b[1] - a[1]);
  document.getElementById("scheduling-causes").innerHTML = causeEntries.length
    ? causeEntries.map(([cause, count]) => `
        <div class="cause-row">
          <span class="cause-label" title="${cause}">${cause}</span>
          <div class="cause-bar-wrap">
            <div class="cause-bar" style="width:${(count / maxCause) * 100}%">${count}</div>
          </div>
        </div>
      `).join("")
    : `<div class="empty-state"><p>Sem problemas de scheduling</p></div>`;

  const namespaces = sched.namespaces || {};
  const findingsByNs = sched.findings_by_namespace || {};
  const nsEntries = Object.entries(namespaces).sort(
    (a, b) => Object.values(b[1]).reduce((s, v) => s + v, 0) - Object.values(a[1]).reduce((s, v) => s + v, 0)
  );

  const nsContainer = document.getElementById("scheduling-namespaces");

  if (!nsEntries.length) {
    nsContainer.innerHTML = `<div class="empty-state"><p>Sem namespaces impactados</p></div>`;
  } else {
    nsContainer.innerHTML = nsEntries.slice(0, 15).map(([ns, counter]) => {
      const total = Object.values(counter).reduce((s, v) => s + v, 0);
      const podCount = (findingsByNs[ns] || []).length;
      const details = Object.entries(counter).map(([c, n]) => `${c}=${n}`).join(", ");
      const isActive = state.selectedSchedulingNamespace === ns;

      return `
        <div class="ns-item ${isActive ? "active" : ""}" data-namespace="${ns}" role="button" tabindex="0">
          <div class="ns-item-header">
            <strong>${ns}</strong>
            <span class="ns-item-count">${podCount || total} pod(s)</span>
            <span class="ns-item-chevron">›</span>
          </div>
          <div class="ns-item-details">${details}</div>
        </div>
      `;
    }).join("");

    nsContainer.querySelectorAll(".ns-item").forEach((el) => {
      el.addEventListener("click", () => selectSchedulingNamespace(el.dataset.namespace));
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          selectSchedulingNamespace(el.dataset.namespace);
        }
      });
    });
  }

  renderSchedulingPods();
}

function selectSchedulingNamespace(namespace) {
  state.selectedSchedulingNamespace = namespace;
  renderScheduling();

  const podsPanel = document.getElementById("scheduling-pods");
  podsPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function clearSchedulingNamespaceFilter() {
  state.selectedSchedulingNamespace = null;
  renderScheduling();
}

function buildPodsTable(findings, showNamespace = false) {
  if (!findings.length) {
    return `<div class="empty-state"><p>Nenhum pod com problema neste namespace</p></div>`;
  }

  const nsCol = showNamespace ? "<th>Namespace</th>" : "";

  const rows = findings.map((f) => {
    const nsCell = showNamespace
      ? `<td class="mono">${f.namespace}</td>`
      : "";
    const message = f.message
      ? `<div class="pod-message" title="${escapeHtml(f.message)}">${escapeHtml(f.message)}</div>`
      : "";

    return `
      <tr>
        ${nsCell}
        <td>
          <span class="mono">${escapeHtml(f.pod)}</span>
          ${message}
        </td>
        <td>${f.cause}</td>
        <td>${severityBadge(f.severity)}</td>
        <td style="max-width:320px">${escapeHtml(f.action)}</td>
      </tr>
    `;
  }).join("");

  return `
    <table>
      <thead>
        <tr>
          ${nsCol}
          <th>Pod</th><th>Causa</th><th>Severidade</th><th>Ação</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderSchedulingPods() {
  const sched = state.status?.latest_report?.scheduling || {};
  const findingsByNs = sched.findings_by_namespace || {};
  const selected = state.selectedSchedulingNamespace;

  const titleEl = document.getElementById("scheduling-pods-title");
  const clearBtn = document.getElementById("scheduling-clear-filter");
  const podsEl = document.getElementById("scheduling-pods");

  if (selected) {
    const findings = findingsByNs[selected] || [];
    titleEl.textContent = `Pods com Problema — ${selected} (${findings.length})`;
    clearBtn.classList.remove("hidden");
    podsEl.innerHTML = buildPodsTable(findings, false);
  } else {
    const findings = sched.top_findings || [];
    titleEl.textContent = findings.length
      ? `Top Pods com Problema (${findings.length})`
      : "Pods com Problema";
    clearBtn.classList.add("hidden");
    podsEl.innerHTML = buildPodsTable(findings, true);
  }
}

document.getElementById("scheduling-clear-filter").addEventListener("click", clearSchedulingNamespaceFilter);

function renderAudit(entries) {
  document.getElementById("audit-log").innerHTML = entries.length
    ? entries.map((e) => `
        <div class="audit-entry">
          <span class="audit-time">${formatDate(e.timestamp)}</span>
          <span class="audit-event ${escapeHtml(e.event)}">${escapeHtml(e.event)}</span>
          <span class="audit-details">${escapeHtml(JSON.stringify(e.details))}</span>
        </div>
      `).join("")
    : `<div class="empty-state"><p>Nenhum evento registrado</p></div>`;
}

function renderAll() {
  renderOverview();
  renderCluster();
  renderClusterPods();
  renderRecommendations();
  renderCapacity();
  renderScheduling();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function renderCluster() {
  const connection = document.getElementById("cluster-connection");
  const table = document.getElementById("cluster-nodes");
  if (state.clusterError) {
    connection.textContent = state.clusterError;
    table.innerHTML = `<div class="empty-state"><p>Sem dados de nodes</p></div>`;
    return;
  }
  if (!state.cluster) {
    connection.textContent = "Carregando conexão com o cluster...";
    table.innerHTML = "";
    return;
  }

  connection.textContent = `Conectado ao contexto ${state.cluster.context} · ${state.cluster.nodes.length} nodes`;
  table.innerHTML = state.cluster.nodes.length
    ? `<table><thead><tr><th>Node</th><th>Status</th><th>Role</th><th>Versão</th></tr></thead><tbody>${state.cluster.nodes.map((node) => `
        <tr><td class="mono">${escapeHtml(node.name)}</td><td>${escapeHtml(node.status)}</td>
        <td>${escapeHtml(node.roles.join(", "))}</td><td>${escapeHtml(node.version)}</td></tr>
      `).join("")}</tbody></table>`
    : `<div class="empty-state"><p>Nenhum node encontrado</p></div>`;
}

function renderClusterPods() {
  const container = document.getElementById("cluster-pods");
  const count = document.getElementById("pod-count");
  if (!state.selectedClusterId) {
    count.textContent = "—";
    container.innerHTML = `<div class="empty-state"><p>Selecione um cluster para consultar os pods</p></div>`;
    return;
  }
  if (state.podError) {
    count.textContent = "—";
    container.innerHTML = `<div class="empty-state"><p>${escapeHtml(state.podError)}</p></div>`;
    return;
  }

  const search = state.podSearch.trim().toLowerCase();
  const pods = state.pods.filter((pod) => !search || pod.name.toLowerCase().includes(search));
  count.textContent = `${pods.length} / ${state.podTotal}`;
  container.innerHTML = pods.length
    ? `<table><thead><tr><th>Namespace</th><th>Pod</th><th>Ready</th><th>Status</th><th>Reinícios</th><th>Idade</th></tr></thead><tbody>${pods.map((pod) => {
        const statusClass = pod.status === "Running"
          ? "pod-status-running"
          : pod.status === "Completed"
            ? "pod-status-completed"
            : "pod-status-attention";
        return `<tr>
          <td>${escapeHtml(pod.namespace)}</td>
          <td><div class="pod-name-cell">
            <span class="mono">${escapeHtml(pod.name)}</span>
            <button class="btn btn-primary btn-sm" type="button"
              data-pod-logs="${escapeHtml(pod.name)}"
              data-pod-namespace="${escapeHtml(pod.namespace)}"
              aria-label="Ver logs do pod ${escapeHtml(pod.name)}">Ver logs</button>
          </div></td>
          <td>${escapeHtml(pod.ready)}</td>
          <td><span class="pod-status ${statusClass}">${escapeHtml(pod.status)}</span></td>
          <td class="${pod.restarts ? "pod-restarts" : ""}">${pod.restarts}</td>
          <td>${formatAge(pod.created_at)}</td>
        </tr>`;
      }).join("")}</tbody></table>`
    : `<div class="empty-state"><p>${search ? "Nenhum pod corresponde à busca" : "Nenhum pod encontrado neste namespace"}</p></div>`;
}

function openPodLogs(pod) {
  state.podLogTarget = {
    namespace: pod.namespace,
    name: pod.name,
    containers: [...(pod.containers || []), ...(pod.init_containers || [])],
    previous: false,
  };
  const target = state.podLogTarget;
  const containerOptions = target.containers.length
    ? target.containers.map((name, index) =>
      `<option value="${escapeHtml(name)}">${escapeHtml(name)}${index >= (pod.containers || []).length ? " (init)" : ""}</option>`
    ).join("")
    : `<option value="">Container padrão</option>`;
  openModalWithSize(
    `Logs · ${pod.name}`,
    `<p class="pod-log-context">${escapeHtml(pod.namespace)} · ${escapeHtml(pod.status)} · ${pod.restarts} reinício(s)</p>
    <div class="pod-log-toolbar">
      <label for="pod-log-container">Container</label>
      <select id="pod-log-container">${containerOptions}</select>
      <button class="btn btn-ghost btn-sm" type="button" data-pod-log-toggle-previous>Ver logs anteriores</button>
      <button class="btn btn-primary btn-sm" type="button" data-pod-log-refresh>Atualizar logs</button>
    </div>
    <p class="pod-log-hint" id="pod-log-status">Buscando as últimas linhas...</p>
    <pre class="pod-log-output" id="pod-log-output" aria-live="polite"></pre>
    <p class="pod-log-security-hint">Os logs podem conter dados sensíveis. A exibição é limitada às últimas 200 linhas e 256 KB.</p>`,
    `<button class="btn btn-ghost" type="button" id="pod-log-close">Fechar</button>`,
    true,
  );
  document.getElementById("pod-log-close").addEventListener("click", closeModal);
  loadPodLogs();
}

async function loadPodLogs() {
  const target = state.podLogTarget;
  if (!target) return;
  const requestId = ++state.podLogRequestId;
  const status = document.getElementById("pod-log-status");
  const output = document.getElementById("pod-log-output");
  const container = document.getElementById("pod-log-container")?.value || "";
  status.textContent = "Buscando as últimas linhas...";
  output.textContent = "";
  const query = new URLSearchParams({
    namespace: target.namespace,
    pod: target.name,
    previous: String(target.previous),
  });
  if (container) query.set("container", container);
  try {
    const result = await API.get(`/cluster/pod-logs?${query.toString()}`);
    if (requestId !== state.podLogRequestId || target !== state.podLogTarget) return;
    output.textContent = result.logs || "(O pod não gerou logs para esta consulta.)";
    status.textContent = result.truncated
      ? "Exibindo até 200 linhas ou 256 KB. O resultado pode estar truncado."
      : `${target.previous ? "Logs da execução anterior" : "Logs atuais"} · máximo de 200 linhas`;
  } catch (error) {
    if (requestId !== state.podLogRequestId || target !== state.podLogTarget) return;
    status.textContent = `Não foi possível carregar os logs: ${error.message}`;
  }
}

// ── Data loading ────────────────────────────────────────────

async function loadStatus() {
  state.status = await API.get("/status");
  document.getElementById("company-name").textContent = state.status.company_name || state.user?.company_name || "";
  document.getElementById("header-company").textContent = state.status.company_name || state.user?.company_name || "";
  const activeCluster = state.clusters.find((item) => item.id === state.selectedClusterId);
  document.getElementById("cluster-name").textContent = activeCluster
    ? `${activeCluster.name} · ${activeCluster.mode === "agent"
        ? `agente${activeCluster.last_seen_at ? " · último envio " + formatDate(activeCluster.last_seen_at) : " · aguardando primeiro envio"}`
        : activeCluster.context_name}`
    : "Cluster não selecionado";
  document.getElementById("btn-rotate-token").classList.toggle(
    "hidden", !(activeCluster?.mode === "agent" && can("admin"))
  );

  const reportDate = state.status.latest_report?.created_at;
  const gateDate = state.status.gate?.updated_at;
  const displayDate = reportDate || gateDate;

  document.getElementById("last-update").textContent =
    displayDate
      ? `Avaliação: ${formatDate(displayDate)}`
      : "Sem avaliação";
}

async function loadCluster() {
  if (!state.selectedClusterId) {
    state.cluster = null;
    state.clusterError = "Cadastre ou selecione um cluster para consultar os nodes.";
    renderCluster();
    return;
  }
  try {
    state.cluster = await API.get("/cluster");
    state.clusterError = null;
  } catch (error) {
    state.cluster = null;
    state.clusterError = error.message;
  }
  renderCluster();
}

async function loadClusterPods() {
  const requestId = ++state.podRequestId;
  if (!state.selectedClusterId) {
    state.pods = [];
    state.podNamespaces = [];
    state.podTotal = 0;
    state.podError = null;
    renderClusterPods();
    return;
  }

  const query = state.podNamespace
    ? `?namespace=${encodeURIComponent(state.podNamespace)}`
    : "";
  try {
    const result = await API.get(`/cluster/pods${query}`);
    if (requestId !== state.podRequestId) return;
    state.pods = result.pods || [];
    state.podNamespaces = result.namespaces || [];
    state.podTotal = result.total ?? state.pods.length;
    state.podError = null;
    if (state.podNamespace && !state.podNamespaces.includes(state.podNamespace)) {
      state.podNamespace = "";
      return loadClusterPods();
    }
    const selector = document.getElementById("pod-namespace-filter");
    selector.innerHTML = `<option value="">Todos os namespaces</option>${state.podNamespaces.map((namespace) =>
      `<option value="${escapeHtml(namespace)}">${escapeHtml(namespace)}</option>`
    ).join("")}`;
    selector.value = state.podNamespace;
  } catch (error) {
    if (requestId !== state.podRequestId) return;
    state.pods = [];
    state.podError = error.message;
  }
  renderClusterPods();
}

async function loadClusters() {
  const result = await API.get("/clusters");
  state.clusters = result.clusters || [];
  if (!state.clusters.some((cluster) => cluster.id === state.selectedClusterId)) {
    state.selectedClusterId = state.clusters[0]?.id || "";
  }
  const selector = document.getElementById("cluster-selector");
  selector.innerHTML = `<option value="">Nenhum cluster</option>${state.clusters.map((cluster) =>
    `<option value="${escapeHtml(cluster.id)}">${escapeHtml(cluster.name)} · ${cluster.mode === "agent" ? "agente" : escapeHtml(cluster.context_name)}</option>`
  ).join("")}`;
  selector.value = state.selectedClusterId;
  const activeCluster = state.clusters.find((item) => item.id === state.selectedClusterId);
  document.getElementById("cluster-name").textContent = activeCluster
    ? `${activeCluster.name} · ${activeCluster.context_name}`
    : "Cluster não selecionado";
}

async function loadRecommendations() {
  if (!state.selectedClusterId) {
    state.recommendations = [];
    return;
  }
  const path = state.filterStatus
    ? `/recommendations?status=${state.filterStatus}`
    : "/recommendations";
  const data = await API.get(path);
  state.recommendations = data.items || [];
}

async function loadAudit() {
  const data = await API.get("/audit?limit=50");
  renderAudit(data.entries || []);
}

async function refresh() {
  await loadStatus();
  await loadClusters();
  await loadCluster();
  if (state.currentTab === "cluster") await loadClusterPods();
  await loadRecommendations();
  renderAll();
  await loadAudit();
}

document.getElementById("btn-refresh-cluster").addEventListener("click", async () => {
  await loadCluster();
  await loadClusterPods();
});

document.getElementById("cluster-selector").addEventListener("change", async (event) => {
  state.selectedClusterId = event.currentTarget.value;
  state.podNamespace = "";
  state.pods = [];
  state.podTotal = 0;
  state.podError = null;
  renderClusterPods();
  await refresh();
});

document.getElementById("pod-namespace-filter").addEventListener("change", async (event) => {
  state.podNamespace = event.currentTarget.value;
  await loadClusterPods();
});

document.getElementById("pod-name-search").addEventListener("input", (event) => {
  state.podSearch = event.currentTarget.value;
  renderClusterPods();
});

document.getElementById("cluster-pods").addEventListener("click", (event) => {
  const button = event.target.closest("[data-pod-logs]");
  if (!button) return;
  const pod = state.pods.find(
    (item) => item.namespace === button.dataset.podNamespace && item.name === button.dataset.podLogs,
  );
  if (pod) openPodLogs(pod);
});

document.getElementById("modal-body").addEventListener("change", (event) => {
  if (event.target.id === "pod-log-container") loadPodLogs();
});

document.getElementById("modal-body").addEventListener("click", (event) => {
  if (event.target.closest("[data-pod-log-refresh]")) {
    loadPodLogs();
    return;
  }
  if (event.target.closest("[data-pod-log-toggle-previous]") && state.podLogTarget) {
    state.podLogTarget.previous = !state.podLogTarget.previous;
    event.target.closest("[data-pod-log-toggle-previous]").textContent =
      state.podLogTarget.previous ? "Ver logs atuais" : "Ver logs anteriores";
    loadPodLogs();
  }
});

document.getElementById("cluster-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const file = document.getElementById("cluster-kubeconfig").files[0];
  if (!file) return;
  if (file.size > 2_000_000) {
    toast("O kubeconfig deve ter no máximo 2 MB", "error");
    return;
  }
  const submit = form.querySelector("button[type='submit']");
  submit.disabled = true;
  try {
    const result = await API.post("/clusters", {
      name: document.getElementById("cluster-display-name").value.trim(),
      kubeconfig: await file.text(),
    });
    state.selectedClusterId = result.cluster.id;
    form.reset();
    toast("Cluster validado e conectado", "success");
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    submit.disabled = false;
  }
});

function showAgentInstructions(title, result) {
  const ins = result.instructions || {};
  openModal(
    title,
    `<p><strong>Copie o token agora:</strong> por segurança ele não será exibido de novo.</p>
     <dl class="rec-detail">
       <dt>Token de ingestão</dt><dd class="mono">${escapeHtml(result.token)}</dd>
       <dt>Instalar no cluster (Helm)</dt><dd><pre class="mono" style="white-space:pre-wrap">${escapeHtml(ins.helm || "")}</pre></dd>
       <dt>Testar localmente (WSL, com kubeconfig do cluster)</dt><dd><pre class="mono" style="white-space:pre-wrap">${escapeHtml(ins.local_test || "")}</pre></dd>
     </dl>
     <p style="color:var(--text-muted);font-size:12px">O coletor só lê o cluster e envia dados para ${escapeHtml(ins.panel_url || "o painel")}. Para remover: helm uninstall capacity-collector -n capacity-agent</p>`,
    `<button class="btn btn-primary" onclick="closeModal()">Fechar</button>`
  );
}

document.getElementById("agent-cluster-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const result = await API.post("/clusters/agent", {
      name: document.getElementById("agent-cluster-name").value.trim(),
    });
    state.selectedClusterId = result.cluster.id;
    form.reset();
    showAgentInstructions("Instalar o agente no cluster", result);
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  }
});

document.getElementById("btn-rotate-token").addEventListener("click", async () => {
  if (!state.selectedClusterId) return;
  if (!confirm("Gerar um novo token? O token atual deixa de funcionar imediatamente.")) return;
  try {
    const result = await API.post(`/clusters/${state.selectedClusterId}/rotate-token`, {});
    showAgentInstructions("Novo token do agente", result);
  } catch (error) {
    toast(error.message, "error");
  }
});

document.getElementById("btn-delete-cluster").addEventListener("click", async () => {
  if (!state.selectedClusterId) return;
  const cluster = state.clusters.find((item) => item.id === state.selectedClusterId);
  if (!confirm(`Remover a conexão ${cluster?.name || "selecionada"}?`)) return;
  try {
    await API.delete(`/clusters/${state.selectedClusterId}`);
    state.selectedClusterId = "";
    toast("Conexão removida", "success");
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  }
});

// ── Evaluate ────────────────────────────────────────────────

document.getElementById("btn-evaluate").addEventListener("click", async () => {
  const btn = document.getElementById("btn-evaluate");
  const spinner = document.getElementById("evaluate-spinner");
  btn.disabled = true;
  spinner.classList.remove("hidden");

  try {
    toast("Avaliação iniciada — pode levar alguns minutos...", "info");
    const result = await API.post("/evaluate");

    if (result.report) {
      if (!state.status) state.status = {};
      state.status.latest_report = result.report;
      state.status.evaluation_id = result.report.evaluation_id;
    }

    toast("Avaliação concluída com sucesso", "success");
    await refresh();
  } catch (e) {
    toast(`Erro na avaliação: ${e.message}`, "error");
  } finally {
    btn.disabled = false;
    spinner.classList.add("hidden");
  }
});

// ── Consumo por node ────────────────────────────────────────

function usageBar(label, pct) {
  if (pct === null || pct === undefined) {
    return `<div class="metric-bar" style="margin:0"><div class="metric-bar-header"><span>${label}</span><span>sem métrica</span></div></div>`;
  }
  return `
    <div class="metric-bar" style="margin:0">
      <div class="metric-bar-header"><span>${label}</span><span>${formatPct(pct)}</span></div>
      <div class="metric-bar-track"><div class="metric-bar-fill ${barClass(pct)}" style="width:${Math.min(pct, 100)}%"></div></div>
    </div>`;
}

function renderNodesUsage() {
  const el = document.getElementById("nodes-usage");
  const nodes = state.status?.latest_report?.nodes_usage || [];
  if (!nodes.length) {
    el.innerHTML = `<div class="empty-state"><p>Execute uma nova avaliação para ver o consumo por node</p></div>`;
    return;
  }
  el.innerHTML = `
    <table>
      <thead><tr><th>Node</th><th>Pool</th><th>Pods</th><th>CPU uso</th><th>CPU reservado</th><th>Memória uso</th><th>Memória reservada</th></tr></thead>
      <tbody>${nodes.map((n) => `
        <tr>
          <td><button class="btn btn-ghost btn-sm" data-node="${escapeHtml(n.name)}" title="Ver o que roda neste node"><strong>${escapeHtml(n.name)}</strong> ›</button>${n.control_plane ? ' <span class="badge badge-manual">control plane</span>' : ""}${n.ready ? "" : ' <span class="badge badge-rejected">NotReady</span>'}</td>
          <td>${escapeHtml(n.pool)}</td>
          <td>${n.pod_count}${n.pods_capacity ? ` <span style="color:var(--text-muted);font-size:11px">/ ${n.pods_capacity}</span>` : ""}</td>
          <td>${usageBar("uso", n.cpu_usage_pct)}</td>
          <td>${usageBar("requests", n.cpu_req_pct)}</td>
          <td>${usageBar("uso", n.mem_usage_pct)}</td>
          <td>${usageBar("requests", n.mem_req_pct)}</td>
        </tr>`).join("")}
      </tbody>
    </table>
    <p style="color:var(--text-muted);font-size:12px;margin-top:8px">Clique em um node para ver os pods e serviços dele. Percentuais sobre o allocatable de cada node. "Uso" = consumo real agora (metrics-server); "reservado" = soma dos requests dos pods no node.</p>`;
}

document.getElementById("nodes-usage").addEventListener("click", (event) => {
  const btn = event.target.closest("[data-node]");
  if (btn) showNodeDetail(btn.dataset.node);
});

function fmtNum(v, unit) {
  return v === null || v === undefined ? "—" : `${v}${unit}`;
}

async function showNodeDetail(name) {
  openModalWithSize(`Node ${name}`, `<div class="empty-state"><p>Carregando…</p></div>`,
    `<button class="btn btn-ghost" onclick="closeModal()">Fechar</button>`, true);
  let d;
  try {
    d = await API.get(`/cluster/nodes/${encodeURIComponent(name)}`);
  } catch (e) {
    document.getElementById("modal-body").innerHTML = `<div class="empty-state"><p>${escapeHtml(e.message)}</p></div>`;
    return;
  }
  const u = d.usage || {};
  const labels = Object.entries(d.labels || {}).map(([k, v]) => `${escapeHtml(k.split("/").pop())}: ${escapeHtml(v)}`).join(" · ");
  const alerts = [
    ...(d.conditions_alert || []).map((c) => `${escapeHtml(c.type)}=${escapeHtml(c.status)} ${escapeHtml(c.reason || "")}`),
    ...(d.unschedulable ? ["Node marcado como não agendável (cordon)"] : []),
    ...(d.pods_without_requests ? [`${d.pods_without_requests} pod(s) sem request de CPU/memória — o scheduler não enxerga esse consumo`] : []),
  ];
  const body = `
    <p><strong>${escapeHtml(d.pool || "—")}</strong>${d.control_plane ? ' <span class="badge badge-manual">control plane</span>' : ""}
      ${d.ready ? '<span class="badge badge-executed">Ready</span>' : '<span class="badge badge-rejected">NotReady</span>'}
      <span style="color:var(--text-muted);font-size:12px"> · kubelet ${escapeHtml(d.kubelet || "—")} · ${escapeHtml(d.runtime || "")} ${labels ? "· " + labels : ""}</span></p>
    ${alerts.length ? `<div class="panel" style="border-color:var(--warn, #d97706)"><div class="panel-body">${alerts.map((a) => `⚠ ${a}`).join("<br>")}</div></div>` : ""}
    <div class="grid-2" style="margin:12px 0">
      <div>${usageBar("CPU uso", u.cpu_usage_pct)}${usageBar("CPU reservado", u.cpu_req_pct)}</div>
      <div>${usageBar("Memória uso", u.mem_usage_pct)}${usageBar("Memória reservada", u.mem_req_pct)}</div>
    </div>
    ${(d.taints || []).length ? `<p style="font-size:12px;color:var(--text-muted)">Taints: ${d.taints.map((t) => escapeHtml(`${t.key}${t.value ? "=" + t.value : ""}:${t.effect}`)).join(", ")}</p>` : ""}
    <h4 style="margin:12px 0 6px">Por namespace</h4>
    <table><thead><tr><th>Namespace</th><th>Pods</th><th>CPU em uso</th><th>Memória em uso</th></tr></thead>
      <tbody>${d.namespaces.map((n) => `<tr><td>${escapeHtml(n.namespace)}</td><td>${n.pods}</td><td>${n.cpu_used_m}m</td><td>${n.mem_used_mi} Mi</td></tr>`).join("")}</tbody></table>
    <h4 style="margin:12px 0 6px">Pods neste node (${d.pods.length}) — ordenados por memória em uso</h4>
    <div style="max-height:360px;overflow:auto">
    <table><thead><tr><th>Namespace / Pod</th><th>Workload</th><th>Status</th><th>Reinícios</th><th>CPU uso / req</th><th>Memória uso / req</th><th>QoS</th></tr></thead>
      <tbody>${d.pods.map((p) => `
        <tr>
          <td><span style="color:var(--text-muted)">${escapeHtml(p.namespace)}/</span>${escapeHtml(p.pod)}</td>
          <td>${escapeHtml(p.workload)}</td>
          <td><span class="badge ${["Running"].includes(p.status) ? "badge-executed" : "badge-pending"}">${escapeHtml(p.status || "—")}</span></td>
          <td>${p.restarts}</td>
          <td>${fmtNum(p.cpu_used_m, "m")} / ${p.cpu_req_m ? p.cpu_req_m + "m" : '<span class="badge badge-rejected">sem request</span>'}</td>
          <td>${fmtNum(p.mem_used_mi, " Mi")} / ${p.mem_req_mi ? p.mem_req_mi + " Mi" : '<span class="badge badge-rejected">sem request</span>'}</td>
          <td>${escapeHtml(p.qos || "—")}</td>
        </tr>`).join("")}</tbody></table>
    </div>`;
  document.getElementById("modal-body").innerHTML = body;
  document.getElementById("modal-footer").innerHTML = `
    <button class="btn btn-ghost" onclick="closeModal()">Fechar</button>
    <button class="btn btn-primary" id="node-ask-ai">Analisar este node com o Assistente IA</button>`;
  document.getElementById("node-ask-ai").addEventListener("click", () => {
    closeModal();
    switchTab("assistant");
    document.getElementById("chat-input").value =
      `Analise o node ${name}: quais pods mais consomem, quais estão sem requests e qual o risco de falta de memória ou CPU?`;
  });
}

// ── Pendências do roadmap (interno) ─────────────────────────

let roadmapCache = null;
async function renderRoadmap() {
  const panel = document.getElementById("roadmap-panel");
  if (!state.status?.show_roadmap) {
    panel.classList.add("hidden");
    return;
  }
  try {
    if (!roadmapCache) roadmapCache = await (await fetch(`/static/roadmap.json?_=${Date.now()}`)).json();
  } catch (e) {
    return;
  }
  panel.classList.remove("hidden");
  document.getElementById("roadmap-list").innerHTML = `
    <ul>${roadmapCache.items.map((i) => `
      <li><strong>${escapeHtml(i.titulo)}</strong> <span class="badge badge-pending">${escapeHtml(i.origem)}</span><br>
      <span style="color:var(--text-muted);font-size:12px">${escapeHtml(i.detalhe)}</span></li>`).join("")}
    </ul>`;
}

function formatBRL(value) {
  return Number(value || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

async function loadAlertsConfig() {
  try {
    const data = await API.get("/alerts/config");
    const c = data.config || {};
    document.getElementById("alert-severity").value = c.min_severity || "MEDIUM";
    document.getElementById("alert-emails").value = c.emails || "";
    document.getElementById("alert-ai").checked = !!c.include_ai;
    document.getElementById("alert-enabled").checked = c.enabled !== false;
    const channels = ["slack_url", "teams_url", "webhook_url"].filter((k) => c[`has_${k}`]).map((k) => k.replace("_url", ""));
    document.getElementById("alert-status").textContent =
      (data.licensed ? "" : "Licença atual não inclui alertas. ") +
      (channels.length ? `Canais salvos: ${channels.join(", ")}` : "Nenhum webhook salvo") +
      (data.smtp_configured ? " · SMTP ok" : " · e-mail: SMTP não configurado na instalação");
  } catch (e) { /* sem permissão */ }
}

function alertBody() {
  const val = (id) => document.getElementById(id).value.trim();
  return {
    enabled: document.getElementById("alert-enabled").checked,
    min_severity: val("alert-severity"),
    slack_url: val("alert-slack") || null,
    teams_url: val("alert-teams") || null,
    webhook_url: val("alert-webhook") || null,
    emails: val("alert-emails"),
    include_ai: document.getElementById("alert-ai").checked,
  };
}

document.getElementById("alert-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const res = await fetch("/api/alerts/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json",
        ...(state.selectedClusterId ? { "X-Cluster-Id": state.selectedClusterId } : {}) },
      body: JSON.stringify(alertBody()),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Erro ${res.status}`);
    for (const id of ["alert-slack", "alert-teams", "alert-webhook"]) document.getElementById(id).value = "";
    toast("Alertas salvos", "success");
    await loadAlertsConfig();
  } catch (e) {
    toast(e.message, "error");
  }
});

document.getElementById("alert-test").addEventListener("click", async () => {
  try {
    const result = await API.post("/alerts/test", {});
    const text = Object.entries(result.results).map(([k, v]) => `${k}: ${v}`).join(" · ");
    toast(`Teste enviado — ${text}`, Object.values(result.results).every((v) => v === "ok") ? "success" : "error");
  } catch (e) {
    toast(e.message, "error");
  }
});

async function loadCosts() {
  try {
    const c = await API.get("/costs");
    document.getElementById("cost-cpu").value = c.cpu_month || "";
    document.getElementById("cost-gb").value = c.gb_month || "";
  } catch (e) { /* sem permissão */ }
}

document.getElementById("cost-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const res = await fetch("/api/costs", {
      method: "PUT",
      headers: { "Content-Type": "application/json",
        ...(state.selectedClusterId ? { "X-Cluster-Id": state.selectedClusterId } : {}) },
      body: JSON.stringify({
        cpu_month: Number(document.getElementById("cost-cpu").value || 0),
        gb_month: Number(document.getElementById("cost-gb").value || 0),
      }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Erro ${res.status}`);
    toast("Custos salvos. Faça uma Nova Avaliação para recalcular.", "success");
  } catch (e) {
    toast(e.message, "error");
  }
});

// ── Licença ─────────────────────────────────────────────────

const PLAN_LABELS = { community: "Community", pro: "Pro", enterprise: "Enterprise" };

async function loadLicense() {
  try {
    state.license = await API.get("/license");
  } catch (e) {
    return;
  }
  const lic = state.license;
  const banner = document.getElementById("license-banner");
  const warn = ["community", "grace", "expired", "invalid"].includes(lic.state) || (lic.days_left !== null && lic.days_left <= 30);
  banner.classList.toggle("hidden", !warn || !can("admin"));
  document.getElementById("license-banner-text").innerHTML =
    `<strong>Licença ${escapeHtml(PLAN_LABELS[lic.plan] || lic.plan)}:</strong> ${escapeHtml(lic.message)}`;
  const features = (lic.features || []).map((f) => escapeHtml(lic.feature_labels?.[f] || f)).join(", ") || "—";
  const info = document.getElementById("license-info");
  if (info) {
    info.innerHTML = `
      <dl class="rec-detail">
        <dt>Plano</dt><dd>${escapeHtml(PLAN_LABELS[lic.plan] || lic.plan)} (${escapeHtml(lic.state)})</dd>
        <dt>Cliente</dt><dd>${escapeHtml(lic.customer || "—")}</dd>
        <dt>Limites</dt><dd>${lic.max_clusters} cluster(s), ${lic.max_users} usuário(s)</dd>
        <dt>Recursos</dt><dd>${features}</dd>
        <dt>Validade</dt><dd>${lic.expires_at ? formatDate(lic.expires_at) : "—"}</dd>
        <dt>Situação</dt><dd>${escapeHtml(lic.message)}</dd>
      </dl>`;
  }
}

document.getElementById("license-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const file = document.getElementById("license-file").files[0];
  if (!file) return;
  try {
    await API.post("/license", { license: await file.text() });
    toast("Licença instalada", "success");
    form.reset();
    await loadLicense();
  } catch (e) {
    toast(e.message, "error");
  }
});

// ── Assistente de IA ────────────────────────────────────────

const chatHistory = [];

function renderChat() {
  const log = document.getElementById("chat-log");
  log.innerHTML = chatHistory.map((m) => `
    <div style="margin:8px 0;padding:10px 12px;border-radius:8px;background:${m.role === "user" ? "var(--bg-elevated, rgba(59,130,246,.12))" : "rgba(255,255,255,.04)"}">
      <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">${m.role === "user" ? "Você" : "Assistente"}${m.tools ? " · consultou: " + escapeHtml(m.tools.join(", ")) : ""}</div>
      <div style="white-space:pre-wrap">${escapeHtml(m.content)}</div>
    </div>`).join("") || `<div class="empty-state"><p>Faça uma pergunta sobre o cluster ativo.</p></div>`;
  log.scrollTop = log.scrollHeight;
}

async function loadAssistantConfig() {
  renderChat();
  const panel = document.getElementById("assistant-config-panel");
  panel.classList.toggle("hidden", !can("admin"));
  if (!can("admin")) return;
  const data = await API.get("/assistant/config");
  const c = data.config || {};
  document.getElementById("ai-provider").value = c.provider || "anthropic";
  document.getElementById("ai-model").value = c.model || "";
  document.getElementById("ai-base-url").value = c.base_url || "";
  document.getElementById("ai-api-version").value = c.api_version || "";
  document.getElementById("ai-auth-header").value = c.auth_header || "bearer";
  document.getElementById("ai-config-status").textContent =
    (data.licensed ? "" : "Licença atual não inclui o assistente. ") +
    (c.model ? `Configurado: ${c.provider} · ${c.model}${c.has_key ? " · chave salva" : ""}` : "Não configurado");
}

document.getElementById("assistant-config-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(event.currentTarget));
  for (const k of ["base_url", "api_version"]) if (!body[k]) body[k] = null;
  if (!body.api_key) delete body.api_key;
  try {
    const res = await fetch("/api/assistant/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json",
        ...(state.selectedClusterId ? { "X-Cluster-Id": state.selectedClusterId } : {}) },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Erro ${res.status}`);
    document.getElementById("ai-api-key").value = "";
    toast("Configuração do assistente salva", "success");
    await loadAssistantConfig();
  } catch (e) {
    toast(e.message, "error");
  }
});

document.getElementById("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.getElementById("chat-input");
  const question = input.value.trim();
  if (!question) return;
  chatHistory.push({ role: "user", content: question });
  input.value = "";
  renderChat();
  const send = document.getElementById("chat-send");
  const status = document.getElementById("chat-status");
  send.disabled = true;
  status.textContent = "Analisando o cluster…";
  try {
    const result = await API.post("/assistant/chat", {
      messages: chatHistory.filter((m) => !m.content.startsWith("Erro: ")).slice(-10)
        .map((m) => ({ role: m.role, content: m.content })),
    });
    chatHistory.push({ role: "assistant", content: result.answer || "(sem resposta)", tools: result.tools_used });
  } catch (e) {
    chatHistory.push({ role: "assistant", content: `Erro: ${e.message}` });
  } finally {
    send.disabled = false;
    status.textContent = "";
    renderChat();
  }
});

document.getElementById("chat-clear").addEventListener("click", () => {
  chatHistory.length = 0;
  renderChat();
});

// ── Suporte ─────────────────────────────────────────────────

const HEALTH_BADGE = { ok: "badge-executed", aviso: "badge-pending", erro: "badge-rejected" };

async function loadSupportHealth() {
  const el = document.getElementById("support-health");
  el.innerHTML = `<div class="empty-state"><p>Verificando…</p></div>`;
  try {
    const h = await API.get("/support/health");
    el.innerHTML = `
      <p>Versão <strong>${escapeHtml(h.version)}</strong> · no ar há ${h.uptime_minutes} min ·
        situação geral <span class="badge ${HEALTH_BADGE[h.status]}">${escapeHtml(h.status.toUpperCase())}</span></p>
      <table>
        <thead><tr><th>Verificação</th><th>Status</th><th>Detalhe</th><th>O que fazer</th></tr></thead>
        <tbody>${h.checks.map((c) => `
          <tr>
            <td>${escapeHtml(c.name)}</td>
            <td><span class="badge ${HEALTH_BADGE[c.status]}">${escapeHtml(c.status.toUpperCase())}</span></td>
            <td style="max-width:420px">${escapeHtml(c.detail || "")}</td>
            <td style="max-width:320px;color:var(--text-muted)">${c.status === "ok" ? "" : escapeHtml(c.hint || "")}</td>
          </tr>`).join("")}
        </tbody>
      </table>`;
  } catch (e) {
    el.innerHTML = `<div class="empty-state"><p>${escapeHtml(e.message)}</p></div>`;
  }
}

document.getElementById("btn-health-refresh").addEventListener("click", loadSupportHealth);

document.getElementById("btn-support-bundle").addEventListener("click", async () => {
  try {
    const res = await fetch("/api/support/bundle", {
      headers: state.selectedClusterId ? { "X-Cluster-Id": state.selectedClusterId } : {},
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Erro ${res.status}`);
    const blob = await res.blob();
    const name = (res.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || "capacity-agent-suporte.zip";
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = name;
    link.click();
    URL.revokeObjectURL(link.href);
    toast("Pacote de suporte gerado", "success");
  } catch (e) {
    toast(e.message, "error");
  }
});

// ── Usuários e convites ─────────────────────────────────────

const ROLE_LABELS = { leitor: "Leitor", operador: "Operador", admin: "Admin" };

async function loadUsers() {
  const data = await API.get("/users");
  const rows = data.users.map((u) => `
    <tr>
      <td>${escapeHtml(u.full_name)}${u.id === data.me ? " (você)" : ""}</td>
      <td>${escapeHtml(u.email)}</td>
      <td>
        <select data-user-role="${escapeHtml(u.id)}" ${u.id === data.me ? "disabled" : ""}>
          ${Object.entries(ROLE_LABELS).map(([value, label]) =>
            `<option value="${value}" ${u.role === value ? "selected" : ""}>${label}</option>`).join("")}
        </select>
      </td>
      <td>${u.id === data.me ? "" : `<button class="btn btn-danger btn-sm" data-user-remove="${escapeHtml(u.id)}">Remover</button>`}</td>
    </tr>`).join("");
  const invites = data.invites.length
    ? `<p class="muted">Convites ativos: ${data.invites.map((i) =>
        `${escapeHtml(ROLE_LABELS[i.role] || i.role)}${i.email ? " · " + escapeHtml(i.email) : ""} (expira ${formatDate(i.expires_at)})`).join("; ")}</p>`
    : "";
  const el = document.getElementById("users-list");
  el.innerHTML = `
    <table>
      <thead><tr><th>Nome</th><th>E-mail</th><th>Papel</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table>${invites}`;
  el.querySelectorAll("[data-user-role]").forEach((select) => {
    select.addEventListener("change", async () => {
      try {
        await API.patch(`/users/${select.dataset.userRole}`, { role: select.value });
        toast("Papel atualizado. O usuário precisará entrar novamente.", "success");
      } catch (e) {
        toast(e.message, "error");
      }
      await loadUsers();
    });
  });
  el.querySelectorAll("[data-user-remove]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await API.delete(`/users/${btn.dataset.userRemove}`);
        toast("Usuário removido", "success");
      } catch (e) {
        toast(e.message, "error");
      }
      await loadUsers();
    });
  });
}

document.getElementById("invite-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(event.currentTarget));
  if (!body.email) delete body.email;
  try {
    const result = await API.post("/invites", body);
    document.getElementById("invite-result").innerHTML = `
      <p>Envie este link ao colega (válido até ${formatDate(result.expires_at)}, uso único):</p>
      <input class="mono" readonly value="${escapeHtml(result.link)}" onclick="this.select()" style="width:100%">`;
    await loadUsers();
  } catch (e) {
    toast(e.message, "error");
  }
});

// ── Init ────────────────────────────────────────────────────

function prepareInviteScreen() {
  const token = new URLSearchParams(location.search).get("invite");
  if (!token) return false;
  state.inviteToken = token;
  document.querySelector('[data-auth-view="register"]').click();
  document.querySelector('[data-auth-view="register"]').textContent = "Aceitar convite";
  document.getElementById("register-company-group").classList.add("hidden");
  document.getElementById("register-company").required = false;
  document.getElementById("register-submit").textContent = "Entrar na empresa";
  return true;
}

async function applySetupMode() {
  try {
    const setup = await (await fetch("/api/auth/setup")).json();
    if (!setup.registration_open) {
      const tab = document.querySelector('[data-auth-view="register"]');
      if (tab && !state.inviteToken) tab.classList.add("hidden");
    }
  } catch (e) { /* mantém a tela padrão */ }
}

async function bootstrap() {
  if (prepareInviteScreen()) {
    showAuthScreen("Você foi convidado. Crie seu acesso para entrar na empresa.");
    return;
  }
  await applySetupMode();
  try {
    const user = await API.get("/auth/me");
    showApp(user);
    await refresh();
  } catch (error) {
    showAuthScreen(error.message === "Autenticação necessária" ? "" : error.message);
  }
}

bootstrap();
setInterval(() => {
  if (state.user) refresh().catch(() => {});
}, 60000);
