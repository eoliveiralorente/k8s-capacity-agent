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
    cluster: "Clusters e conexões",
    recommendations: "Recomendações",
    capacity: "Nodes e capacidade",
    costs: "Custos",
    scheduling: "Pods e scheduling",
    audit: "Auditoria",
    users: "Usuários e custos",
    assistant: "Assistente IA",
    journal: "Diário de bordo",
    support: "Suporte",
  };
  document.getElementById("page-title").textContent = titles[tab] || tab;
  if (tab === "users" && can("admin")) {
    loadUsers().catch((e) => toast(e.message, "error"));
    loadCosts();
    loadAlertsConfig();
  }
  if (tab === "assistant") loadAssistantConfig().catch(() => {});
  if (tab === "journal") loadJournal();
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

// Uso da CPU reservada: abaixo de 30% sobra reserva; acima de 100% os pods usam mais do que
// reservaram e disputam CPU no node. Os dois casos pedem atenção.
function cpuReservedKpi(kpi, pct) {
  if (pct === null || pct === undefined) return kpi("Uso da CPU reservada", "—", "sem métricas de CPU");
  if (pct > 100) return kpi("Uso da CPU reservada", `${pct}%`, "acima do reservado: risco de disputa de CPU", "warn");
  if (pct < 30) return kpi("Uso da CPU reservada", `${pct}%`, "pouco uso: CPU reservada sobrando", "warn");
  return kpi("Uso da CPU reservada", `${pct}%`, "do reservado está em uso");
}

function renderOverview() {
  loadLicense();
  renderExecutiveOverview();
  renderOverviewStatus();
  renderNodesUsage();
  renderCosts();
  renderNavCounts();
  loadJournalSummary();
}

const COST_ACCURACY = {
  tabela: ["preços da sua tabela", "ok"],
  aproximado: ["estimativa aproximada (R$/vCPU e R$/GB)", "warn"],
};

function renderCosts() {
  const kpisBox = document.getElementById("cost-kpis");
  if (!kpisBox) return;
  document.getElementById("cost-settings-btn").classList.toggle("hidden", !can("admin"));
  const report = state.status?.latest_report;
  const c = report?.cluster_cost;
  const k = report?.overview?.kpis || {};
  const ids = ["cost-breakdown", "cost-namespaces", "cost-pools", "cost-savings"];
  if (!c || !c.configured) {
    kpisBox.innerHTML = "";
    document.getElementById("cost-breakdown").innerHTML = `<div class="ov-empty">Cadastre o preço dos seus tipos de máquina
      para ver quanto o cluster custa por mês, quanto cada namespace consome e quanto está pago e ocioso.
      ${can("admin") ? "Use o botão Preços e custos." : "Peça a um admin para cadastrar em Usuários e custos."}</div>`;
    ids.slice(1).forEach((id) => { document.getElementById(id).innerHTML = ""; });
    document.getElementById("cost-settings-btn").classList.toggle("hidden", !can("admin"));
    return;
  }
  const num = (v) => Number(v).toLocaleString("pt-BR");
  const h = c.history && c.history.available ? c.history : null;
  const [accLabel, accTone] = COST_ACCURACY[c.accuracy] || ["preços parciais", "warn"];
  const kpi = (label, value, sub, cls = "") => `
    <div class="kpi"><span class="kpi-label">${label}</span><strong class="kpi-value ${cls}">${value}</strong><span class="kpi-sub">${sub}</span></div>`;
  kpisBox.innerHTML = [
    kpi("Custo por mês (nodes de agora)", formatBRL(c.total_monthly), accLabel),
    h ? kpi(`Média dos últimos ${num(h.days)} dias`, formatBRL(h.monthly),
            `${h.diff_pct > 0 ? "+" : ""}${num(h.diff_pct)}% vs agora · gasto real ${formatBRL(h.spend_window)}`,
            Math.abs(h.diff_pct || 0) >= 5 ? "warn" : "")
      : kpi("Média do histórico", "—", c.history ? `disponível após ${c.history.min_hours} h de coleta` : "sem histórico ainda"),
    kpi("Capacidade ociosa", formatBRL(c.idle_monthly), c.idle_pct != null ? `${num(c.idle_pct)}% dos nodes, pago sem uso` : "pago sem uso",
        (c.idle_pct || 0) >= 40 ? "warn" : ""),
    kpi("Economia potencial", k.savings_monthly == null ? "—" : formatBRL(k.savings_monthly),
        k.savings_monthly == null ? "" : `por mês · ${k.savings_count} recomendação(ões)`, "ok"),
  ].join("");

  const total = c.total_monthly || 0;
  const seg = (v) => total ? Math.max(0, v / total * 100) : 0;
  const scaling = h ? Object.entries(h.pools || {}).filter(([, p]) => p.min_nodes !== p.max_nodes)
    .map(([name, p]) => `${escapeHtml(name)} (${p.min_nodes}–${p.max_nodes} nodes, média ${num(p.avg_nodes)})`) : [];
  const warns = [];
  if (c.coverage?.sem_preco) warns.push(`${c.coverage.sem_preco} node(s) sem preço ficaram fora do total: ${escapeHtml((c.unpriced_types || []).join(", "))}.`);
  if (c.coverage?.aproximado && c.coverage?.tabela) warns.push(`${c.coverage.aproximado} node(s) usam o preço de referência por vCPU/GB (aproximado).`);
  if (scaling.length) warns.push(`Autoscaling detectado: ${scaling.join(", ")}. A média do histórico fica mais perto da fatura.`);
  document.getElementById("cost-breakdown").innerHTML = `
    <div class="cost-bar cost-bar-lg" role="img" aria-label="Composição do custo">
      <i class="cb-alloc" style="width:${seg(c.allocated_monthly)}%"></i><i class="cb-idle" style="width:${seg(c.idle_monthly)}%"></i><i class="cb-fixed" style="width:${seg(c.fixed_monthly)}%"></i>
    </div>
    <ul class="cost-legend cost-legend-row">
      <li><i class="cb-alloc"></i><div><span>Reservado pelos workloads</span><b>${formatBRL(c.allocated_monthly)}</b></div></li>
      <li><i class="cb-idle"></i><div><span>Capacidade ociosa</span><b class="warn-text">${formatBRL(c.idle_monthly)}</b></div></li>
      <li><i class="cb-fixed"></i><div><span>Custos fixos${(c.fixed || []).length ? ` (${(c.fixed || []).map((f) => escapeHtml(f.name)).join(", ")})` : ""}</span><b>${formatBRL(c.fixed_monthly)}</b></div></li>
    </ul>
    ${warns.map((w) => `<p class="cost-warn">${w}</p>`).join("")}
    <p class="ov-foot">Preço por hora × 730 h/mês. Cada node é dividido entre os pods pelo que cada um reserva (requests). "Ociosa" é a capacidade paga que nenhum pod reserva: é ela que vira economia quando um node pode sair. A média do histórico usa quantos nodes cada pool teve a cada hora.</p>`;

  const maxNs = Math.max(...(c.by_namespace || []).map((n) => n.monthly), 1);
  document.getElementById("cost-namespaces").innerHTML = (c.by_namespace || []).map((n) => `
    <div class="cost-ns"><span title="${escapeHtml(n.namespace)}">${escapeHtml(n.namespace)}</span>
      <div class="cost-ns-bar"><i style="width:${n.monthly / maxNs * 100}%"></i></div><b>${formatBRL(n.monthly)}</b></div>`).join("")
    || `<div class="ov-empty">Nenhum pod com requests.</div>`;

  const pools = Object.entries(c.by_pool || {}).sort((a, b) => b[1].monthly - a[1].monthly);
  document.getElementById("cost-pools").innerHTML = pools.map(([name, p]) => {
    const hp = h?.pools?.[name];
    return `
    <div class="cost-pool"><div><strong>${escapeHtml(name)}</strong>
      <span>${p.nodes} × ${escapeHtml(p.machine || "node")} · ${formatBRL(p.per_node)}/node${hp && hp.min_nodes !== hp.max_nodes ? ` · histórico ${hp.min_nodes}–${hp.max_nodes} nodes` : ""}</span></div>
      <div class="cost-pool-val"><b>${formatBRL(p.monthly)}</b><span class="${p.idle_monthly > p.monthly * 0.4 ? "warn-text" : ""}">ocioso ${formatBRL(p.idle_monthly)}</span></div></div>`;
  }).join("");

  const savings = (report.recommendations || []).filter((r) => (r.estimated_monthly || 0) > 0 && !String(r.type).startsWith("INCREASE"))
    .sort((a, b) => b.estimated_monthly - a.estimated_monthly).slice(0, 8);
  document.getElementById("cost-savings").innerHTML = savings.length ? savings.map((s) => `
    <div class="ov-item">
      <strong class="ov-money">${formatBRL(s.estimated_monthly)}<small>/mês</small></strong>
      <div class="ov-item-text"><strong>${escapeHtml(REC_TYPE_LABELS[s.type] || s.type)}</strong><span>${escapeHtml(s.pool || "")}${s.type === "UNDERUTILIZED_POOL" ? " · 1 node a menos" : " · vira dinheiro quando permitir remover nodes"}</span></div>
      <button class="btn btn-ghost btn-sm" data-goto-rec="${escapeHtml(s.id || "")}">Revisar</button>
    </div>`).join("") : `<div class="ov-empty">Nenhuma economia relevante identificada agora.</div>`;
}

document.getElementById("cost-settings-btn").addEventListener("click", () => {
  switchTab("users");
  setTimeout(() => document.getElementById("cost-panel")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
});
document.getElementById("tab-costs").addEventListener("click", (event) => {
  const rec = event.target.closest("[data-goto-rec]");
  if (rec) focusRecommendation(rec.dataset.gotoRec);
});


function renderNavCounts() {
  const pending = state.status?.gate?.counts?.pending ?? 0;
  const btn = document.querySelector('.nav-item[data-tab="recommendations"]');
  if (btn) btn.innerHTML = `Recomendações${pending ? ` <span class="nav-count">${pending}</span>` : ""}`;
}

const CHECK_LABELS = { NODE_METRICS: "Métricas de nodes", POD_METRICS: "Métricas de pods", PROMETHEUS: "Prometheus",
  CONTAINER_METRICS: "Métricas de containers", HISTORY: "Histórico" };
function checkLabel(type) {
  const key = String(type || "").toUpperCase();
  if (CHECK_LABELS[key]) return CHECK_LABELS[key];
  const t = String(type || "").replace(/_/g, " ").toLowerCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function renderOverviewStatus() {
  const report = state.status?.latest_report;
  const summary = report?.summary || {};
  const nodes = report?.nodes_usage || [];
  const ready = nodes.filter((n) => n.ready).length;
  const strip = document.getElementById("ov-strip");
  const statusEl = document.getElementById("ov-status");
  if (!report || report.locked) { strip.innerHTML = ""; statusEl.innerHTML = ""; return; }

  const problems = summary.scheduling_issues ?? 0;
  strip.innerHTML = `
    <button class="ov-stat" data-risk-goto="capacity"><span>Nodes</span><strong>${ready}/${nodes.length || summary.nodes || 0}</strong><em>Ready · ${summary.node_pools ?? 0} pools</em></button>
    <button class="ov-stat" data-risk-goto="scheduling"><span>Pods</span><strong>${summary.pods ?? "—"}</strong><em>${summary.pending_pods ? `${summary.pending_pods} Pending` : "nenhum Pending"}</em></button>
    <button class="ov-stat ${problems ? "warn" : ""}" data-risk-goto="scheduling"><span>Problemas</span><strong>${problems}</strong><em>de scheduling</em></button>`;

  const checks = report.health?.checks || [];
  const decision = report.decision;
  const items = checks.map((c) => `
    <span class="st-item" title="${escapeHtml(`${c.type}: cobertura ${c.coverage}% — ${c.status}`)}">
      <i class="st-dot ${c.status === "OK" ? "ok" : "bad"}"></i>${escapeHtml(checkLabel(c.type))} <b>${c.coverage}%</b></span>`);
  if (decision) {
    items.push(`
      <button class="st-item st-gate" id="ov-gate" title="Ver detalhes do gate de decisão">
        <i class="st-dot ${decision.allowed ? "ok" : "bad"}"></i>Gate: ${decision.allowed ? "decisões liberadas" : "decisões bloqueadas"}
        · ${decision.executable_recommendations ?? 0} executáveis ›</button>`);
  }
  statusEl.innerHTML = items.length ? `<span class="st-label">Status da coleta</span>${items.join("")}` : "";
  const gate = document.getElementById("ov-gate");
  if (gate) gate.addEventListener("click", () => {
    const reasons = (decision.reasons || []).map((r) => `<li>${escapeHtml(r)}</li>`).join("");
    openModal("Gate de decisão", `
      <p class="${decision.allowed ? "decision-ok" : "decision-blocked"}" style="font-weight:600">
        ${decision.allowed ? "✓ Decisões permitidas" : "✗ Decisões bloqueadas"}</p>
      ${reasons ? `<ul class="reason-list">${reasons}</ul>` : "<p>Nenhum bloqueio: os dados estão completos e estáveis para aprovar mudanças.</p>"}
      <p style="margin-top:12px;font-size:12px;color:var(--text-muted)">Executáveis: ${decision.executable_recommendations ?? 0} ·
        Severidade HIGH: ${decision.high_severity_count ?? 0}</p>
      <h4 style="margin:14px 0 6px">Health checks</h4>
      ${checks.map((c) => usageBar(`${checkLabel(c.type)} — ${c.status}`, c.coverage)).join("")}`,
      `<button class="btn btn-ghost" onclick="closeModal()">Fechar</button>`);
  });
}

function focusRecommendation(id) {
  state.focusRecId = id;
  if (state.filterStatus) {
    state.filterStatus = "";
    document.querySelectorAll(".filter-btn").forEach((b) => b.classList.toggle("active", b.dataset.status === ""));
    switchTab("recommendations");
    loadRecommendations().then(renderRecommendations).catch(() => {});
  } else {
    switchTab("recommendations");
    renderRecommendations();
  }
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
      if (can("operador")) {
        btns.push(`<button class="btn btn-ghost btn-sm btn-icon" title="Registrar no diário de bordo" data-action="journal" data-id="${rec.id}">＋</button>`);
      }
      actions = `<td><div class="actions-cell">${btns.join("")}</div></td>`;
    }

    return `
      <tr id="rec-row-${rec.id}" class="${state.focusRecId === rec.id ? "rec-focus" : ""}">
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
  const items = state.recommendations;
  if (!items.length) {
    el.innerHTML = buildRecTable(items);
  } else {
    const groups = {};
    items.forEach((r) => { (groups[r.type] = groups[r.type] || []).push(r); });
    const impact = (list) => list.reduce((t, r) => t + Math.max(r.estimated_monthly || 0, 0), 0);
    const worst = (list) => Math.min(...list.map((r) => SEV_RANK[r.severity] ?? 9));
    const ordered = Object.entries(groups).sort(([, a], [, b]) => worst(a) - worst(b) || impact(b) - impact(a));
    el.innerHTML = ordered.map(([type, list]) => {
      list.sort((a, b) => (SEV_RANK[a.severity] ?? 9) - (SEV_RANK[b.severity] ?? 9)
        || (b.estimated_monthly || 0) - (a.estimated_monthly || 0));
      const money = impact(list);
      return `
        <details class="rec-group" open>
          <summary>
            <span class="rec-group-title">${escapeHtml(REC_TYPE_LABELS[type] || type)}</span>
            <span class="rec-group-count">${list.length}</span>
            ${money > 0 ? `<span class="rec-group-money">${formatBRL(money)}/mês</span>` : ""}
          </summary>
          <div class="table-wrap">${buildRecTable(list)}</div>
        </details>`;
    }).join("");
  }

  el.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const rec = state.recommendations.find((r) => r.id === btn.dataset.id);
      if (!rec) return;
      const action = btn.dataset.action;
      if (action === "approve") showApproveModal(rec);
      else if (action === "reject") showRejectModal(rec);
      else if (action === "execute") showExecuteModal(rec, false);
      else if (action === "dry-run") showExecuteModal(rec, true);
      else if (action === "journal") showJournalForm("pendencia", {
        title: `${REC_TYPE_LABELS[rec.type] || rec.type}: ${rec.pool || ""}`, body: rec.action,
        link_type: "recommendation", link_ref: rec.id });
    });
  });

  if (state.focusRecId) {
    const row = document.getElementById(`rec-row-${state.focusRecId}`);
    if (row) {
      row.closest("details")?.setAttribute("open", "");
      setTimeout(() => row.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
    }
    setTimeout(() => { state.focusRecId = null; row?.classList.remove("rec-focus"); }, 4000);
  }
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

const AUDIT_META = {
  evaluate: ["Avaliação", "eval", "◎"],
  approve: ["Aprovação", "ok", "✓"],
  reject: ["Rejeição", "bad", "✕"],
  execute: ["Execução", "exec", "▶"],
  journal_created: ["Diário", "info", "✎"],
  journal_updated: ["Diário", "info", "✎"],
  journal_deleted: ["Diário", "info", "✎"],
  alerts_sent: ["Alertas", "warn", "!"],
  alert_settings: ["Configuração", "cfg", "⚙"],
  cost_settings: ["Configuração", "cfg", "⚙"],
  assistant_config: ["Configuração", "cfg", "⚙"],
  assistant_query: ["Assistente IA", "info", "?"],
  invite: ["Usuários", "cfg", "＋"],
  role_change: ["Usuários", "cfg", "⇄"],
  user_removed: ["Usuários", "cfg", "−"],
  license_installed: ["Licença", "ok", "★"],
  support_bundle: ["Suporte", "cfg", "⇩"],
  agent_cluster_created: ["Cluster", "cfg", "＋"],
  agent_token_rotated: ["Cluster", "cfg", "↻"],
};
const JOURNAL_STATUS_LABELS = { aberta: "aberta", andamento: "em andamento", concluida: "concluída" };
const JOURNAL_KIND_LABELS = { pendencia: "a pendência", nota: "a nota" };

function auditActor(d) {
  const who = d.executed_by || d.approver || d.rejector || d.by;
  if (!who) return "Sistema";
  const named = String(who).match(/^(.+?)\s*\(/);
  if (named) return named[1];
  return String(who).split("@")[0].replace(/[._-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function auditRec(d) {
  const rec = (state.recommendations || []).find((r) => r.id === d.rec_id);
  const label = REC_TYPE_LABELS[d.type] || REC_TYPE_LABELS[rec?.type] || d.type || "recomendação";
  let target = d.pool || rec?.pool;
  const parts = target ? String(target).split("/") : [];
  if (parts.length === 3) target = `${parts[2]} (${parts[0]})`;
  return `<b>${escapeHtml(label)}</b>${target ? ` em <code>${escapeHtml(target)}</code>` : ""}`;
}

function describeAudit(e) {
  const d = e.details || {};
  const who = `<b>${escapeHtml(auditActor(d))}</b>`;
  switch (e.event) {
    case "evaluate": {
      const n = d.recommendations ?? 0;
      const src = d.source === "agent" || d.source === "ingest" ? " com dados do agente" : "";
      const kept = d.decisions_kept ? ` · ${d.decisions_kept} decisões anteriores mantidas` : "";
      return { text: `${who} rodou uma avaliação do cluster${src}: <b>${n}</b> ${n === 1 ? "recomendação" : "recomendações"}${kept}`,
        tone: d.decision_allowed === false ? "warn" : null };
    }
    case "approve": return { text: `${who} aprovou ${auditRec(d)}` };
    case "reject": return { text: `${who} rejeitou ${auditRec(d)}${d.reason ? ` — motivo: “${escapeHtml(d.reason)}”` : ""}` };
    case "execute": {
      const sim = /\[demo\]/.test(d.output || "") ? ' <span class="audit-tag">simulado</span>' : "";
      return d.success
        ? { text: `${who} executou ${auditRec(d)} com sucesso${sim}` }
        : { text: `${who} tentou executar ${auditRec(d)}, mas <b>falhou</b>${sim}`, tone: "bad" };
    }
    case "journal_created": return { text: `${who} registrou ${JOURNAL_KIND_LABELS[d.kind] || "um item"} no diário: “${escapeHtml(d.title || "")}”` };
    case "journal_updated": return { text: `${who} marcou um item do diário como <b>${escapeHtml(JOURNAL_STATUS_LABELS[d.status] || d.status || "atualizado")}</b>` };
    case "journal_deleted": return { text: `${who} removeu um item do diário` };
    case "alerts_sent": return { text: `${d.count || 0} ${d.count === 1 ? "alerta enviado" : "alertas enviados"} para os canais configurados` };
    case "alert_settings": return { text: `${who} alterou as configurações de alerta${d.min_severity ? ` (severidade mínima: ${escapeHtml(d.min_severity)})` : ""}` };
    case "cost_settings": return { text: d.machine_prices
      ? `${who} atualizou a tabela de custos: ${d.machine_prices} tipo(s) de máquina${d.fixed_costs ? ` e ${d.fixed_costs} custo(s) fixo(s)` : ""}`
      : `${who} alterou os custos de referência: R$ ${escapeHtml(d.cpu_month)}/vCPU e R$ ${escapeHtml(d.gb_month)}/GB por mês` };
    case "assistant_config": return { text: `${who} configurou o Assistente IA${d.model ? ` (${escapeHtml(d.model)})` : ""}` };
    case "assistant_query": return { text: `${who} perguntou ao Assistente IA: “${escapeHtml((d.question || "").slice(0, 120))}”` };
    case "invite": return { text: `${who} convidou ${d.email ? `<b>${escapeHtml(d.email)}</b>` : "um usuário"} como ${escapeHtml(ROLE_LABELS[d.role] || d.role || "")}` };
    case "role_change": return { text: `${who} alterou o perfil de um usuário para <b>${escapeHtml(ROLE_LABELS[d.role] || d.role || "")}</b>` };
    case "user_removed": return { text: `${who} removeu um usuário` };
    case "license_installed": return { text: `${who} instalou a licença <b>${escapeHtml(d.plan || "")}</b>${d.customer ? ` de ${escapeHtml(d.customer)}` : ""}` };
    case "support_bundle": return { text: `${who} gerou um pacote de suporte` };
    case "agent_cluster_created": return { text: `${who} cadastrou o cluster <b>${escapeHtml(d.cluster || "")}</b>` };
    case "agent_token_rotated": return { text: `${who} gerou um novo token para o agente do cluster` };
    default: return { text: `${who} · ${escapeHtml(e.event)}` };
  }
}

function renderAudit(entries) {
  document.getElementById("audit-log").innerHTML = entries.length
    ? entries.map((e) => {
        const [cat, tone, icon] = AUDIT_META[e.event] || ["Evento", "cfg", "•"];
        const { text, tone: override } = describeAudit(e);
        const t = override || tone;
        const d = e.details || {};
        const extra = e.event === "execute" && d.output
          ? `<pre class="audit-output">${escapeHtml(d.output)}</pre>` : "";
        return `
        <div class="audit-entry">
          <span class="audit-icon t-${t}" aria-hidden="true">${icon}</span>
          <div class="audit-main">
            <div class="audit-line">${text}</div>
            <div class="audit-meta">
              <span class="audit-chip t-${t}">${escapeHtml(cat)}</span>
              <span>${formatDate(e.timestamp)}</span>
              ${d.cluster ? `<span>· ${escapeHtml(d.cluster)}</span>` : ""}
            </div>
            <details class="audit-raw">
              <summary>Detalhes técnicos</summary>
              ${extra}
              <pre>${escapeHtml(JSON.stringify(d, null, 2))}</pre>
            </details>
          </div>
        </div>`;
      }).join("")
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

// Sem licença válida: só a visão geral (nota e número de riscos). As demais telas mostram o aviso.
const LOCKED_TABS = ["recommendations", "capacity", "scheduling", "costs"];

function trialLinkHtml(url, cls = "btn btn-primary") {
  if (!url || !/^https?:\/\//.test(url)) return "";
  return `<a class="${cls}" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Pedir teste grátis de 30 dias</a>`;
}

function lockCardHtml() {
  const msg = state.status?.license_message || "Esta tela exige uma licença válida.";
  const trial = trialLinkHtml(state.status?.trial_url);
  const install = can("admin")
    ? `<button class="btn ${trial ? "btn-ghost" : "btn-primary"}" type="button" data-lock-goto="users">Já tenho a licença</button>`
    : "";
  return `<div class="license-lock-icon" aria-hidden="true">🔒</div>
    <h3>Licença necessária</h3>
    <p>${escapeHtml(msg)}</p>
    <p class="license-lock-sub">Com o teste grátis você vê cada risco, as recomendações e os custos do seu cluster por 30 dias.</p>
    <div class="license-lock-actions">${trial}${install}</div>
    ${can("admin") ? "" : `<p class="license-lock-sub">Fale com o administrador do painel para instalar a licença.</p>`}`;
}

function applyLicenseLock() {
  const locked = !!state.status?.license_locked;
  document.body.classList.toggle("license-locked", locked);
  LOCKED_TABS.forEach((tab) => {
    const panel = document.getElementById(`tab-${tab}`);
    if (!panel) return;
    let card = panel.querySelector(":scope > .license-lock");
    if (locked && !card) {
      card = document.createElement("div");
      card.className = "panel license-lock";
      panel.prepend(card);
    }
    if (card) card.innerHTML = locked ? lockCardHtml() : "";
    panel.classList.toggle("locked", locked);
  });
}

document.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-lock-goto]");
  if (btn) switchTab(btn.dataset.lockGoto);
});

async function loadStatus() {
  state.status = await API.get("/status");
  const banner = document.getElementById("demo-banner");
  banner.classList.toggle("hidden", !state.status.demo_only);
  if (state.status.demo_only) {
    banner.innerHTML = `<strong>Demonstração</strong> · empresa e cluster fictícios, nada aqui é um ambiente real.
      ${state.status.demo_contact ? `Quer ver no seu cluster? <span class="demo-contact">${escapeHtml(state.status.demo_contact)}</span>` : ""}`;
  }
  applyLicenseLock();
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
  if (!state.selectedClusterId || state.status?.license_locked) {
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
  if (chatHistory.length) {  // a conversa anterior era sobre outro cluster
    chatHistory.length = 0;
    renderChat();
  }
  await refresh();
  renderChat();
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

function nodeLayer(label, use, req) {
  const hot = (use ?? 0) >= 85 || (req ?? 0) >= 95;
  return `
    <div class="nt-row">
      <div class="nt-row-head"><span>${label}</span><span class="mono">${use === null || use === undefined ? "sem métrica" : formatPct(use)} <span class="nt-dim">/ ${formatPct(req)} res.</span></span></div>
      <div class="nt-track">
        <div class="nt-req" style="width:${Math.min(req || 0, 100)}%"></div>
        <div class="nt-use ${hot ? "hot" : ""}" style="width:${Math.min(use || 0, 100)}%"></div>
      </div>
    </div>`;
}

function renderNodesUsage() {
  const el = document.getElementById("nodes-usage");
  if (state.status?.license_locked) {
    el.innerHTML = `<div class="empty-state"><p>🔒 O mapa de nodes exige uma licença válida.</p></div>`;
    return;
  }
  const nodes = state.status?.latest_report?.nodes_usage || [];
  if (!nodes.length) {
    el.innerHTML = `<div class="empty-state"><p>Execute uma nova avaliação para ver o consumo por node</p></div>`;
    return;
  }
  const sorted = [...nodes].sort((a, b) => (a.control_plane - b.control_plane)
    || ((b.mem_usage_pct ?? 0) - (a.mem_usage_pct ?? 0)));
  el.innerHTML = `
    <div class="node-grid">${sorted.map((n) => `
      <button class="node-tile ${n.ready ? "" : "down"}" data-node="${escapeHtml(n.name)}" title="Ver pods e serviços deste node">
        <div class="nt-head">
          <span class="nt-dot ${n.ready ? "ok" : "bad"}"></span>
          <strong class="nt-name">${escapeHtml(n.name)}</strong>
          <span class="nt-arrow">›</span>
        </div>
        <div class="nt-meta">${escapeHtml(n.pool)}${n.control_plane ? " · control plane" : ""} · ${n.pod_count}${n.pods_capacity ? "/" + n.pods_capacity : ""} pods${n.ready ? "" : " · NotReady"}</div>
        ${nodeLayer("CPU", n.cpu_usage_pct, n.cpu_req_pct)}
        ${nodeLayer("Memória", n.mem_usage_pct, n.mem_req_pct)}
      </button>`).join("")}
    </div>
    <p class="ov-foot">Clique em um node para ver os pods e serviços dele. Percentuais sobre o allocatable: "em uso" vem do metrics-server; "reservado" é a soma dos requests dos pods.</p>`;
}

const REC_TYPE_LABELS = {
  RIGHTSIZE_REQUESTS: "Ajustar requests (sobra)",
  INCREASE_REQUESTS: "Aumentar requests (pressão)",
  MISSING_REQUESTS: "Definir requests ausentes",
  INCREASE_REPLICAS: "Aumentar réplicas",
  REDUCE_REPLICAS: "Reduzir réplicas",
  CREATE_HPA: "Criar HPA",
  HPA_AT_MAX: "HPA no limite",
  HPA_WITHOUT_REQUESTS: "HPA sem requests",
  UNDERUTILIZED: "Pool subutilizado",
  UNDERUTILIZED_POOL: "Pool de nodes subutilizado",
  SCHEDULING_MEMORY: "Pods sem memória para agendar",
  SCHEDULING_CPU: "Pods sem CPU para agendar",
  SCHEDULING_COMBINED: "Pods sem CPU e memória para agendar",
  PVC_SCHEDULING: "Pods presos por volume (PVC)",
  UNKNOWN_SCHEDULING: "Pods Pending (causa a investigar)",
};
const SEV_RANK = { HIGH: 0, MEDIUM: 1, LOW: 2 };

function renderExecutiveOverview() {
  const ov = state.status?.latest_report?.overview;
  const hero = document.getElementById("ov-hero");
  if (!ov) {
    hero.innerHTML = `<div class="ov-hero-empty"><h2>Sem avaliação ainda</h2><p>Clique em <strong>Nova avaliação</strong> para gerar a nota de saúde do cluster.</p></div>`;
    ["ov-kpis", "ov-risks", "ov-savings"].forEach((id) => { document.getElementById(id).innerHTML = ""; });
    return;
  }
  const tone = ov.score >= 85 ? "ok" : ov.score >= 60 ? "warn" : "bad";
  const R = 52;
  const circ = 2 * Math.PI * R;
  const created = state.status?.latest_report?.created_at;
  hero.innerHTML = `
    <div class="ov-ring ${tone}" title="${escapeHtml((ov.factors || []).map((f) => `${f.points} ${f.reason}`).join("\n") || "Sem descontos")}">
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle cx="60" cy="60" r="${R}" class="ring-bg"/>
        <circle cx="60" cy="60" r="${R}" class="ring-fg" transform="rotate(-90 60 60)"
          stroke-dasharray="${circ}" stroke-dashoffset="${circ * (1 - ov.score / 100)}"/>
      </svg>
      <div class="ov-ring-label"><strong>${ov.score}</strong><span>de 100</span></div>
    </div>
    <div class="ov-hero-text">
      <span class="chip chip-${tone}">${escapeHtml(ov.status)}</span>
      <h2>${escapeHtml(ov.headline)}</h2>
      <p>${escapeHtml(ov.explanation)}</p>
      ${created ? `<span class="ov-when">Avaliação de ${formatDate(created)}</span>` : ""}
    </div>`;

  const k = ov.kpis || {};
  const kpi = (label, value, sub, cls = "", goto = "") => goto
    ? `<button type="button" class="kpi kpi-link" data-kpi-goto="${goto}" title="Abrir a tela de custos"><span class="kpi-label">${label}</span><strong class="kpi-value ${cls}">${value}</strong><span class="kpi-sub">${sub}</span></button>`
    : `<div class="kpi"><span class="kpi-label">${label}</span><strong class="kpi-value ${cls}">${value}</strong><span class="kpi-sub">${sub}</span></div>`;
  document.getElementById("ov-kpis").innerHTML = [
    kpi("Riscos ativos", k.risks ?? 0, k.risks_high ? `${k.risks_high} crítico(s)` : "nenhum crítico", k.risks_high ? "bad" : k.risks ? "warn" : "ok"),
    ov.locked ? kpi("Economia potencial", "🔒", "disponível com licença") : kpi("Economia potencial", k.savings_monthly === null || k.savings_monthly === undefined ? "—" : formatBRL(k.savings_monthly),
      k.savings_monthly === null || k.savings_monthly === undefined ? "configure custos em Usuários e custos" : `por mês · ver detalhes em Custos →`, "ok", "costs"),
    cpuReservedKpi(kpi, k.cpu_efficiency_pct),
    kpi("Disponibilidade", k.pods_ok_pct === null || k.pods_ok_pct === undefined ? "—" : `${k.pods_ok_pct}%`, `pods saudáveis · ${k.nodes_ready}/${k.nodes_total} nodes Ready`,
      (k.pods_ok_pct ?? 100) < 95 ? "warn" : "ok"),
  ].join("");

  if (ov.locked) {
    const lockHtml = `<div class="ov-empty license-lock-inline">🔒 ${escapeHtml(state.status?.license_message || "")}
      <span class="license-lock-actions">${trialLinkHtml(state.status?.trial_url, "btn btn-primary btn-sm")}
      ${can("admin") ? `<button class="btn btn-ghost btn-sm" type="button" data-lock-goto="users">Já tenho a licença</button>` : ""}</span></div>`;
    document.getElementById("ov-risks").innerHTML = lockHtml;
    document.getElementById("ov-savings").innerHTML = `<div class="ov-empty">Disponível com licença.</div>`;
    return;
  }

  const risks = ov.top_risks || [];
  document.getElementById("ov-risks").innerHTML = risks.length ? risks.map((r, i) => {
    let btn = "";
    if (r.key.startsWith("node-")) btn = `<button class="btn btn-ghost btn-sm" data-risk-node="${escapeHtml(r.key.split(":").slice(1).join(":"))}">Ver node</button>`;
    else if (r.key.startsWith("pod:")) btn = `<button class="btn btn-ghost btn-sm" data-risk-ai="${i}">Diagnosticar com IA</button>`;
    else if (r.key.startsWith("rec:")) btn = `<button class="btn btn-ghost btn-sm" data-goto-rec="${escapeHtml(r.key.slice(4))}">Ver recomendação</button>`;
    else if (r.key === "agent-stale") btn = `<button class="btn btn-ghost btn-sm" data-risk-goto="cluster">Ver conexão</button>`;
    else btn = `<button class="btn btn-ghost btn-sm" data-risk-goto="scheduling">Ver scheduling</button>`;
    return `
      <div class="ov-item">
        <span class="chip chip-${r.severity === "HIGH" ? "bad" : "warn"}">${r.severity === "HIGH" ? "CRÍTICO" : "ATENÇÃO"}</span>
        <div class="ov-item-text"><strong>${escapeHtml(r.title)}</strong><span>${escapeHtml(r.detail)}</span></div>
        <div class="ov-item-actions">${btn}${can("operador") ? `<button class="btn btn-ghost btn-sm btn-icon" title="Registrar no diário de bordo" data-risk-journal="${i}">＋</button>` : ""}</div>
      </div>`;
  }).join("") : `<div class="ov-empty">✓ Nenhum risco ativo na última avaliação.</div>`;

  const savings = ov.top_savings || [];
  document.getElementById("ov-savings").innerHTML = savings.length ? savings.map((s) => `
    <div class="ov-item">
      <strong class="ov-money">${formatBRL(s.monthly)}<small>/mês</small></strong>
      <div class="ov-item-text"><strong>${escapeHtml(REC_TYPE_LABELS[s.type] || s.type)}</strong><span>${escapeHtml(s.target || "")}</span></div>
      <button class="btn btn-ghost btn-sm" data-goto-rec="${escapeHtml(s.id || "")}">Revisar</button>
    </div>`).join("") : `<div class="ov-empty">${k.savings_monthly === null || k.savings_monthly === undefined
      ? "Cadastre o preço dos seus tipos de máquina em Usuários e custos para estimar economias."
      : "Nenhuma economia relevante identificada agora."}</div>`;
}

document.getElementById("tab-overview").addEventListener("click", (event) => {
  const kg = event.target.closest("[data-kpi-goto]");
  if (kg) return switchTab(kg.dataset.kpiGoto);
  const nodeBtn = event.target.closest("[data-risk-node]");
  if (nodeBtn) return showNodeDetail(nodeBtn.dataset.riskNode);
  const goto = event.target.closest("[data-risk-goto]");
  if (goto) return switchTab(goto.dataset.riskGoto);
  const rec = event.target.closest("[data-goto-rec]");
  if (rec) return focusRecommendation(rec.dataset.gotoRec);
  const jr = event.target.closest("[data-risk-journal]");
  if (jr) {
    const r = (state.status?.latest_report?.overview?.top_risks || [])[Number(jr.dataset.riskJournal)];
    if (r) {
      const node = r.key.startsWith("node-") ? r.key.split(":").slice(1).join(":") : null;
      const recId = r.key.startsWith("rec:") ? r.key.slice(4) : null;
      showJournalForm("pendencia", { title: r.title, body: r.detail,
        link_type: node ? "node" : recId ? "recommendation" : "risk", link_ref: node || recId || r.key });
    }
    return;
  }
  const jopen = event.target.closest("[data-journal-open]");
  if (jopen) { switchTab("journal"); return; }
  const ai = event.target.closest("[data-risk-ai]");
  if (ai) {
    const r = (state.status?.latest_report?.overview?.top_risks || [])[Number(ai.dataset.riskAi)];
    switchTab("assistant");
    const input = document.getElementById("chat-input");
    if (input && r) { input.value = `Diagnostique: ${r.title}. ${r.detail}`; input.focus(); }
  }
});

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
    ${can("operador") ? `<button class="btn btn-ghost" id="node-journal">Registrar pendência</button>` : ""}
    <button class="btn btn-primary" id="node-ask-ai">Analisar este node com o Assistente IA</button>`;
  document.getElementById("node-journal")?.addEventListener("click", () => {
    showJournalForm("pendencia", { title: `Node ${name}: `, link_type: "node", link_ref: name });
  });
  document.getElementById("node-ask-ai").addEventListener("click", () => {
    closeModal();
    switchTab("assistant");
    document.getElementById("chat-input").value =
      `Analise o node ${name}: quais pods mais consomem, quais estão sem requests e qual o risco de falta de memória ou CPU?`;
  });
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

function costMachineRow(m = {}) {
  return `<div class="cost-row cost-row-machine">
    <input class="cm-match" list="cost-machine-options" maxlength="120" placeholder="tipo de máquina, pool ou *" value="${escapeHtml(m.match || "")}" aria-label="Tipo de máquina">
    <input class="cm-price" type="number" min="0" step="0.0001" placeholder="preço" value="${m.price ?? ""}" aria-label="Preço">
    <select class="cm-unit" aria-label="Unidade"><option value="hour"${m.unit === "hour" ? " selected" : ""}>R$ por hora</option><option value="month"${m.unit !== "hour" ? " selected" : ""}>R$ por mês</option></select>
    <span class="cm-month"></span>
    <button class="btn btn-ghost btn-sm btn-icon" type="button" data-cost-remove title="Remover">✕</button>
  </div>`;
}

function costFixedRow(f = {}) {
  return `<div class="cost-row cost-row-fixed">
    <input class="cf-name" maxlength="80" placeholder="ex.: Load balancer" value="${escapeHtml(f.name || "")}" aria-label="Descrição">
    <input class="cf-monthly" type="number" min="0" step="0.01" placeholder="R$ por mês" value="${f.monthly ?? ""}" aria-label="Valor mensal">
    <input class="cf-qty" type="number" min="1" step="1" placeholder="qtd" value="${f.qty ?? 1}" aria-label="Quantidade">
    <span class="cm-month"></span>
    <button class="btn btn-ghost btn-sm btn-icon" type="button" data-cost-remove title="Remover">✕</button>
  </div>`;
}

function updateCostPreview() {
  document.querySelectorAll(".cost-row-machine").forEach((row) => {
    const price = Number(row.querySelector(".cm-price").value || 0);
    const monthly = row.querySelector(".cm-unit").value === "hour" ? price * 730 : price;
    row.querySelector(".cm-month").textContent = price ? `≈ ${formatBRL(monthly)}/mês por node` : "";
  });
  document.querySelectorAll(".cost-row-fixed").forEach((row) => {
    const v = Number(row.querySelector(".cf-monthly").value || 0) * Number(row.querySelector(".cf-qty").value || 1);
    row.querySelector(".cm-month").textContent = v ? `= ${formatBRL(v)}/mês` : "";
  });
}

function renderCostDetected(machinePrices) {
  const c = state.status?.latest_report?.cluster_cost;
  const types = c?.machine_types || [];
  const priced = new Set(machinePrices.map((m) => String(m.match).toLowerCase()));
  document.getElementById("cost-machine-options").innerHTML = types.map((t) => `<option value="${escapeHtml(t)}">`).join("");
  document.getElementById("cost-detected").innerHTML = types.length
    ? `<span>No cluster ativo:</span> ${types.map((t) => priced.has(t.toLowerCase())
        ? `<span class="chip chip-ok">✓ ${escapeHtml(t)}</span>`
        : `<button type="button" class="chip chip-warn" data-cost-add="${escapeHtml(t)}" title="Adicionar preço">+ ${escapeHtml(t)} · sem preço</button>`).join(" ")}`
    : "";
}

async function loadCosts() {
  try {
    const c = await API.get("/costs");
    document.getElementById("cost-cpu").value = c.cpu_month || "";
    document.getElementById("cost-gb").value = c.gb_month || "";
    const machines = c.machine_prices || [];
    document.getElementById("cost-machines").innerHTML = (machines.length ? machines : [{}]).map(costMachineRow).join("");
    document.getElementById("cost-fixed").innerHTML = (c.fixed_costs || []).map(costFixedRow).join("");
    renderCostDetected(machines);
    updateCostPreview();
  } catch (e) { /* sem permissão */ }
}

document.getElementById("cost-add-machine").addEventListener("click", () => {
  document.getElementById("cost-machines").insertAdjacentHTML("beforeend", costMachineRow());
});
document.getElementById("cost-add-fixed").addEventListener("click", () => {
  document.getElementById("cost-fixed").insertAdjacentHTML("beforeend", costFixedRow());
});
document.getElementById("cost-panel").addEventListener("click", (event) => {
  const rm = event.target.closest("[data-cost-remove]");
  if (rm) { rm.closest(".cost-row").remove(); return; }
  const add = event.target.closest("[data-cost-add]");
  if (add) {
    const empty = [...document.querySelectorAll(".cm-match")].find((i) => !i.value);
    if (empty) empty.value = add.dataset.costAdd;
    else document.getElementById("cost-machines").insertAdjacentHTML("beforeend", costMachineRow({ match: add.dataset.costAdd, unit: "hour" }));
    add.remove();
    document.querySelector(".cost-row-machine:last-child .cm-price")?.focus();
  }
});
document.getElementById("cost-panel").addEventListener("input", updateCostPreview);

document.getElementById("cost-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const machine_prices = [...document.querySelectorAll(".cost-row-machine")].map((row) => ({
    match: row.querySelector(".cm-match").value.trim(),
    price: Number(row.querySelector(".cm-price").value || 0),
    unit: row.querySelector(".cm-unit").value,
  })).filter((m) => m.match && m.price > 0);
  const fixed_costs = [...document.querySelectorAll(".cost-row-fixed")].map((row) => ({
    name: row.querySelector(".cf-name").value.trim() || "Custo fixo",
    monthly: Number(row.querySelector(".cf-monthly").value || 0),
    qty: Number(row.querySelector(".cf-qty").value || 1),
  })).filter((f) => f.monthly > 0 && f.qty > 0);
  try {
    const res = await fetch("/api/costs", {
      method: "PUT",
      headers: { "Content-Type": "application/json",
        ...(state.selectedClusterId ? { "X-Cluster-Id": state.selectedClusterId } : {}) },
      body: JSON.stringify({
        cpu_month: Number(document.getElementById("cost-cpu").value || 0),
        gb_month: Number(document.getElementById("cost-gb").value || 0),
        machine_prices, fixed_costs,
      }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Erro ${res.status}`);
    toast("Custos salvos. Clique em Nova Avaliação para recalcular.", "success");
    await loadCosts();
  } catch (e) {
    toast(e.message, "error");
  }
});

// ── Licença ─────────────────────────────────────────────────

const PLAN_LABELS = { community: "Sem licença", essencial: "Essencial", profissional: "Profissional",
  enterprise: "Enterprise", pro: "Pro" };

const LICENSE_STATES = { valid: "válida", grace: "em carência", expired: "vencida", invalid: "inválida", community: "sem licença" };

function licenseNodesHtml(lic) {
  const u = lic.node_usage;
  const used = u && u.clusters ? `média de ${String(u.avg_nodes).replace(".", ",")} nos últimos ${u.days} dias · ${u.now_nodes} agora · pico ${u.peak_nodes}` : "sem histórico ainda";
  if (!lic.max_nodes) return `sem limite · ${used}`;
  return `até ${lic.max_nodes} (média do mês) · ${used}${lic.nodes_over
    ? ` <span class="chip chip-warn">acima do contratado</span>` : ""}`;
}

async function loadLicense() {
  try {
    state.license = await API.get("/license");
  } catch (e) {
    return;
  }
  const lic = state.license;
  const banner = document.getElementById("license-banner");
  const warn = ["community", "grace", "expired", "invalid"].includes(lic.state) || (lic.days_left !== null && lic.days_left <= 30)
    || lic.nodes_over;
  banner.classList.toggle("hidden", !warn || !can("admin") || state.status?.demo_only);
  const label = lic.plan_label || PLAN_LABELS[lic.plan] || lic.plan;
  const nodesMsg = lic.nodes_over
    ? ` O uso médio de nodes (${String(lic.node_usage.avg_nodes).replace(".", ",")}) passou do contratado (${lic.max_nodes}). Fale com o fornecedor para ajustar o plano.`
    : "";
  document.getElementById("license-banner-text").innerHTML =
    `<strong>${lic.plan === "community" ? "Licença" : `Licença ${escapeHtml(label)}`}:</strong> ${escapeHtml(lic.message + nodesMsg)}`;
  const features = (lic.features || []).map((f) => escapeHtml(lic.feature_labels?.[f] || f)).join(", ") || "—";
  const info = document.getElementById("license-info");
  if (info) {
    info.innerHTML = `
      <dl class="rec-detail">
        <dt>Plano</dt><dd>${escapeHtml(lic.plan_label || PLAN_LABELS[lic.plan] || lic.plan)} (${escapeHtml(LICENSE_STATES[lic.state] || lic.state)})</dd>
        <dt>Cliente</dt><dd>${escapeHtml(lic.customer || "—")}</dd>
        <dt>Limites</dt><dd>${lic.max_clusters} cluster(s), ${lic.max_users} usuário(s)</dd>
        <dt>Nodes</dt><dd>${licenseNodesHtml(lic)}</dd>
        <dt>Recursos</dt><dd>${features}</dd>
        <dt>Validade</dt><dd>${lic.expires_at ? formatDate(lic.expires_at) : "—"}</dd>
        <dt>Situação</dt><dd>${escapeHtml(lic.message)}</dd>
      </dl>
      ${lic.trial_url ? `<div class="license-trial">${trialLinkHtml(lic.trial_url)}<span class="form-hint">Receba uma licença de teste com todos os recursos por 30 dias.</span></div>` : ""}`;
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
    await refresh();
  } catch (e) {
    toast(e.message, "error");
  }
});

// ── Assistente de IA ────────────────────────────────────────

const chatHistory = [];

function activeClusterLabel() {
  const sel = document.getElementById("cluster-selector");
  const opt = sel && sel.selectedOptions && sel.selectedOptions[0];
  return (opt && opt.textContent.trim()) || "ativo";
}

function renderChat() {
  const log = document.getElementById("chat-log");
  log.innerHTML = chatHistory.map((m) => `
    <div style="margin:8px 0;padding:10px 12px;border-radius:8px;background:${m.role === "user" ? "var(--bg-elevated, rgba(59,130,246,.12))" : "rgba(255,255,255,.04)"}">
      <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">${m.role === "user" ? "Você" : "Assistente"}${m.tools ? " · consultou: " + escapeHtml(m.tools.join(", ")) : ""}</div>
      <div style="white-space:pre-wrap">${escapeHtml(m.content)}</div>
    </div>`).join("") || `<div class="empty-state"><p>Faça uma pergunta sobre o cluster <b>${escapeHtml(activeClusterLabel())}</b>.<br>
      <span style="font-size:12px">Ao trocar o cluster ativo no topo, a conversa recomeça com os dados do novo cluster.</span></p></div>`;
  log.scrollTop = log.scrollHeight;
}

const AI_FIELD_HINTS = {
  default: { base: "URL base (opcional)", basePh: "Ollama: http://ollama:11434/v1 · Azure: https://<recurso>.openai.azure.com/openai/deployments/<deploy>",
    ver: "api-version (somente Azure)", verPh: "", model: "ex.: claude-sonnet-5-5 · gpt-4o · llama3.1", auth: true },
  tess: { base: "ID do agente Tess", basePh: "ex.: 12345 (número do agente de chat na Tess)",
    ver: "ID do workspace Tess", verPh: "ex.: 6789", model: "slug do modelo na Tess, ex.: tess-5", auth: false },
};

function updateAiFields() {
  const h = AI_FIELD_HINTS[document.getElementById("ai-provider").value] || AI_FIELD_HINTS.default;
  document.getElementById("ai-base-url-label").textContent = h.base;
  document.getElementById("ai-base-url").placeholder = h.basePh;
  document.getElementById("ai-api-version-label").textContent = h.ver;
  document.getElementById("ai-api-version").placeholder = h.verPh;
  document.getElementById("ai-model").placeholder = h.model;
  document.getElementById("ai-auth-header-group").classList.toggle("hidden", !h.auth);
}
document.getElementById("ai-provider").addEventListener("change", updateAiFields);

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
  updateAiFields();
  document.getElementById("ai-config-status").textContent =
    (data.licensed ? "" : "Licença atual não inclui o assistente. ") +
    (c.model ? `Configurado: ${c.provider} · ${c.model}${c.has_key ? " · chave salva" : ""}` : "Não configurado");
}

document.getElementById("assistant-config-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(event.currentTarget));
  for (const k of ["base_url", "api_version"]) if (!body[k]) body[k] = null;
  if (body.provider === "tess") delete body.auth_header;
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

// ── Diário de bordo ─────────────────────────────────────────
const JOURNAL_STATUS = { aberta: "Aberta", andamento: "Em andamento", concluida: "Concluída" };
state.journalFilter = "abertas";

function fmtDay(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}

function journalLink(e) {
  if (!e.link_type || !e.link_ref) return "";
  const label = { node: "Node", recommendation: "Recomendação", pod: "Pod", risk: "Risco" }[e.link_type] || e.link_type;
  return `<button class="j-link" data-jlink-type="${escapeHtml(e.link_type)}" data-jlink-ref="${escapeHtml(e.link_ref)}">${label}: ${escapeHtml(e.link_ref)} ›</button>`;
}

function journalDue(e) {
  if (!e.due_date) return "";
  return `<span class="j-due ${e.overdue ? "late" : ""}">${e.overdue ? "Venceu em " : "Prazo "}${fmtDay(e.due_date)}</span>`;
}

async function loadJournalSummary() {
  const el = document.getElementById("ov-journal");
  if (!el || !state.selectedClusterId) return;
  try {
    const data = await API.get("/journal?status=abertas&kind=pendencia");
    const s = data.summary || { open: 0, top: [] };
    const nav = document.querySelector('.nav-item[data-tab="journal"]');
    if (nav) nav.innerHTML = `Diário de bordo${s.open ? ` <span class="nav-count ${s.overdue ? "late" : ""}">${s.open}</span>` : ""}`;
    el.innerHTML = s.top.length ? s.top.map((e) => `
      <div class="ov-item">
        <span class="chip chip-${e.overdue ? "bad" : e.status === "andamento" ? "info" : "warn"}">${e.overdue ? "ATRASADA" : JOURNAL_STATUS[e.status].toUpperCase()}</span>
        <div class="ov-item-text"><strong>${escapeHtml(e.title)}</strong>
          <span>${[e.assignee ? `Responsável: ${escapeHtml(e.assignee)}` : "", e.due_date ? `Prazo ${fmtDay(e.due_date)}` : ""].filter(Boolean).join(" · ") || "Sem responsável e sem prazo"}</span></div>
        <button class="btn btn-ghost btn-sm" data-journal-open="1">Abrir</button>
      </div>`).join("") + (s.open > 3 ? `<p class="ov-foot">+ ${s.open - 3} pendência(s) no diário de bordo.</p>` : "")
      : `<div class="ov-empty">Nenhuma pendência aberta. Use o <strong>＋</strong> nos riscos, nodes ou recomendações para registrar.</div>`;
  } catch (e) {
    el.innerHTML = `<div class="ov-empty">${escapeHtml(e.message)}</div>`;
  }
}

async function loadJournal() {
  const el = document.getElementById("journal-list");
  if (!state.selectedClusterId) {
    el.innerHTML = `<div class="empty-state"><p>Selecione um cluster para ver o diário de bordo</p></div>`;
    return;
  }
  try {
    const data = await API.get(`/journal?status=${encodeURIComponent(state.journalFilter)}`);
    renderJournal(data.items || []);
  } catch (e) {
    el.innerHTML = `<div class="empty-state"><p>${escapeHtml(e.message)}</p></div>`;
  }
}

function renderJournal(items) {
  const el = document.getElementById("journal-list");
  if (!items.length) {
    el.innerHTML = `<div class="panel"><div class="panel-body"><div class="empty-state"><p>Nada por aqui. Registre pendências e notas do dia a dia do cluster.</p></div></div></div>`;
    return;
  }
  const editor = can("operador");
  el.innerHTML = `<div class="j-list">${items.map((e) => `
    <article class="j-card ${e.kind} ${e.status} ${e.overdue ? "overdue" : ""}">
      <div class="j-head">
        <span class="chip ${e.kind === "nota" ? "chip-info" : e.overdue ? "chip-bad" : e.status === "concluida" ? "chip-ok" : e.status === "andamento" ? "chip-info" : "chip-warn"}">${e.kind === "nota" ? "NOTA" : e.overdue ? "ATRASADA" : JOURNAL_STATUS[e.status].toUpperCase()}</span>
        <strong class="j-title">${escapeHtml(e.title)}</strong>
        ${journalDue(e)}
      </div>
      ${e.body ? `<p class="j-body">${escapeHtml(e.body)}</p>` : ""}
      <div class="j-foot">
        <span>${escapeHtml(e.created_by)} · ${formatDate(e.created_at)}${e.assignee ? ` · Responsável: <b>${escapeHtml(e.assignee)}</b>` : ""}${e.closed_at && e.kind === "pendencia" ? ` · concluída ${formatDate(e.closed_at)}` : ""}</span>
        ${journalLink(e)}
        <span class="j-actions">
          ${editor && e.kind === "pendencia" ? `<select class="j-status" data-jstatus-id="${e.id}">${Object.entries(JOURNAL_STATUS).map(([k, v]) => `<option value="${k}" ${k === e.status ? "selected" : ""}>${v}</option>`).join("")}</select>` : ""}
          ${editor ? `<button class="btn btn-ghost btn-sm" data-jedit="${e.id}">Editar</button>` : ""}
          ${can("admin") ? `<button class="btn btn-ghost btn-sm" data-jdel="${e.id}">Excluir</button>` : ""}
        </span>
      </div>
    </article>`).join("")}</div>`;
  state.journalItems = items;
}

function showJournalForm(kind, preset = {}, existing = null) {
  const v = existing || preset;
  const isTask = (existing?.kind || kind) === "pendencia";
  openModal(existing ? "Editar registro" : isTask ? "Nova pendência" : "Nota do dia", `
    <div class="form-group"><label>Título</label><input id="j-title" maxlength="200" value="${escapeHtml(v.title || "")}"></div>
    <div class="form-group"><label>${isTask ? "Descrição" : "O que aconteceu / o que foi feito"}</label><textarea id="j-body" rows="5" maxlength="5000">${escapeHtml(v.body || "")}</textarea></div>
    ${isTask ? `<div class="grid-2">
      <div class="form-group"><label>Responsável</label><input id="j-assignee" maxlength="120" value="${escapeHtml(v.assignee || state.user?.full_name || "")}"></div>
      <div class="form-group"><label>Prazo</label><input id="j-due" type="date" value="${escapeHtml(v.due_date || "")}"></div>
    </div>` : ""}
    ${v.link_type && v.link_ref ? `<p style="font-size:12px;color:var(--text-muted)">Vinculado a: ${escapeHtml(v.link_type)} ${escapeHtml(v.link_ref)}</p>` : ""}`,
    `<button class="btn btn-ghost" onclick="closeModal()">Cancelar</button>
     <button class="btn btn-primary" id="j-save">Salvar</button>`);
  setTimeout(() => document.getElementById("j-title")?.focus(), 30);
  document.getElementById("j-save").addEventListener("click", async () => {
    const body = {
      title: document.getElementById("j-title").value.trim(),
      body: document.getElementById("j-body").value.trim(),
    };
    if (isTask) {
      body.assignee = document.getElementById("j-assignee").value.trim();
      body.due_date = document.getElementById("j-due").value || "";
    }
    if (body.title.length < 2) return toast("Informe um título", "error");
    try {
      if (existing) await API.patch(`/journal/${existing.id}`, body);
      else await API.post("/journal", { ...body, kind, due_date: body.due_date || null,
        link_type: preset.link_type || null, link_ref: preset.link_ref || null });
      closeModal();
      toast(existing ? "Registro atualizado" : "Registrado no diário de bordo", "success");
      loadJournalSummary();
      if (state.currentTab === "journal") loadJournal();
    } catch (e) {
      toast(e.message, "error");
    }
  });
}

document.getElementById("journal-filters").addEventListener("click", (event) => {
  const btn = event.target.closest("[data-jstatus]");
  if (!btn) return;
  document.querySelectorAll("#journal-filters .filter-btn").forEach((b) => b.classList.toggle("active", b === btn));
  state.journalFilter = btn.dataset.jstatus;
  loadJournal();
});

document.querySelector(".journal-actions").addEventListener("click", (event) => {
  const btn = event.target.closest("[data-jnew]");
  if (!btn) return;
  if (!can("operador")) return toast("Seu perfil é somente leitura", "error");
  showJournalForm(btn.dataset.jnew, btn.dataset.jnew === "nota" ? { title: `Nota de ${new Date().toLocaleDateString("pt-BR")}` } : {});
});

document.getElementById("journal-list").addEventListener("click", async (event) => {
  const link = event.target.closest("[data-jlink-type]");
  if (link) {
    const { jlinkType, jlinkRef } = link.dataset;
    if (jlinkType === "node") showNodeDetail(jlinkRef);
    else if (jlinkType === "recommendation") focusRecommendation(jlinkRef);
    else switchTab("overview");
    return;
  }
  const edit = event.target.closest("[data-jedit]");
  if (edit) {
    const entry = (state.journalItems || []).find((e) => e.id === edit.dataset.jedit);
    if (entry) showJournalForm(entry.kind, {}, entry);
    return;
  }
  const del = event.target.closest("[data-jdel]");
  if (del) {
    if (!del.dataset.armed) {
      del.dataset.armed = "1";
      del.textContent = "Confirmar exclusão";
      del.classList.add("btn-danger");
      setTimeout(() => { if (del.isConnected) { delete del.dataset.armed; del.textContent = "Excluir"; del.classList.remove("btn-danger"); } }, 4000);
      return;
    }
    try {
      await API.delete(`/journal/${del.dataset.jdel}`);
      toast("Registro excluído", "success");
      loadJournal();
      loadJournalSummary();
    } catch (e) { toast(e.message, "error"); }
  }
});

document.getElementById("journal-list").addEventListener("change", async (event) => {
  const sel = event.target.closest("[data-jstatus-id]");
  if (!sel) return;
  try {
    await API.patch(`/journal/${sel.dataset.jstatusId}`, { status: sel.value });
    toast(`Status: ${JOURNAL_STATUS[sel.value]}`, "success");
    loadJournal();
    loadJournalSummary();
  } catch (e) { toast(e.message, "error"); }
});
