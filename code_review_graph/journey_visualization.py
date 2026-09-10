"""Human-friendly, self-contained visualization for full-stack journeys."""

from __future__ import annotations

import json
from pathlib import Path

from .graph import GraphStore
from .journeys import build_journeys


def generate_journeys_html(
    store: GraphStore,
    repo_root: str | Path,
    output_path: str | Path,
) -> Path:
    """Generate a searchable HTML explorer for every detailed journey."""
    output = Path(output_path)
    result = build_journeys(store, repo_root, limit=100_000, details=True)
    data_json = json.dumps(result, default=str).replace("</", "<\\/")
    html = _HTML_TEMPLATE.replace("__JOURNEY_DATA__", data_json)
    output.write_text(html, encoding="utf-8")
    return output


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Parcours · Code Review Graph</title>
<style>
  :root {
    color-scheme: light;
    --ink: #182331;
    --muted: #617083;
    --canvas: #edf1f5;
    --paper: #ffffff;
    --line: #d8e0e8;
    --frontend: #1677c8;
    --transport: #07866f;
    --application: #b96812;
    --repository: #7554b8;
    --database: #b23b55;
    --warning: #a45b00;
    --shadow: 0 14px 34px rgba(36, 51, 68, .10);
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--canvas);
    color: var(--ink);
    font: 14px/1.45 "Avenir Next", Avenir, "Segoe UI", sans-serif;
  }
  button, input, select { font: inherit; }
  button:focus-visible, input:focus-visible, select:focus-visible {
    outline: 3px solid rgba(22, 119, 200, .28);
    outline-offset: 2px;
  }
  .shell { display: grid; grid-template-columns: minmax(290px, 360px) 1fr; height: 100%; }
  .sidebar {
    display: flex; flex-direction: column; min-height: 0;
    background: #172331; color: #eef4fa; border-right: 1px solid #26384b;
  }
  .brand { padding: 24px 22px 18px; border-bottom: 1px solid #304153; }
  .brand h1 { margin: 0; font-size: 20px; letter-spacing: -.025em; }
  .brand p { margin: 5px 0 0; color: #aebdcb; font-size: 13px; }
  .controls { padding: 16px; border-bottom: 1px solid #304153; }
  .search {
    width: 100%; padding: 11px 12px; color: #f5f8fb; background: #223244;
    border: 1px solid #3a4d61; border-radius: 8px;
  }
  .search::placeholder { color: #9badbd; }
  .filters { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 9px; }
  .filters select {
    min-width: 0; padding: 8px 9px; color: #dce6ef; background: #223244;
    border: 1px solid #3a4d61; border-radius: 7px;
  }
  .result-count { margin-top: 10px; color: #9fb0c0; font-size: 12px; }
  .journey-list { overflow: auto; padding: 8px; }
  .journey-item {
    display: block; width: 100%; padding: 12px 13px; text-align: left; color: #e8eff6;
    background: transparent; border: 1px solid transparent; border-radius: 8px; cursor: pointer;
  }
  .journey-item + .journey-item { margin-top: 3px; }
  .journey-item:hover { background: #203043; }
  .journey-item.active { background: #293c50; border-color: #4b657d; }
  .journey-name { display: block; overflow: hidden; font-weight: 650; text-overflow: ellipsis; }
  .journey-domain, .journey-match { display: block; overflow: hidden; margin-top: 3px; color: #9fb0c0; font-size: 12px; text-overflow: ellipsis; }
  .journey-match { color: #69b9ef; }
  .badges { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
  .badge { padding: 2px 7px; border-radius: 999px; background: #3a4c5f; color: #dce6ef; font-size: 11px; }
  .badge.frontend { background: #124c79; color: #d7edff; }
  .badge.incomplete { background: #674312; color: #ffe8ba; }
  .main { min-width: 0; overflow: auto; padding: 28px clamp(20px, 4vw, 58px) 56px; }
  .empty { max-width: 620px; margin: 20vh auto 0; text-align: center; color: var(--muted); }
  .empty h2 { color: var(--ink); }
  .detail { max-width: 1180px; margin: 0 auto; }
  .detail-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
  .detail-header > div:first-child { min-width: 0; }
  .detail-header h2 { margin: 0; font-size: clamp(25px, 3vw, 38px); line-height: 1.12; letter-spacing: -.035em; overflow-wrap: anywhere; }
  .detail-header p { margin: 8px 0 0; color: var(--muted); }
  .header-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 12px; }
  .view-switch { display: flex; padding: 3px; border: 1px solid var(--line); border-radius: 9px; background: #e2e8ee; }
  .view-button { padding: 6px 11px; border: 0; border-radius: 6px; color: #526172; background: transparent; cursor: pointer; }
  .view-button.active { color: var(--ink); background: var(--paper); box-shadow: 0 1px 4px rgba(36, 51, 68, .16); }
  .status {
    flex: none; padding: 6px 10px; border: 1px solid #bad8c8; border-radius: 999px;
    background: #e6f5ed; color: #176840; font-size: 12px; font-weight: 650;
  }
  .status.incomplete { border-color: #ecd09a; background: #fff4d9; color: #865000; }
  .summary { display: flex; gap: 18px; margin: 24px 0; padding: 13px 16px; background: #e3e9ef; border-radius: 9px; color: #526172; }
  .summary strong { color: var(--ink); }
  .overview { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 24px; }
  .overview-column { min-width: 0; padding: 17px; border: 1px solid var(--line); border-radius: 10px; background: var(--paper); }
  .overview-column h3 { margin: 0 0 11px; color: var(--muted); font-size: 12px; font-weight: 650; }
  .overview-list { display: grid; gap: 7px; }
  .overview-item { overflow: hidden; padding: 8px 10px; border-radius: 7px; background: #edf2f6; font-weight: 600; text-overflow: ellipsis; }
  .overview-item.frontend { color: #0b5d99; background: #e2f3ff; }
  .overview-item.application { color: #8b4b08; background: #fff0dc; }
  .overview-item.database { color: #8e2940; background: #fde8ed; }
  .evidence-details { margin-top: 18px; border-top: 1px solid var(--line); }
  .evidence-details summary { width: max-content; margin-top: 14px; padding: 7px 0; color: var(--muted); cursor: pointer; }
  .section { margin-top: 30px; }
  .section-title { margin: 0 0 12px; font-size: 17px; letter-spacing: -.015em; }
  .consumer-card, .repository-card, .notice {
    background: var(--paper); border: 1px solid var(--line); border-radius: 11px; box-shadow: var(--shadow);
  }
  .consumer-card, .repository-card { padding: 18px; }
  .consumer-card + .consumer-card, .repository-card + .repository-card { margin-top: 12px; }
  .card-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
  .card-heading h3 { margin: 0; font-size: 15px; }
  .route { margin-top: 7px; color: var(--transport); font: 600 13px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; }
  .confidence { color: var(--muted); font-size: 12px; }
  .path { display: grid; gap: 0; margin-top: 16px; }
  .step { position: relative; display: grid; grid-template-columns: 16px minmax(0, 1fr); gap: 11px; padding-bottom: 14px; }
  .step:last-child { padding-bottom: 0; }
  .step:not(:last-child)::after { content: ""; position: absolute; top: 13px; bottom: -2px; left: 5px; width: 2px; background: var(--line); }
  .dot { z-index: 1; width: 12px; height: 12px; margin-top: 4px; border: 3px solid var(--paper); border-radius: 50%; background: var(--muted); box-shadow: 0 0 0 1px currentColor; }
  .step.frontend .dot { color: var(--frontend); background: var(--frontend); }
  .step.transport .dot { color: var(--transport); background: var(--transport); }
  .step.application .dot { color: var(--application); background: var(--application); }
  .step.repository .dot { color: var(--repository); background: var(--repository); }
  .step.database .dot { color: var(--database); background: var(--database); }
  .step-name { font-weight: 650; overflow-wrap: anywhere; }
  .step-kind { margin-left: 7px; color: var(--muted); font-size: 12px; font-weight: 400; }
  .relation { margin-bottom: 2px; color: var(--muted); font-size: 11px; }
  .location { margin-top: 3px; color: #52677a; font: 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }
  .method { margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--line); }
  .method:first-of-type { margin-top: 10px; }
  .method-title { display: flex; gap: 8px; align-items: baseline; font-weight: 650; }
  .resolution { color: var(--muted); font-size: 12px; font-weight: 400; }
  .persistence { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
  .table-chip { padding: 7px 9px; border: 1px solid #e3bdc6; border-radius: 7px; background: #fff3f5; color: #8e2940; }
  .table-chip small { color: #9d6370; }
  .notice { padding: 14px 16px; color: #714c12; background: #fff8e8; border-color: #ead8af; box-shadow: none; }
  .notice + .notice { margin-top: 8px; }
  .muted { color: var(--muted); }
  .canvas-shell { margin-top: 24px; border: 1px solid var(--line); border-radius: 12px; background: #f8fafc; box-shadow: var(--shadow); overflow: hidden; }
  .canvas-toolbar { display: flex; align-items: center; gap: 6px; min-height: 46px; padding: 7px 10px; border-bottom: 1px solid var(--line); background: var(--paper); }
  .canvas-toolbar button { min-width: 34px; padding: 6px 9px; border: 1px solid var(--line); border-radius: 6px; color: var(--ink); background: #f7f9fb; cursor: pointer; }
  .canvas-toolbar button:hover { background: #edf2f6; }
  .canvas-toolbar .canvas-help { margin-left: auto; color: var(--muted); font-size: 12px; }
  .canvas-viewport {
    height: min(72vh, 820px); min-height: 560px; overflow: hidden; cursor: grab; touch-action: none;
    background-color: #fbfcfd;
    background-image: linear-gradient(#e7edf3 1px, transparent 1px), linear-gradient(90deg, #e7edf3 1px, transparent 1px);
    background-size: 28px 28px;
  }
  .canvas-viewport.dragging { cursor: grabbing; }
  .canvas-viewport svg { display: block; width: 100%; height: 100%; user-select: none; }
  .canvas-stage { fill: #788797; font: 600 13px "Avenir Next", Avenir, "Segoe UI", sans-serif; }
  .canvas-edge { fill: none; stroke: #a8b5c3; stroke-width: 1.6; }
  .canvas-edge.conditional { stroke-dasharray: 7 5; }
  .canvas-edge-label { fill: #6d7c8c; font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; paint-order: stroke; stroke: #fbfcfd; stroke-width: 5px; }
  .canvas-node rect { stroke-width: 1.6; }
  .canvas-node .node-title { fill: #172331; font: 650 13px "Avenir Next", Avenir, "Segoe UI", sans-serif; }
  .canvas-node .node-meta { fill: #617083; font: 10px ui-monospace, SFMono-Regular, Menlo, monospace; }
  .canvas-node.frontend rect { fill: #e2f3ff; stroke: var(--frontend); }
  .canvas-node.transport rect { fill: #e0f5f0; stroke: var(--transport); }
  .canvas-node.application rect { fill: #fff0dc; stroke: var(--application); }
  .canvas-node.repository rect { fill: #eee9fa; stroke: var(--repository); }
  .canvas-node.database rect { fill: #fde8ed; stroke: var(--database); }
  .canvas-legend { display: flex; flex-wrap: wrap; gap: 13px; padding: 10px 13px; border-top: 1px solid var(--line); background: var(--paper); color: var(--muted); font-size: 12px; }
  .legend-item { display: inline-flex; align-items: center; gap: 5px; }
  .legend-swatch { width: 10px; height: 10px; border-radius: 3px; background: currentColor; }
  @media (max-width: 1200px) {
    .shell { grid-template-columns: 300px minmax(0, 1fr); }
    .main { padding-inline: 24px; }
    .detail-header { display: block; }
    .header-actions { align-items: flex-start; margin-top: 12px; }
    .canvas-help { display: none; }
  }
  @media (max-width: 820px) {
    .shell { grid-template-columns: 1fr; grid-template-rows: minmax(260px, 42vh) 1fr; }
    .sidebar { border-right: 0; border-bottom: 1px solid #26384b; }
    .brand { padding: 16px; }
    .main { padding: 22px 16px 40px; }
    .detail-header { display: block; }
    .header-actions { align-items: flex-start; margin-top: 12px; }
    .status { display: inline-block; }
    .summary { flex-wrap: wrap; }
    .overview { grid-template-columns: 1fr; }
    .canvas-viewport { min-height: 460px; }
  }
</style>
</head>
<body>
<div class="shell">
  <aside class="sidebar">
    <header class="brand">
      <h1>Parcours</h1>
      <p>Vue → API → BDD</p>
    </header>
    <div class="controls">
      <input id="search" class="search" type="search" placeholder="Composant, use case, route…" autocomplete="off">
      <div class="filters">
        <select id="consumer-filter" aria-label="Type d’entrée"><option value="">Toutes les entrées</option></select>
        <select id="status-filter" aria-label="État de l’analyse">
          <option value="">Tous les états</option><option value="complete">Complet</option><option value="incomplete">Incomplet</option>
        </select>
      </div>
      <div id="result-count" class="result-count"></div>
    </div>
    <nav id="journey-list" class="journey-list" aria-label="Journeys"></nav>
  </aside>
  <main id="main" class="main"></main>
</div>
<script>
const payload = __JOURNEY_DATA__;
const journeys = payload.journeys || [];
const list = document.getElementById('journey-list');
const main = document.getElementById('main');
const search = document.getElementById('search');
const consumerFilter = document.getElementById('consumer-filter');
const statusFilter = document.getElementById('status-filter');
const resultCount = document.getElementById('result-count');
let selectedId = null;
let viewMode = 'essential';

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}
function allPaths(journey, includeIndirect = false) {
  const result = [];
  const consumers = [...(journey.consumers || [])];
  if (includeIndirect) consumers.push(...(journey.indirect?.consumers || []));
  consumers.forEach(consumer => {
    (consumer.frontend_requests || []).forEach(request => (request.paths || []).forEach(path => result.push(path)));
    if (consumer.path) result.push(consumer.path);
  });
  if (includeIndirect) (journey.effects || []).forEach(effect => { if (effect.path) result.push(effect.path); });
  return result;
}
function searchText(journey) {
  const {tests, ambiguities, incomplete_paths, ...searchable} = journey;
  return JSON.stringify(searchable).toLocaleLowerCase();
}
function basename(value) { return String(value || '').split('/').pop(); }
function matchLabel(journey, query) {
  if (!query || journey.name.toLocaleLowerCase().includes(query)) return '';
  const files = []; const values = [];
  function visit(value, key = '') {
    if (Array.isArray(value)) return value.forEach(item => visit(item, key));
    if (value && typeof value === 'object') return Object.entries(value).forEach(([childKey, child]) => visit(child, childKey));
    if (typeof value !== 'string' || !value.toLocaleLowerCase().includes(query)) return;
    const file = value.match(/([^/:]+?\.(?:vue|tsx?|jsx?|py|java|cs|go|rs))(?:::|$)/i);
    if (file) files.push(file[1]); else values.push(key === 'file' ? basename(value) : value);
  }
  visit(journey);
  return files[0] || values[0] || '';
}
function statusLabel(status) { return status === 'complete' ? 'complet' : 'incomplet'; }
const searchIndex = new Map(journeys.map(journey => [journey.id, searchText(journey)]));
const consumerTypes = [...new Set(journeys.flatMap(j => (j.consumers || []).map(c => c.type)))].sort();
consumerTypes.forEach(type => consumerFilter.append(el('option', '', type)));

function classify(step) {
  const text = `${step.kind || ''} ${step.file || ''} ${step.name || ''}`.toLowerCase();
  if (text.includes('frontend/') || /component|view/.test(text)) return 'frontend';
  if (/endpoint|controller|httprequest|route/.test(text)) return 'transport';
  if (/repository|mapper/.test(text)) return 'repository';
  if (/entity|table|persistence/.test(text)) return 'database';
  return 'application';
}
function renderPath(path) {
  const root = el('div', 'path');
  (path || []).forEach(step => {
    const row = el('div', `step ${classify(step)}`);
    row.append(el('span', 'dot'));
    const body = el('div');
    if (step.via) body.append(el('div', 'relation', `${step.via.relation || 'related'}${step.via.reason ? ` · ${step.via.reason}` : ''}`));
    const name = el('div', 'step-name', step.name || step.symbol || 'Unknown step');
    name.append(el('span', 'step-kind', step.kind || ''));
    body.append(name);
    if (step.file) body.append(el('div', 'location', `${step.file}${step.line ? `:${step.line}` : ''}`));
    row.append(body); root.append(row);
  });
  return root;
}
function renderConsumer(consumer) {
  const card = el('article', 'consumer-card');
  const heading = el('div', 'card-heading');
  heading.append(el('h3', '', `${consumer.type} · ${consumer.name}`));
  heading.append(el('span', 'confidence', consumer.confidence)); card.append(heading);
  if (consumer.method) card.append(el('div', 'route', `${consumer.method} ${consumer.route || ''}`));
  const paths = [];
  (consumer.frontend_requests || []).forEach(request => (request.paths || []).forEach(path => paths.push(path)));
  if (consumer.path) paths.push(consumer.path);
  if (!paths.length) card.append(el('p', 'muted', 'No detailed path available.'));
  paths.forEach(path => card.append(renderPath(path)));
  return card;
}
function renderRepository(repository) {
  const card = el('article', 'repository-card');
  const heading = el('div', 'card-heading'); heading.append(el('h3', '', repository.name));
  heading.append(el('span', 'confidence', repository.confidence)); card.append(heading);
  (repository.methods || []).forEach(method => {
    const block = el('div', 'method');
    const title = el('div', 'method-title', method.name);
    title.append(el('span', 'resolution', method.resolution || 'unknown')); block.append(title);
    const paths = method.implementation_paths && method.implementation_paths.length ? method.implementation_paths : (method.path ? [method.path] : []);
    paths.forEach(path => block.append(renderPath(path)));
    if (method.persistence && method.persistence.length) {
      const persistence = el('div', 'persistence');
      method.persistence.forEach(item => {
        const chip = el('div', 'table-chip', item.table);
        chip.append(el('small', '', ` · ${item.entity} · ${item.access}`)); persistence.append(chip);
      });
      block.append(persistence);
    }
    card.append(block);
  });
  return card;
}
function unique(values) { return [...new Set(values.filter(Boolean))]; }
function compactOverview(journey) {
  const paths = allPaths(journey);
  const components = unique(paths.flatMap(path => path.filter(step => String(step.file || '').endsWith('.vue')).map(step => String(step.file).split('/').pop().replace('.vue', ''))));
  const routes = unique((journey.consumers || []).filter(c => c.method).map(c => `${c.method} ${c.route}`));
  const controllers = unique((journey.consumers || []).map(c => c.name));
  const effects = unique((journey.effects || []).map(effect => `${effect.event} → ${effect.name}`));
  const repositories = unique((journey.repositories || []).flatMap(repo => (repo.methods || []).map(method => `${repo.name}.${method.name}`)));
  const tables = unique((journey.repositories || []).flatMap(repo => (repo.methods || []).flatMap(method => (method.persistence || []).map(item => item.table))));
  const columns = [
    ['Entrées', [...components, ...routes], 'frontend'],
    ['Traitement', [...controllers, journey.name, ...effects], 'application'],
    ['Données', [...repositories, ...tables], 'database'],
  ];
  const overview = el('div', 'overview');
  columns.forEach(([title, items, kind]) => {
    const column = el('section', 'overview-column'); column.append(el('h3', '', title)); const list = el('div', 'overview-list');
    unique(items).forEach(item => list.append(el('div', `overview-item ${kind}`, item))); column.append(list); overview.append(column);
  });
  return overview;
}
function graphForJourney(journey) {
  const nodes = new Map(); const edges = new Map();
  function nodeId(step) { return step.symbol || `${step.kind}:${step.name}`; }
  function addNode(step) {
    const id = nodeId(step);
    if (!nodes.has(id)) nodes.set(id, {id, ...step, category: classify(step)});
    return id;
  }
  function addEdge(source, target, relation) {
    if (!source || !target || source === target) return;
    const key = `${source}\u0000${target}`;
    if (!edges.has(key)) edges.set(key, {source, target, relation: relation || ''});
  }
  const useCase = {kind: 'UseCase', name: journey.name, symbol: `usecase:${journey.id}`}; const useCaseId = addNode(useCase);
  (journey.consumers || []).forEach(consumer => {
    const route = consumer.method ? {kind: 'Route', name: `${consumer.method} ${consumer.route}`, symbol: `route:${consumer.method}:${consumer.route}`} : null;
    const controller = {kind: 'Controller', name: consumer.name, symbol: `controller:${consumer.name}`};
    const routeId = route ? addNode(route) : null, controllerId = addNode(controller);
    addEdge(routeId, controllerId); addEdge(controllerId, useCaseId);
    const consumerPaths = [];
    (consumer.frontend_requests || []).forEach(request => (request.paths || []).forEach(path => consumerPaths.push(path)));
    if (consumer.path) consumerPaths.push(consumer.path);
    consumerPaths.forEach(path => {
      const components = unique(path.filter(step => String(step.file || '').endsWith('.vue')).map(step => step.file));
      const service = path.find(step => String(step.file || '').includes('frontend/') && !String(step.file || '').endsWith('.vue') && step.kind === 'Function');
      const serviceId = service ? addNode({...service, kind: 'Frontend service'}) : routeId;
      if (serviceId && routeId) addEdge(serviceId, routeId);
      components.forEach(file => addEdge(addNode({kind: 'Vue component', name: basename(file), symbol: `component:${file}`}), serviceId || routeId || controllerId));
    });
  });
  (journey.repositories || []).forEach(repository => (repository.methods || []).forEach(method => {
    const repositoryNode = {kind: 'Repository', name: `${repository.name}.${method.name}`, symbol: `repository:${repository.id}:${method.name}`};
    const repositoryId = addNode(repositoryNode); addEdge(useCaseId, repositoryId);
    (method.persistence || []).forEach(item => {
      const table = {kind: 'Table', name: item.table, symbol: `table:${item.table}`}; const tableId = addNode(table);
      addEdge(repositoryId, tableId);
    });
  }));
  const raw = {nodes: [...nodes.values()], edges: [...edges.values()]};
  const buckets = [
    ['component', node => node.kind === 'Vue component', 'Vue'],
    ['route', node => node.kind === 'Route' || node.kind === 'Frontend service', 'HTTP'],
    ['controller', node => node.kind === 'Controller', 'Controllers'],
    ['effect', node => node.kind === 'Domain event' || node.kind === 'Event handler', 'Effets'],
    ['repository', node => node.kind === 'Repository', 'Repositories'],
    ['table', node => node.kind === 'Table', 'Tables'],
  ];
  const replacements = new Map(); const compactNodes = new Map(raw.nodes.map(node => [node.id, node]));
  buckets.forEach(([key, match, label]) => {
    const matches = raw.nodes.filter(match);
    if (matches.length <= 2) return;
    matches.forEach(node => compactNodes.delete(node.id));
    const id = `group:${key}`;
    const sample = matches.slice(0, 2).map(node => node.name).join(' · ');
    compactNodes.set(id, {id, kind: label, name: `${label} · ${matches.length}`, detail: sample, category: matches[0].category});
    matches.forEach(node => replacements.set(node.id, id));
  });
  const compactEdges = new Map();
  raw.edges.forEach(edge => {
    const source = replacements.get(edge.source) || edge.source, target = replacements.get(edge.target) || edge.target;
    if (source !== target) compactEdges.set(`${source}\u0000${target}`, {...edge, source, target});
  });
  return {nodes: [...compactNodes.values()], edges: [...compactEdges.values()]};
}
function fullGraphForJourney(journey) {
  const nodes = new Map(); const edges = new Map();
  function add(step) {
    const id = step.symbol || `${step.kind}:${step.file || ''}:${step.line || ''}:${step.name}`;
    if (!nodes.has(id)) nodes.set(id, {id, ...step, category: classify(step)});
    return id;
  }
  function path(steps) {
    let previous = null;
    (steps || []).forEach(step => { const current = add(step); if (previous && previous !== current) edges.set(`${previous}\u0000${current}`, {source: previous, target: current, relation: step.via?.relation}); previous = current; });
  }
  const useCaseId = add({kind: 'UseCase', name: journey.name, symbol: journey.id});
  allPaths(journey, true).forEach(path);
  const repositories = [...(journey.repositories || []), ...(journey.indirect?.repositories || [])];
  repositories.forEach(repository => (repository.methods || []).forEach(method => {
    (method.implementation_paths || (method.path ? [method.path] : [])).forEach(path);
    const repositoryId = add({kind: 'Repository', name: `${repository.name}.${method.name}`, symbol: `repository:${repository.id}:${method.name}`});
    edges.set(`${useCaseId}\u0000${repositoryId}`, {source: useCaseId, target: repositoryId});
    (method.persistence || []).forEach(item => {
      const tableId = add({kind: 'Table', name: item.table, symbol: `table:${item.table}`});
      edges.set(`${repositoryId}\u0000${tableId}`, {source: repositoryId, target: tableId});
    });
  }));
  return {nodes: [...nodes.values()], edges: [...edges.values()]};
}
function canvasStage(node) {
  const text = `${node.kind || ''} ${node.name || ''} ${node.file || ''}`.toLowerCase();
  if (node.category === 'database') return 6;
  if (text.includes('mapper')) return 5;
  if (node.category === 'repository') return 4;
  if (text.includes('usecase')) return 3;
  if (text.includes('controller')) return 2;
  if (text.includes('route')) return 1;
  if (text.includes('.vue')) return 0;
  return 1;
}
function svgEl(tag, attrs = {}) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value)); return node;
}
function truncate(value, max) { value = String(value || ''); return value.length > max ? `${value.slice(0, max - 1)}…` : value; }
function nodeMeta(node) {
  if (node.detail) return node.detail;
  if (node.file) return `${basename(node.file)}${node.line ? `:${node.line}` : ''}`;
  return node.kind || node.category;
}
function renderCanvas(journey, detailed = false) {
  const graph = detailed ? fullGraphForJourney(journey) : graphForJourney(journey); const columns = Array.from({length: 7}, () => []);
  graph.nodes.forEach(node => { node.stage = canvasStage(node); columns[node.stage].push(node); });
  columns.forEach(column => column.sort((a, b) => String(a.name).localeCompare(String(b.name))));
  const nodeW = 238, nodeH = 72, xGap = 76, yGap = 40, marginX = 70, marginY = 84;
  const maxRows = Math.max(1, ...columns.map(column => column.length));
  const width = marginX * 2 + 7 * nodeW + 6 * xGap;
  const height = Math.max(650, marginY * 2 + maxRows * nodeH + (maxRows - 1) * yGap);
  const positions = new Map();
  columns.forEach((column, stage) => {
    const used = column.length * nodeH + Math.max(0, column.length - 1) * yGap;
    const startY = marginY + Math.max(0, (height - marginY * 2 - used) / 2);
    column.forEach((node, row) => positions.set(node.id, {x: marginX + stage * (nodeW + xGap), y: startY + row * (nodeH + yGap)}));
  });
  const shell = el('div', 'canvas-shell'); const toolbar = el('div', 'canvas-toolbar');
  const zoomOut = el('button', '', '−'); zoomOut.type = 'button'; zoomOut.title = 'Zoom out';
  const zoomIn = el('button', '', '+'); zoomIn.type = 'button'; zoomIn.title = 'Zoom in';
  const fit = el('button', '', 'Cadrer'); fit.type = 'button';
  toolbar.append(zoomOut, zoomIn, fit, el('span', 'canvas-help', 'Glisser · molette')); shell.append(toolbar);
  const viewport = el('div', 'canvas-viewport'); const svg = svgEl('svg', {role: 'img', 'aria-label': `Architecture tree for ${journey.name}`});
  const world = svgEl('g'); svg.append(world); viewport.append(svg); shell.append(viewport);
  const labels = ['Vue / UI', 'Client API / HTTP', 'Controllers', 'Use case', 'Repositories', 'Mappers', 'BDD'];
  labels.forEach((label, stage) => {
    const text = svgEl('text', {x: marginX + stage * (nodeW + xGap), y: 38, class: 'canvas-stage'}); text.textContent = label; world.append(text);
  });
  graph.edges.forEach(edge => {
    const a = positions.get(edge.source), b = positions.get(edge.target); if (!a || !b) return;
    const x1 = a.x + nodeW, y1 = a.y + nodeH / 2, x2 = b.x, y2 = b.y + nodeH / 2, bend = Math.max(34, (x2 - x1) / 2);
    const conditional = ['publishes', 'handled_by'].includes(String(edge.relation || '').toLowerCase());
    world.append(svgEl('path', {d: `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`, class: `canvas-edge${conditional ? ' conditional' : ''}`, 'marker-end': 'url(#arrow)'}));
  });
  const defs = svgEl('defs'); const marker = svgEl('marker', {id: 'arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse'});
  marker.append(svgEl('path', {d: 'M 0 0 L 10 5 L 0 10 z', fill: '#8fa0b1'})); defs.append(marker); svg.prepend(defs);
  graph.nodes.forEach(node => {
    const pos = positions.get(node.id); const group = svgEl('g', {class: `canvas-node ${node.category}`, transform: `translate(${pos.x} ${pos.y})`});
    const title = svgEl('title'); title.textContent = `${node.name}\n${node.file || ''}${node.line ? `:${node.line}` : ''}`; group.append(title);
    group.append(svgEl('rect', {width: nodeW, height: nodeH, rx: 9}));
    const name = svgEl('text', {x: 14, y: 29, class: 'node-title'}); name.textContent = truncate(node.name, 31); group.append(name);
    const meta = svgEl('text', {x: 14, y: 51, class: 'node-meta'}); meta.textContent = truncate(nodeMeta(node), 37); group.append(meta); world.append(group);
  });
  let view = {x: 0, y: 0, w: width, h: height};
  function applyView() { svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`); }
  function zoom(factor, cx = view.x + view.w / 2, cy = view.y + view.h / 2) {
    const nextW = Math.max(520, Math.min(width * 2, view.w * factor)); const nextH = nextW * viewport.clientHeight / Math.max(viewport.clientWidth, 1);
    const rx = (cx - view.x) / view.w, ry = (cy - view.y) / view.h;
    view = {x: cx - rx * nextW, y: cy - ry * nextH, w: nextW, h: nextH}; applyView();
  }
  function reset() { view = {x: 0, y: 0, w: width, h: height}; applyView(); }
  zoomIn.addEventListener('click', () => zoom(.78)); zoomOut.addEventListener('click', () => zoom(1.28)); fit.addEventListener('click', reset);
  viewport.addEventListener('wheel', event => { event.preventDefault(); const rect = svg.getBoundingClientRect(); const cx = view.x + (event.clientX - rect.left) / rect.width * view.w; const cy = view.y + (event.clientY - rect.top) / rect.height * view.h; zoom(event.deltaY < 0 ? .86 : 1.16, cx, cy); }, {passive: false});
  let drag = null;
  viewport.addEventListener('pointerdown', event => { drag = {x: event.clientX, y: event.clientY, vx: view.x, vy: view.y}; viewport.setPointerCapture(event.pointerId); viewport.classList.add('dragging'); });
  viewport.addEventListener('pointermove', event => { if (!drag) return; const rect = viewport.getBoundingClientRect(); view.x = drag.vx - (event.clientX - drag.x) / rect.width * view.w; view.y = drag.vy - (event.clientY - drag.y) / rect.height * view.h; applyView(); });
  viewport.addEventListener('pointerup', () => { drag = null; viewport.classList.remove('dragging'); });
  const legend = el('div', 'canvas-legend'); [['frontend','Vue / frontend'],['transport','HTTP / controller'],['application','Application'],['repository','Repository / mapper'],['database','Database']].forEach(([kind,label]) => { const item = el('span', `legend-item ${kind}`); item.append(el('span', 'legend-swatch'), el('span', '', label)); item.style.color = `var(--${kind})`; legend.append(item); });
  shell.append(legend); reset(); return shell;
}
function section(title, items) {
  const root = el('section', 'section'); root.append(el('h3', 'section-title', title));
  items.forEach(item => root.append(item)); return root;
}
function renderDetail(journey) {
  main.replaceChildren();
  main.scrollTop = 0; main.scrollLeft = 0;
  if (!journey) {
    const empty = el('div', 'empty'); empty.append(el('h2', '', 'Choisis un parcours'));
    empty.append(el('p', '', 'Recherche un composant, un use case ou une route.'));
    main.append(empty); return;
  }
  const detail = el('div', 'detail');
  const header = el('header', 'detail-header'); const copy = el('div');
  copy.append(el('h2', '', journey.name)); copy.append(el('p', '', journey.domain)); header.append(copy);
  const actions = el('div', 'header-actions');
  actions.append(el('span', `status ${journey.analysis_status === 'incomplete' ? 'incomplete' : ''}`, statusLabel(journey.analysis_status)));
  const switcher = el('div', 'view-switch');
  [['essential','Essentiel'],['complete','Complet']].forEach(([mode,label]) => { const button = el('button', `view-button ${viewMode === mode ? 'active' : ''}`, label); button.type = 'button'; button.addEventListener('click', () => { viewMode = mode; renderDetail(journey); }); switcher.append(button); });
  actions.append(switcher); header.append(actions);
  detail.append(header);
  const summary = el('div', 'summary');
  summary.append(el('span', '', `${journey.consumers.length} entrées`));
  summary.append(el('span', '', `${(journey.effects || []).length} effets`));
  summary.append(el('span', '', `${journey.repositories.length} repositories`));
  summary.append(el('span', '', `${journey.tests.length} tests`)); detail.append(summary);
  const hidden = Object.values(journey.hidden || {}).reduce((sum, value) => sum + Number(value || 0), 0);
  if (hidden) summary.append(el('span', '', `+${hidden} masqués`));
  detail.append(renderCanvas(journey, viewMode === 'complete'));
  main.append(detail);
}
function filteredJourneys() {
  const query = search.value.trim().toLocaleLowerCase();
  return journeys.filter(journey => {
    if (query && !searchIndex.get(journey.id).includes(query)) return false;
    if (consumerFilter.value && !(journey.consumers || []).some(c => c.type === consumerFilter.value)) return false;
    return !statusFilter.value || journey.analysis_status === statusFilter.value;
  });
}
function renderList() {
  const filtered = filteredJourneys(); const query = search.value.trim().toLocaleLowerCase(); list.replaceChildren();
  resultCount.textContent = `${filtered.length} parcours sur ${journeys.length}`;
  if (query && filtered.length && !filtered.some(journey => journey.id === selectedId)) {
    selectedId = filtered[0].id; viewMode = 'essential'; renderDetail(filtered[0]);
  }
  filtered.forEach(journey => {
    const button = el('button', `journey-item ${journey.id === selectedId ? 'active' : ''}`);
    button.type = 'button'; button.append(el('span', 'journey-name', journey.name));
    button.append(el('span', 'journey-domain', journey.domain));
    const matched = matchLabel(journey, query); if (matched) button.append(el('span', 'journey-match', `↳ ${matched}`));
    const badges = el('span', 'badges');
    if ((journey.consumers || []).some(c => c.type === 'frontend')) badges.append(el('span', 'badge frontend', 'frontend'));
    badges.append(el('span', `badge ${journey.analysis_status === 'incomplete' ? 'incomplete' : ''}`, statusLabel(journey.analysis_status)));
    button.append(badges); button.addEventListener('click', () => { selectedId = journey.id; viewMode = 'essential'; renderList(); renderDetail(journey); });
    list.append(button);
  });
  if (!filtered.length) list.append(el('p', 'result-count', 'Aucun parcours.'));
  if (selectedId && !filtered.some(j => j.id === selectedId)) { selectedId = null; renderDetail(null); }
}
[search, consumerFilter, statusFilter].forEach(control => control.addEventListener('input', renderList));
renderList(); renderDetail(null); search.focus();
</script>
</body>
</html>
"""
