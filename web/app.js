import * as THREE from 'three';
import { OrbitControls } from './vendor/three/OrbitControls.js';
import * as pdfjsLib from './vendor/pdfjs/pdf.min.mjs';
import { COLLECTIONS, isOriginal, casePath, baseMesh, operationMesh, inputRelation, historicalResult, failedResult, originalMethod, originalResultLabel, originalDisplay, smlibResult, smlibResultLabel, smlibPairingLabel } from './original.js';

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL('./vendor/pdfjs/pdf.worker.min.mjs', import.meta.url).href;
const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
const state = { series: 'original', collections: new Map(), collectionToken: 0, routeToken: 0, inputStage: 'base', catalog: null, cases: new Map(), currentCase: null, variant: null, filter: 'all', query: '', token: 0, selectionToken: 0, viewers: {}, syncing: false, pdf: null, pdfMeta: null, imageUrl: null, mapping: readStorage('filletbench-reference-maps', {}), previewPage: 1, previewCrop: null, previewToken: 0, detailTab: 'evidence', detailEngine: null, expanded: null, refView: { scale: 1, x: 0, y: 0 } };
const meshCache = new Map();
// Stable DOM slots: input, OCC output, SMLib output. Data uses the actual engine names.
const modelSlots = ['occt', 'smlib', 'smlibFourth'];
const resultSlots = { occt: 'smlib', smlib: 'smlibFourth' };
const statusNames = { pass: ['通过', 'passed'], passed: ['通过', 'passed'], accepted: ['通过', 'passed'], fail: ['未通过', 'failed'], failed: ['未通过', 'failed'], invalid: ['几何无效', 'failed'], error: ['构建失败', 'failed'], self_intersect: ['存在自交', 'failed'], self_intersection: ['存在自交', 'failed'], pending: ['待验证', 'pending'], not_run: ['未运行', 'pending'], unavailable: ['未提供', 'pending'], unsupported: ['暂不支持', 'pending'], missing: ['缺少结果', 'pending'], blocked: ['受阻', 'pending'], generated: ['已生成', 'neutral'], valid: ['已生成', 'neutral'], ok: ['已生成', 'neutral'], partial: ['部分完成', 'pending'], candidate_unverified: ['候选未验证', 'neutral'], api_failed: ['调用失败', 'failed'], geometry_failed: ['几何失败', 'failed'], crash: ['异常退出', 'failed'], native_api_failed_with_candidate: ['调用失败 · 有候选', 'failed'], controlled_subchecks: ['子判据通过', 'neutral'] };

function readStorage(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } }
function saveMappings() { try { localStorage.setItem('filletbench-reference-maps', JSON.stringify(state.mapping)); } catch { toast('浏览器无法保存参考映射；当前会话仍可使用。'); } }
function toast(message) { const node = $('#toast'); node.textContent = message; node.hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => { node.hidden = true; }, 4000); }
function text(value, fallback = '未记录') { if (value === undefined || value === null || value === '') return fallback; return typeof value === 'object' ? JSON.stringify(value) : String(value); }
function statusInfo(result) { const status = String(result?.status ?? 'pending').toLowerCase(); const failure = /fail|invalid|error|crash|reject|self_intersect/.test(status) || result?.api_success === false; const [label, tone] = statusNames[status] ?? (failure ? ['未通过', 'failed'] : ['待验证', 'pending']); return { label: statusNames[status] ? label : (result?.label || label), fullLabel: result?.label || label, tone: failure ? 'failed' : tone, raw: status }; }
function getCaseNumber(item) { return String(item?.number ?? item?.id?.match(/\d+/)?.[0] ?? '').padStart(2, '0'); }
function variantLabel(variant) { return variant.label || (variant.radius_mm !== undefined ? `R ${variant.radius_mm} mm` : variant.id); }
function brief(value, max = 170) { const string = text(value, ''); return string.length > max ? string.slice(0, max) + '…' : string; }
function originalParameterText(variant) {
  const parameters = variant.parameters;
  if (!parameters || typeof parameters !== 'object') return text(parameters, '原版参数详见记录。');
  const parts = [parameters.summary, parameters.radius_text || (parameters.radius_mm !== undefined ? `R ${parameters.radius_mm} mm` : null), parameters.part_number ? `原部件 ${parameters.part_number}` : null, parameters.plan?.selection_note || parameters.preprocess?.description, parameters.construction].filter((value) => value !== undefined && value !== null && value !== '');
  return parts.length ? parts.map((value) => text(value)).join(' · ') : brief(parameters, 280);
}
function newNode(tag, className, content) { const node = document.createElement(tag); if (className) node.className = className; if (content !== undefined) node.textContent = content; return node; }
function getHash() { return new URLSearchParams(location.hash.replace(/^#/, '')); }
function setHash(caseData, variant) { const hash = new URLSearchParams({ series: state.series, case: getCaseNumber(caseData) }); if (variant) hash.set('variant', variant.id); if (location.hash.slice(1) !== hash.toString()) history.replaceState(null, '', '#' + hash); }
async function fetchJSON(path) { const response = await fetch(path, { cache: 'no-cache' }); if (!response.ok) throw new Error(`${response.status} · ${path}`); return response.json(); }
function safePath(path) { if (typeof path !== 'string') return null; const url = new URL(path, location.href); return url.origin === location.origin ? url.href : null; }
function addDetailLink(parent, label, path) { const url = safePath(path); if (!url) return; const link = newNode('a', 'detail-link', label); link.href = url; link.target = '_blank'; link.rel = 'noopener'; parent.append(link); }
function addModelDownloads(parent, engine = 'occt') {
  const variant = state.variant, result = engine === 'input' ? {} : variant[engine] || {};
  const files = [...(Array.isArray(result.files) ? result.files : [])];
  if (engine === 'input' && variant.base_brep_url && !files.some((file) => file.path === variant.base_brep_url || (file.sha256 === variant.base_sha256 && /基础/.test(file.label || '')))) files.unshift({ label: '原版基础 BREP', path: variant.base_brep_url, sha256: variant.base_sha256, status: '原基础输入' });
  const list = newNode('ul', 'model-download-list');
  for (const file of files) {
    if (typeof file.path !== 'string') continue;
    let url;
    try { url = new URL(file.path, location.href); } catch { continue; }
    const local = url.origin === location.origin;
    if (!local && !(url.protocol === 'https:' && url.hostname === 'raw.githubusercontent.com')) continue;
    const row = newNode('li', 'model-download');
    const link = newNode('a', 'detail-link', `${text(file.label, '模型文件')} ↓`); link.href = url.href; link.target = '_blank'; link.rel = 'noopener';
    if (local) link.download = url.pathname.split('/').pop();
    row.append(link);
    if (file.status) {
      const status = text(file.status), failed = /fail|invalid|error|crash|reject|未通过|无效|失败/i.test(status);
      const statusLabel = { export_failed: 'STEP 回读未通过', geometry_failed: '无效候选 · 几何检查未通过', api_failed: 'API 失败候选', candidate_unverified: '候选 · 未完成验收', input_only: '仅输入' }[status] || status;
      const badge = newNode('span', `model-file-status${failed ? ' failed' : ''}`, statusLabel); badge.title = status; row.append(badge);
    }
    if (file.sha256) { const hash = newNode('code', 'model-file-hash', `SHA-256 ${String(file.sha256).slice(0, 12)}…`); hash.title = String(file.sha256); row.append(hash); }
    list.append(row);
  }
  if (!list.children.length) return;
  const section = newNode('section', 'model-downloads'); section.append(newNode('h3', '', '下载模型'), list); parent.append(section);
}

async function boot() {
  wireUI();
  await routeHash();
  restorePDF();
}
async function loadCollection(series) {
  if (!state.collections.has(series)) state.collections.set(series, fetchJSON(COLLECTIONS[series].path).then((catalog) => {
    if (!Array.isArray(catalog.cases) || !catalog.cases.length) throw new Error('目录中没有案例。');
    return { catalog, cases: new Map() };
  }).catch((error) => { state.collections.delete(series); throw error; }));
  return state.collections.get(series);
}
async function readCase(item, collection, series) {
  if (!collection.cases.has(item.id)) collection.cases.set(item.id, await fetchJSON(casePath(item, series)));
  return collection.cases.get(item.id);
}
async function routeHash() {
  const token = ++state.routeToken;
  const hash = getHash();
  let series = COLLECTIONS[hash.get('series')] ? hash.get('series') : 'original';
  const number = hash.get('case'), requested = hash.get('variant');
  if (!hash.has('series') && requested) {
    const matches = await Promise.allSettled(['original', 'comparison'].map(async (candidate) => {
      const collection = await loadCollection(candidate);
      const item = collection.catalog.cases.find((entry) => getCaseNumber(entry) === String(number).padStart(2, '0'));
      return item && (await readCase(item, collection, candidate)).variants?.some((variant) => variant.id === requested) ? candidate : null;
    }));
    if (token !== state.routeToken) return;
    const match = matches.find((entry) => entry.status === 'fulfilled' && entry.value)?.value;
    if (match) { series = match; if (match === 'comparison') toast('此旧链接属于 OCC–SMLib 对照实验，已保留原变体。'); }
    else toast('旧链接中的变体未找到，将明确显示原版默认参数。');
  }
  await selectCollection(series, number, requested);
}
async function selectCollection(series, number = getCaseNumber(state.currentCase), requestedVariant = null) {
  ++state.routeToken;
  const token = ++state.collectionToken;
  ++state.selectionToken; ++state.token;
  if ($('#detailDialog').open) $('#detailDialog').close();
  state.series = series; state.inputStage = 'base';
  state.catalog = null; state.currentCase = null; state.variant = null; state.cases = new Map();
  $('#caseCount').textContent = '—'; $('#caseKicker').textContent = 'CASE —';
  $('#caseTitle').textContent = COLLECTIONS[series].label;
  $('#caseQuestion').textContent = '正在读取本集合的原始参数与实际处理记录…';
  $('#variantSelect').replaceChildren(); $('#variantMeta').hidden = true; $('#familyTag').hidden = true;
  $('#pipelineBadges').replaceChildren(); $('#findings').replaceChildren(); $('#representationNotice').hidden = true;
  $('#caseList').replaceChildren(newNode('p', 'list-message', '正在读取案例…'));
  $('#previousCase').disabled = true; $('#nextCase').disabled = true;
  for (const engine of modelSlots) {
    state.viewers[engine]?.clear(); const stage = $(`#${engine}Stage`);
    $('.stage-empty', stage).hidden = false; $('h3', $('.stage-empty', stage)).textContent = '等待本集合数据'; $('p', $('.stage-empty', stage)).textContent = '保留案例、参数与实际产物的对应关系。';
    $('.model-view-label', stage).hidden = true; $('.model-hint', stage).hidden = true; $('.stage-busy', stage).hidden = true;
    $(`#${engine}Status`).textContent = '待载入'; $(`#${engine}Status`).className = 'status-badge neutral'; $(`#${engine}Caption`).textContent = '读取记录中';
  }
  ++referenceRenderToken; $('#referenceImageWrap').hidden = true; $('#referenceEmpty').hidden = false; $('#referenceBadge').hidden = true; $('#referenceZoomControls').hidden = true;
  $('#referenceCaption').textContent = '原始图像不包含在公开仓库中'; $('#changeReference').hidden = true;
  renderCollectionUI();
  $('#bootError').hidden = true;
  try {
    const collection = await loadCollection(series);
    if (token !== state.collectionToken) return;
    state.catalog = collection.catalog; state.cases = collection.cases;
    const explanationCount = isOriginal(state) ? state.catalog.cases.filter((item) => item.has_model === false || getCaseNumber(item) === '32').length : 0;
    $('#caseCount').textContent = explanationCount ? `${state.catalog.cases.length - explanationCount} + ${explanationCount} 说明` : state.catalog.cases.length;
    renderList();
    const first = state.catalog.cases.find((item) => getCaseNumber(item) === String(number).padStart(2, '0')) || state.catalog.cases[0];
    await selectCase(first, requestedVariant);
    const results = await Promise.allSettled(collection.catalog.cases.map((item) => readCase(item, collection, series)));
    if (results.some((result) => result.status === 'rejected')) console.warn(`${series}: some case definitions could not be loaded.`);
    if (token === state.collectionToken) renderList();
  } catch (error) {
    if (token !== state.collectionToken) return;
    state.catalog = null; state.currentCase = null; state.variant = null;
    $('#bootError').hidden = false;
    $('#bootError').textContent = `${COLLECTIONS[series].label}的数据尚未就绪：${error.message}。可选择另一个集合；不会用其他输入或实验替换本系列。`;
    $('#caseList').replaceChildren(newNode('p', 'list-message', '本集合暂无可读取的案例数据'));
    Object.values(state.viewers).forEach((viewer) => viewer.clear());
  }
}
function renderCollectionUI() {
  const original = isOriginal(state);
  document.body.dataset.series = state.series;
  $$('.collection-tabs button').forEach((button) => { const active = button.dataset.series === state.series; button.classList.toggle('active', active); button.setAttribute('aria-pressed', active); });
  $('#collectionContext').textContent = original ? '原版 OCC 系列' : 'OCCT × SMLib';
  $('#collectionDescription').textContent = original ? '34 组原始编号 · 原版参数 / 基础输入 · 缝合、裁剪、延伸后的操作输入单列。32 为说明项。' : '独立的 OCC–SMLib 补充对照实验。各实验输入、参数与原版系列分别记录。';
  $('#variantControlLabel').textContent = original ? '原版参数' : '测试参数';
  $('#beforeControl').hidden = original; $('#beforeDivider').hidden = original;
  $('#originalPipeline').hidden = !original;
  $('#occtHeading').textContent = '基础模型与选边';
  $('#smlibHeading').textContent = '实际 OCC 结果';
  $('#smlibFourthHeading').textContent = '实际 SMLib 结果';
  $('#referenceHeading').textContent = original ? 'PDF 原图' : '原始参考';
  $('.comparison-grid').setAttribute('aria-label', 'PDF 原图、基础模型与选边、OCC 和 SMLib 实际结果横向四栏对照');
  $('#referenceEmpty p').textContent = '载入你拥有的 PDF 或图片\n并排核对基础模型、OCC 与 SMLib 实际产物';
  $('#validationFootnote').textContent = original ? '历史记录未复跑；几何、特殊语义和参考外观分别验收。' : '“已生成”仅代表有输出；几何、特殊语义和参考外观需分别验收。';
}
function caseTone(item) {
  const data = state.cases.get(item.id);
  if (!data) return '';
  const statuses = (data.variants || []).flatMap((variant) => (isOriginal(state) ? ['occt'] : ['occt', 'smlib']).map((key) => statusInfo(variant[key])));
  if (statuses.some((status) => status.tone === 'failed')) return 'failed';
  if (statuses.some((status) => status.tone === 'passed')) return 'passed';
  return 'pending';
}
function renderList() {
  if (!state.catalog) return;
  const container = $('#caseList');
  const items = state.catalog.cases.filter((item) => {
    const haystack = `${getCaseNumber(item)} ${item.id} ${item.title} ${item.question} ${item.family}`.toLowerCase();
    if (state.query && (/^\d{1,2}$/.test(state.query) ? getCaseNumber(item) !== state.query.padStart(2, '0') : !haystack.includes(state.query.toLowerCase()))) return false;
    const data = state.cases.get(item.id);
    if (state.filter === 'mesh') return data?.variants?.some((variant) => (isOriginal(state) ? ['occt'] : ['occt', 'smlib']).some((key) => Boolean(variant[key]?.mesh)));
    if (state.filter === 'attention') return !data || data.variants?.some((variant) => (isOriginal(state) ? ['occt'] : ['occt', 'smlib']).some((key) => statusInfo(variant[key]).tone !== 'passed'));
    return true;
  });
  container.replaceChildren();
  for (const item of items) {
    const button = newNode('button', 'case-link' + (state.currentCase?.id === item.id ? ' active' : ''));
    button.dataset.case = item.id;
    button.setAttribute('aria-current', state.currentCase?.id === item.id ? 'page' : 'false');
    button.append(newNode('span', 'case-number', getCaseNumber(item)));
    const content = newNode('span', 'case-link-content');
    const explanation = item.has_model === false || getCaseNumber(item) === '32';
    content.append(newNode('span', 'case-link-title', item.title || `案例 ${getCaseNumber(item)}`), newNode('span', 'case-link-subtitle', explanation ? '说明项 · 无独立模型' : `${item.variant_count || '—'} 组参数 · 系列 ${(item.family || '—').toUpperCase()}`));
    button.append(content, newNode('span', 'case-list-dot ' + caseTone(item)));
    button.addEventListener('click', () => selectCase(item));
    container.append(button);
  }
  if (!items.length) container.append(newNode('p', 'list-message', '没有匹配的案例'));
}
async function selectCase(item, requestedVariant) {
  ++state.routeToken;
  const selectionToken = ++state.selectionToken;
  try {
    const data = state.cases.get(item.id) || await fetchJSON(casePath(item, state.series));
    if (selectionToken !== state.selectionToken) return;
    state.cases.set(item.id, data);
    state.currentCase = { ...item, ...data };
    const variants = data.variants || [];
    const chosen = variants.find((variant) => variant.id === requestedVariant) || variants.find((variant) => variant.id === data.default_variant) || variants[0];
    if (requestedVariant && !variants.some((variant) => variant.id === requestedVariant)) toast(`变体 ${requestedVariant} 不属于本集合；已显示本案例明确指定的默认参数。`);
    $('#caseKicker').textContent = `CASE ${getCaseNumber(data)}`;
    $('#caseTitle').textContent = data.title || item.title;
    $('#caseQuestion').textContent = data.question || item.question || '对照输入与实际内核输出，检查目标圆角能否可靠构建。';
    $('#familyTag').textContent = (data.family || item.family) ? `系列 ${(data.family || item.family).toUpperCase()}` : '';
    $('#familyTag').hidden = !$('#familyTag').textContent;
    document.title = `${getCaseNumber(data)} ${data.title || item.title} · FilletBench`;
    $('#variantSelect').replaceChildren();
    $('#variantSelect').disabled = !variants.length;
    $('#openDetails').disabled = !variants.length;
    $$('.inspect-button').forEach((button) => { button.disabled = !variants.length; });
    $$('.input-stage-switch button').forEach((button) => { button.disabled = !variants.length; });
    const groups = new Map();
    const multiPart = new Set(variants.map((variant) => variant.id.match(/part(\d+)/)?.[1]).filter(Boolean)).size > 1;
    for (const variant of variants) {
      const groupName = isOriginal(state) ? '原版参数 / 基础输入' : variant.role === 'ordinary_challenge' ? '普通边圆角 · 挑战参数' : variant.role === 'ordinary_control' ? '普通边圆角 · 控制参数' : '补充证据 · 独立特殊协议';
      if (!groups.has(groupName)) { const group = newNode('optgroup'); group.label = groupName; groups.set(groupName, group); $('#variantSelect').append(group); }
      const option = newNode('option'); option.value = variant.id;
      const part = multiPart ? `部件 ${Number(variant.id.match(/part(\d+)/)?.[1] || 1)} · ` : '';
      option.textContent = isOriginal(state) ? variantLabel(variant) : variant.role?.startsWith('ordinary_') ? `${part}${variant.role === 'ordinary_control' ? '控制' : '挑战'} · ${variant.radius_label || `R${variant.radius_mm} mm`}` : (variant.label || variant.id).replace('先导原生重建 · ', '补充 · ');
      option.title = variantLabel(variant); groups.get(groupName).append(option);
    }
    $('#beforeToggle').checked = false;
    state.inputStage = 'base';
    window.scrollTo(0, 0);
    $$('.input-stage-switch button').forEach((button) => { const active = button.dataset.inputStage === 'base'; button.classList.toggle('active', active); button.setAttribute('aria-pressed', active); });
    renderList();
    $('#caseList .active')?.scrollIntoView({ block: 'nearest' });
    const index = state.catalog.cases.findIndex((entry) => entry.id === item.id);
    $('#previousCase').disabled = index === 0;
    $('#nextCase').disabled = index === state.catalog.cases.length - 1;
    $('.sidebar').classList.remove('is-open');
    if (chosen) await selectVariant(chosen); else {
      state.variant = null; ++state.token; setHash(state.currentCase);
      $('#variantMeta').hidden = true; $('#representationNotice').hidden = true; $('#pipelineBadges').replaceChildren();
      const explanation = data.has_model === false || getCaseNumber(data) === '32';
      $('#findings').replaceChildren(newNode('p', 'list-message', explanation ? text(data.note || data.question, '本项仅为原文说明，不建立独立模型或执行圆角任务。') : '该案例尚无测试变体；不会显示其他案例的结果。'));
      for (const engine of modelSlots) {
        state.viewers[engine]?.clear(); const stage = $(`#${engine}Stage`), empty = $('.stage-empty', stage);
        empty.hidden = false; $('h3', empty).textContent = explanation ? '说明项 · 无独立模型' : '没有测试变体'; $('p', empty).textContent = explanation ? '保留原编号与原文说明。' : '不会借用其他参数的结果。';
        $('.model-view-label', stage).hidden = true; $('.model-hint', stage).hidden = true; $('.stage-busy', stage).hidden = true;
        $(`#${engine}Status`).textContent = explanation ? '说明项' : '未提供'; $(`#${engine}Status`).className = 'status-badge neutral'; $(`#${engine}Caption`).textContent = explanation ? '原文说明 · 不计入 34 组模型' : '尚无记录';
      }
      renderReference();
    }
  } catch (error) { toast(`无法读取案例：${error.message}`); }
}
async function selectVariant(variant) {
  if ($('#detailDialog').open) $('#detailDialog').close();
  state.variant = variant;
  const token = ++state.token;
  $('#variantSelect').value = variant.id;
  $('#variantMeta').hidden = variant.role?.startsWith('ordinary_') || variant.radius_mm === undefined || variant.radius_mm === null;
  $('#variantMeta').textContent = `R ${text(variant.radius_mm, '—')} mm`;
  setHash(state.currentCase, variant);
  renderNotice();
  renderFindings();
  renderReference();
  if (isOriginal(state)) renderOriginalMetadata(); else { renderComparisonInputMetadata(); for (const engine of ['occt', 'smlib']) renderEngineMetadata(engine); }
  await renderModels(token);
}
function renderNotice() {
  const variant = state.variant;
  const notice = $('#representationNotice');
  const parts = [];
  if (isOriginal(state)) {
    const relation = inputRelation(variant);
    parts.push(variant.operation_relation_note || (relation === 'derived' ? '原基础与实际操作输入不同：中栏默认保留原基础，可单独查看缝合 / 裁剪 / 延伸后的输入。' : relation === 'part_selection' ? '中栏默认保留原基础总模型，实际操作输入单独显示本次选取的部件。' : relation === 'same_as_base' ? '本次直接使用原版基础几何；着色与网格记录可不同。' : relation === 'recorded_combination_input' ? '操作输入为组合流程入口；内部分割与 Boolean 步骤另见处理记录。' : '原基础与实际操作输入单列保留；具体部件与预处理步骤以操作记录为准。'));
    const scope = variant.scope_note || variant.input_construction_note || variant.input_note || state.currentCase.scope_note;
    if (scope) parts.push(text(scope));
    parts.push(historicalResult(variant) ? '历史处理记录 · 本次未复跑。' : '已记录本次复跑证据。');
    notice.textContent = 'ⓘ  ' + parts.join('  '); notice.hidden = false; return;
  }
  if (variant.pairing === 'same_source_geometry_and_request_different_representations') {
    parts.push('同源几何与目标参数 · OCCT：原解析 BREP · SMLib：有限 NURBS / 共享拓扑。');
  } else if (variant.pairing === 'same_end_constraints_law_equivalence_unverified') {
    parts.push('同源输入、相同物理两端半径；各内核采用默认内插。全程半径规律等价未验证，不能当成同一沿程 law 评分。');
  } else if (variant.pairing === 'unmatched_special_protocol') {
    parts.push('独立特殊协议：两侧尚未核对同输入、同半径和特殊参数，普通轨结果不能替代。');
  } else parts.push(text(variant.input_construction_note || variant.input_note || variant.representation_note || state.currentCase.representation_note, '内核输入表示与构建方法见记录。'));
  parts.push('普通圆角不代表原图高级语义通过。');
  notice.textContent = 'ⓘ  ' + parts.join('  ');
  notice.hidden = false;
}
function renderComparisonInputMetadata() {
  $('#occtHeading').textContent = '基础模型与选边';
  $('#occtVersion').textContent = 'COMPARISON INPUT';
  $('#occtStatus').textContent = '实验输入';
  $('#occtStatus').className = 'status-badge neutral';
  $('#occtCaption').textContent = '本实验基础输入与目标边 · 内核表示见记录';
}
function renderEngineMetadata(engine) {
  const result = engine === 'smlib' ? smlibResult(state.variant) : state.variant[engine];
  const slot = resultSlots[engine];
  const info = statusInfo(result);
  const badge = $(`#${slot}Status`);
  badge.textContent = info.label; badge.title = info.fullLabel;
  badge.className = `status-badge ${info.tone}`;
  $(`#${slot}Version`).textContent = result?.version ? text(result.version) : (engine === 'occt' ? 'OPEN CASCADE' : 'SMLIB SDK');
  const methodNames = { native_edge_fillet: '原生普通边圆角', native: '原生构建', composite: '组合构造', exact_nurbs: '精确 NURBS 输入' };
  $(`#${slot}Caption`).textContent = engine === 'smlib' ? smlibResultLabel(state.variant) : methodNames[result?.method] || result?.method_label || result?.method || '未记录构建方法';
  if (engine === 'smlib') { badge.textContent = info.fullLabel; badge.title = `${info.fullLabel} · ${smlibPairingLabel(state.variant)}`; }
}

function renderOriginalMetadata() {
  const variant = state.variant, result = variant.occt || {}, info = statusInfo(result);
  const operation = state.inputStage === 'operation';
  const relation = inputRelation(variant);
  const relationLabel = { same_as_base: '同原基础几何', part_selection: '原基础的部件', derived: '已衍生', recorded_combination_input: '组合流程入口', recorded_input: '单列操作记录' }[relation];
  $('#occtHeading').textContent = operation ? '实际操作输入' : '基础模型与选边';
  $('#occtVersion').textContent = operation ? 'OPERATION INPUT' : 'ORIGINAL BASE';
  $('#occtStatus').textContent = operation ? relationLabel : '原版基础';
  $('#occtStatus').className = 'status-badge neutral';
  $('#occtCaption').textContent = operation ? text(variant.operation_relation_note || variant.operation_note || variant.preparation_note || variant.operation_input?.note, `实际操作输入 · ${relationLabel}`) : '原版参数 / 基础输入 · 原选边 / 选面';
  $('#occtCaption').title = $('#occtCaption').textContent;
  $('#smlibStatus').textContent = (historicalResult(variant) ? '历史 · ' : '') + info.fullLabel;
  $('#smlibStatus').className = `status-badge ${failedResult(variant) ? 'failed' : info.tone}`;
  $('#smlibStatus').title = `${info.fullLabel} · ${historicalResult(variant) ? '本次未复跑' : '本次运行'}`;
  $('#smlibVersion').textContent = text(result.version, 'OPEN CASCADE');
  $('#smlibCaption').textContent = failedResult(variant) || !result.mesh ? originalResultLabel(variant) : `${originalMethod(variant)} · ${historicalResult(variant) ? '历史输出，未复跑' : '本次实际输出'}`;
  renderEngineMetadata('smlib');
  $('#validationFootnote').textContent = `${historicalResult(variant) ? '历史记录未复跑' : '已记录本次运行'}；几何、特殊语义和参考外观分别验收。`;
  $$('.input-stage-switch button').forEach((button) => { const active = button.dataset.inputStage === state.inputStage; button.classList.toggle('active', active); button.setAttribute('aria-pressed', active); });
  const pipeline = $('#pipelineBadges'); pipeline.replaceChildren();
  for (const [index, label] of ['原基础', `操作输入 · ${relationLabel}`, originalMethod(variant), historicalResult(variant) ? '验证 · 历史记录 / 未复跑' : '验证 · 本次记录'].entries()) {
    if (index) pipeline.append(newNode('span', 'pipeline-arrow', '→'));
    pipeline.append(newNode('span', `pipeline-badge${index === (operation ? 1 : 0) ? ' active' : ''}`, label));
  }
}
function renderFindings() {
  const variant = state.variant;
  const container = $('#findings');
  container.replaceChildren();
  if (isOriginal(state)) {
    const result = variant.occt || {};
    const humanNote = variant.human_note || state.currentCase.human_note || variant.human_review?.note;
    const humanStatus = variant.human_status || state.currentCase.human_status;
    const cards = [
      ['原版参数 / 基础输入', variantLabel(variant), [originalParameterText(variant), variant.base_note || variant.input_note].filter(Boolean).join(' · ')],
      [originalMethod(variant), failedResult(variant) || !result.mesh ? originalResultLabel(variant) : `${historicalResult(variant) ? '历史记录 · 未复跑' : '本次实际处理'} · ${statusInfo(result).fullLabel}`, result.reason || result.summary || '没有完整处理记录。'],
      ['SMLib 对应证据', smlibResultLabel(variant), smlibResult(variant).reason || smlibResult(variant).summary || '对应关系尚未确认；第四栏只显示独立记录的 SMLib 实际产物。'],
      ['人工核对与验证边界', humanNote ? '保留用户原确认 / 备注' : humanStatus ? `原人工状态：${text(humanStatus)}` : '参考外观仍需人工核对', humanNote ? text(humanNote) : `${humanStatus ? '原人工状态为历史记录，本次未重新验收。' : ''}${variant.scope_note || '基础重建、实际选边 / 选面、处理结果、独立几何验证与原图外观分别验收。'}`],
    ];
    cards.forEach(([label, title, content], index) => { const card = newNode('article', 'finding' + (index === 1 && failedResult(variant) ? ' warn' : '')); const heading = newNode('div', 'finding-label'); heading.append(newNode('span', 'finding-number', index + 1), newNode('span', '', label)); card.append(heading, newNode('h3', '', title), newNode('p', '', text(content))); container.append(card); });
    return;
  }
  const definition = newNode('article', 'finding');
  const label = newNode('div', 'finding-label');
  label.append(newNode('span', 'finding-number', '1'), newNode('span', '', '本次比较'));
  definition.append(label, newNode('h3', '', $('#variantSelect').selectedOptions[0]?.textContent || variantLabel(variant)), newNode('p', '', variant.input_construction_note || variant.input_note || variant.note || state.currentCase.question || '参数相同；输入表示和目标边可在“建模前 / 目标边”中核对。'));
  container.append(definition);
  for (const [index, engine] of ['occt', 'smlib'].entries()) {
    const result = variant[engine];
    const info = statusInfo(result);
    const card = newNode('article', 'finding' + (info.tone === 'failed' || info.tone === 'pending' ? ' warn' : ''));
    const caption = newNode('div', 'finding-label');
    caption.append(newNode('span', 'finding-number', index + 2), newNode('span', '', engine.toUpperCase()));
    const reason = result?.reason || result?.summary || '暂无完整验证记录。';
    card.append(caption, newNode('h3', '', info.label), newNode('p', '', text(reason)));
    container.append(card);
  }
}
async function readMesh(source) {
  if (!source) return null;
  if (typeof source === 'object') return source;
  if (!meshCache.has(source)) meshCache.set(source, fetchJSON(source).catch((error) => { meshCache.delete(source); throw error; }));
  return meshCache.get(source);
}
function validMesh(mesh) { return mesh && Array.isArray(mesh.vertices) && mesh.vertices.length > 2 && Array.isArray(mesh.triangles) && mesh.triangles.length > 0; }
async function renderModels(token) {
  const variant = state.variant;
  const before = $('#beforeToggle').checked;
  const original = isOriginal(state);
  const descriptors = original ? originalDisplay(variant, state.inputStage) : [
    { engine: 'occt', source: variant.input_mesh || variant.occt?.before_mesh || variant.smlib?.before_mesh, targets: variant.targets, faces: variant.selected_faces || [], label: '本实验基础输入 · 目标边', reason: '本实验未提供基础输入网格。' },
    ...['occt', 'smlib'].map((engine) => {
      const result = engine === 'smlib' ? smlibResult(variant) : variant[engine];
      const source = before ? result?.before_mesh : result?.mesh;
      return { engine: resultSlots[engine], source, targets: before ? variant.targets : [], faces: [], label: before ? `${engine.toUpperCase()} 实际建模前输入` : engine === 'smlib' ? smlibResultLabel(variant) : 'OCC 实际输出', reason: before ? '未提供此内核实际使用的建模前网格。' : result?.reason || result?.summary || '尚未提供此内核的实际输出。' };
    }),
  ];
  const tasks = descriptors.map(async (entry) => {
    const { engine, source } = entry;
    const stage = $(`#${engine}Stage`);
    $('.stage-busy', stage).hidden = !source;
    if (!source) return { ...entry, mesh: null };
    try { const mesh = await readMesh(source); return { ...entry, mesh, reason: validMesh(mesh) ? null : '网格数据为空或格式无效。' }; }
    catch (error) { return { ...entry, mesh: null, reason: `网格读取失败：${error.message}` }; }
  });
  const results = await Promise.all(tasks);
  // A retained fragment must not expand to fill the frame. Keep the exact same
  // world bounds for before/after, including both inputs and both real outputs.
  const boundSources = [...new Set((original ? [baseMesh(variant), operationMesh(variant), variant.occt?.mesh, variant.smlib?.before_mesh, variant.smlib?.mesh] : [variant.input_mesh, ...['occt', 'smlib'].flatMap((engine) => [variant[engine]?.before_mesh, variant[engine]?.mesh])]).filter(Boolean))];
  const boundMeshes = await Promise.all(boundSources.map((source) => readMesh(source).catch(() => null)));
  if (token !== state.token) return;
  const bounds = new THREE.Box3();
  for (const mesh of boundMeshes) if (validMesh(mesh)) for (const vertex of mesh.vertices) bounds.expandByPoint(new THREE.Vector3(...vertex));
  for (const entry of results) {
    const stage = $(`#${entry.engine}Stage`);
    $('.stage-busy', stage).hidden = true;
    const empty = $('.stage-empty', stage);
    if (!validMesh(entry.mesh)) {
      state.viewers[entry.engine]?.clear();
      empty.hidden = false;
      $('h3', empty).textContent = entry.engine === 'smlibFourth' ? '尚无对应 SMLib 实际产物' : entry.engine === 'occt' ? '本阶段输入未提供' : before && !original ? '建模前数据未提供' : '没有可展示的实际结果';
      $('p', empty).textContent = text(entry.reason, '暂无数据');
      $('.model-view-label', stage).hidden = true;
      $('.model-hint', stage).hidden = true;
      continue;
    }
    try {
      const viewer = state.viewers[entry.engine] ||= new MeshViewer(stage, entry.engine);
      viewer.setMesh(entry.mesh, bounds, entry.targets, entry.faces, original ? variant.camera || state.currentCase.camera : null);
      empty.hidden = true;
      $('.model-view-label', stage).hidden = false;
      const auxiliary = entry.targets?.some((target) => target.target_kind === 'auxiliary_guide');
      const witnessCount = entry.targets?.filter((target) => target.target_kind === 'result_witness').length || 0;
      const edgeCount = entry.targets?.filter((target) => !['auxiliary_guide','selected_face','result_witness'].includes(target.target_kind)).length || 0;
      const selectionLabel = entry.engine === 'occt' ? [edgeCount ? `${edgeCount} 条选边` : '', entry.faces?.length ? `${entry.faces.length} 个选面` : '', auxiliary ? '虚线为理论辅助位置' : ''].filter(Boolean).join(' · ') || '本阶段未记录选边 / 选面' : [witnessCount ? '绿色为实际自由边' : '', auxiliary ? '虚线为原位置辅助' : ''].filter(Boolean).join(' · ');
      $('.model-label-text', stage).textContent = entry.label + (selectionLabel ? ' · ' + selectionLabel : '');
      $('.model-hint', stage).hidden = false;
    } catch (error) {
      empty.hidden = false;
      $('h3', empty).textContent = '3D 视图无法启动';
      $('p', empty).textContent = `请确认浏览器支持 WebGL。${error.message}`;
    }
  }
}
class MeshViewer {
  constructor(stage, engine) {
    this.stage = stage; this.engine = engine;
    this.scene = new THREE.Scene();
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, .01, 10000);
    this.camera.up.set(0, 0, 1);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.setClearColor(0xffffff, 0);
    $('.model-canvas', stage).append(this.renderer.domElement);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0xa7b4ac, 2.6));
    const key = new THREE.DirectionalLight(0xffffff, 3); key.position.set(5, -7, 10); this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xe9f3ef, 1.1); fill.position.set(-6, 3, 4); this.scene.add(fill);
    this.group = new THREE.Group(); this.scene.add(this.group);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = false;
    this.controls.screenSpacePanning = true;
    this.controls.rotateSpeed = .65;
    this.controls.zoomSpeed = .8;
    this.controls.addEventListener('change', () => {
      this.render();
      if (!$('#syncToggle').checked || state.syncing) return;
      state.syncing = true;
      for (const viewer of Object.values(state.viewers)) if (viewer !== this && viewer.hasMesh) viewer.copyCamera(this);
      state.syncing = false;
    });
    this.observer = new ResizeObserver(() => this.resize()); this.observer.observe(stage);
    this.resize();
  }
  clear() {
    for (const object of [...this.group.children]) { this.group.remove(object); object.traverse((child) => { child.geometry?.dispose(); if (Array.isArray(child.material)) child.material.forEach((item) => item.dispose()); else child.material?.dispose(); }); }
    this.hasMesh = false;
    this.render();
  }
  setMesh(mesh, bounds, targets, selectedFaces = [], camera = null) {
    this.clear();
    this.defaultCamera = camera;
    const vertices = mesh.vertices.flat();
    const triangles = mesh.triangles.flat();
    if (vertices.some((value) => !Number.isFinite(value)) || triangles.some((index) => !Number.isInteger(index) || index < 0 || index >= mesh.vertices.length)) throw new Error('网格包含无效坐标或索引。');
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    geometry.setIndex(triangles); geometry.computeVertexNormals();
    const faceColors = mesh.face_colors || mesh.metadata?.face_colors;
    const partColors = mesh.part_colors || mesh.metadata?.part_colors;
    const coloredGeometry = geometry.toNonIndexed();
    const colors = [];
    for (let index = 0; index < mesh.triangles.length; index++) {
      const faceId = mesh.face_ids?.[index];
      const faceColor = Array.isArray(faceColors) ? faceColors[faceColors.length === mesh.triangles.length ? index : faceId] : faceColors?.[faceId];
      const partId = mesh.part_ids?.[index] ?? mesh.metadata?.face_parts?.[faceId];
      const sourceColor = faceColor || partColors?.[partId];
      const color = new THREE.Color();
      if (Array.isArray(sourceColor)) color.setRGB(...sourceColor.map((value) => value > 1 ? value / 255 : value)); else color.set(sourceColor || 0xc5d2ce);
      for (let vertex = 0; vertex < 3; vertex++) colors.push(color.r, color.g, color.b);
    }
    coloredGeometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    const material = new THREE.MeshStandardMaterial({ color: 0xffffff, vertexColors: true, metalness: .12, roughness: .5, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
    this.group.add(new THREE.Mesh(coloredGeometry, material));
    const edgeMaterial = new THREE.LineBasicMaterial({ color: 0x49645b, transparent: true, opacity: .62 });
    if (Array.isArray(mesh.edges) && mesh.edges.length) {
      for (const edge of mesh.edges) { const points = edge.points || edge; if (!Array.isArray(points) || points.length < 2) continue; const edgeGeometry = new THREE.BufferGeometry().setFromPoints(points.map((point) => new THREE.Vector3(...point))); this.group.add(new THREE.Line(edgeGeometry, edgeMaterial)); }
    } else this.group.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 28), edgeMaterial));
    const center = bounds.getCenter(new THREE.Vector3());
    this.group.position.copy(center).negate();
    this.radius = Math.max(bounds.getSize(new THREE.Vector3()).length() * .5, .1);
    if (Array.isArray(targets)) for (const target of targets) {
      const points = target.samples_mm || target.points || [];
      if (points.length < 2) continue;
      const targetGeometry = new THREE.BufferGeometry().setFromPoints(points.map((point) => new THREE.Vector3(...point)));
      const auxiliary = target.target_kind === 'auxiliary_guide';
      const targetMaterial = auxiliary ? new THREE.LineDashedMaterial({ color: 0xb3855b, transparent: true, opacity: 1, depthTest: false, depthWrite: false, dashSize: this.radius * .04, gapSize: this.radius * .025 }) : new THREE.LineBasicMaterial({ color: target.target_kind === 'selected_face' ? 0xd3a04c : target.target_kind === 'result_witness' ? 0x129c7b : 0xe52d45, transparent: true, opacity: 1, depthTest: false, depthWrite: false, linewidth: 2 });
      const line = new THREE.Line(targetGeometry, targetMaterial); if (auxiliary) line.computeLineDistances(); line.renderOrder = 4; this.group.add(line);
      if (!auxiliary) {
        const ends = new THREE.BufferGeometry().setFromPoints([points[0], points[points.length - 1]].map((point) => new THREE.Vector3(...point)));
        const dots = new THREE.Points(ends, new THREE.PointsMaterial({ color: target.target_kind === 'selected_face' ? 0xd3a04c : target.target_kind === 'result_witness' ? 0x129c7b : 0xe52d45, size: 3.5, sizeAttenuation: false, transparent: true, opacity: 1, depthTest: false, depthWrite: false })); dots.renderOrder = 5; this.group.add(dots);
      }
    }
    for (const selected of Array.isArray(selectedFaces) ? selectedFaces : []) {
      const id = typeof selected === 'object' ? selected.face_id ?? selected.id ?? selected.native_index ?? (selected.index_1based !== undefined ? Number(selected.index_1based) - 1 : selected.index) : selected;
      const faceMesh = typeof selected === 'object' ? selected.mesh || selected : null;
      let points = validMesh(faceMesh) ? faceMesh.triangles.flatMap((triangle) => triangle.flatMap((index) => faceMesh.vertices[index])) : [];
      const selectedIndices = typeof selected === 'object' ? selected.triangle_indices : null;
      if (!points.length) for (let index = 0; index < mesh.triangles.length; index++) if ((Array.isArray(selectedIndices) && selectedIndices.includes(index)) || (id !== undefined && String(mesh.face_ids?.[index]) === String(id))) points.push(...mesh.triangles[index].flatMap((vertex) => mesh.vertices[vertex]));
      if (points.length) { const highlight = new THREE.BufferGeometry(); highlight.setAttribute('position', new THREE.Float32BufferAttribute(points, 3)); highlight.computeVertexNormals(); this.group.add(new THREE.Mesh(highlight, new THREE.MeshStandardMaterial({ color: 0xd3a04c, transparent: true, opacity: .62, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 }))); }
    }
    this.radius = Math.max(bounds.getSize(new THREE.Vector3()).length() * .5, .1);
    this.hasMesh = true; this.reset();
  }
  reset() {
    if (!this.hasMesh) return;
    const distance = this.radius * 4;
    const camera = this.defaultCamera;
    this.camera.up.set(0, 0, 1);
    if (camera) {
      const azimuth = THREE.MathUtils.degToRad(Number(Array.isArray(camera) ? camera[0] : camera.azimuth_deg ?? camera.azimuth ?? -53.5));
      const elevation = THREE.MathUtils.degToRad(Number(Array.isArray(camera) ? camera[1] : camera.elevation_deg ?? camera.elevation ?? 29.2));
      this.camera.position.set(distance * Math.cos(elevation) * Math.cos(azimuth), distance * Math.cos(elevation) * Math.sin(azimuth), distance * Math.sin(elevation));
      const roll = THREE.MathUtils.degToRad(Number(Array.isArray(camera) ? camera[2] || 0 : camera.roll_deg ?? camera.roll ?? 0));
      if (roll) this.camera.up.applyAxisAngle(this.camera.position.clone().normalize(), roll);
    } else this.camera.position.set(distance * .85, -distance * 1.15, distance * .8);
    this.camera.near = Math.max(this.radius * .001, .0001); this.camera.far = this.radius * 100;
    this.camera.zoom = 1;
    this.controls.target.set(0, 0, 0); this.controls.update(); this.resize();
  }
  resize() {
    const width = this.stage.clientWidth || 1, height = this.stage.clientHeight || 1;
    this.renderer.setSize(width, height, false);
    const radius = (this.radius || 1) * 1.2;
    const aspect = width / height;
    if (aspect >= 1) { this.camera.left = -radius * aspect; this.camera.right = radius * aspect; this.camera.top = radius; this.camera.bottom = -radius; }
    else { this.camera.left = -radius; this.camera.right = radius; this.camera.top = radius / aspect; this.camera.bottom = -radius / aspect; }
    this.camera.updateProjectionMatrix(); this.render();
  }
  copyCamera(source) { this.camera.position.copy(source.camera.position); this.camera.quaternion.copy(source.camera.quaternion); this.camera.up.copy(source.camera.up); this.camera.zoom = source.camera.zoom; this.controls.target.copy(source.controls.target); this.camera.updateProjectionMatrix(); this.controls.update(); this.render(); }
  render() { this.renderer.render(this.scene, this.camera); }
}

// Local files never leave this browser. IndexedDB stores only user-selected blobs.
let databasePromise;
function database() {
  return databasePromise ||= new Promise((resolve, reject) => {
    const request = indexedDB.open('filletbench-local-references', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('assets');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function dbAction(mode, key, value) {
  const db = await database();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction('assets', mode === 'get' ? 'readonly' : 'readwrite');
    const store = transaction.objectStore('assets');
    const request = mode === 'get' ? store.get(key) : mode === 'put' ? store.put(value, key) : store.delete(key);
    let result;
    request.onsuccess = () => { result = request.result; };
    request.onerror = () => reject(request.error);
    transaction.oncomplete = () => resolve(result);
    transaction.onabort = () => reject(transaction.error || request.error || new Error('本地存储事务未完成。'));
  });
}
async function digest(bytes) { const hash = await crypto.subtle.digest('SHA-256', bytes); return [...new Uint8Array(hash)].map((value) => value.toString(16).padStart(2, '0')).join(''); }
async function loadPDF(record) {
  const bytes = await record.blob.arrayBuffer();
  const hash = record.hash || await digest(bytes);
  const pdf = await pdfjsLib.getDocument({ data: new Uint8Array(bytes), standardFontDataUrl: new URL('./vendor/pdfjs/standard_fonts/', import.meta.url).href, isEvalSupported: false }).promise;
  state.pdf?.destroy(); state.pdf = pdf; state.pdfMeta = { name: record.name, hash, size: record.blob.size };
}
async function restorePDF() {
  try { const record = await dbAction('get', 'pdf'); if (record) { await loadPDF(record); await renderReference(); } }
  catch (error) { console.warn('Local PDF restoration failed:', error.message); }
}
function currentReferenceMap() {
  const id = state.currentCase?.id;
  const stored = state.mapping[id];
  const matching = Boolean(stored && state.pdfMeta && stored.pdfHash === state.pdfMeta.hash);
  const reference = state.currentCase?.reference || {};
  const expectedPDFHash = reference.expected_pdf_sha256 || state.currentCase?.source_pdf_sha256;
  const sourceMatch = state.pdfMeta?.hash && expectedPDFHash?.toLowerCase() === state.pdfMeta.hash;
  const requestedPage = Number(reference.page) || 1;
  const fallbackPage = !state.pdf || requestedPage <= state.pdf.numPages ? requestedPage : 1;
  return { page: matching && stored.page ? stored.page : Math.min(Math.max(fallbackPage, 1), state.pdf?.numPages || fallbackPage), crop: matching ? stored.crop : sourceMatch ? reference.suggested_crop || null : null, source: stored?.source || 'pdf', sourceMatch };
}
async function importReference(file) {
  if (!file || !state.currentCase) return;
  $('#referenceBusy').hidden = false;
  try {
    if (file.type === 'application/pdf' || /\.pdf$/i.test(file.name)) {
      const bytes = await file.arrayBuffer();
      const record = { blob: file, name: file.name, hash: await digest(bytes) };
      await loadPDF(record);
      try { await dbAction('put', 'pdf', record); } catch { toast('PDF 已载入，但浏览器存储空间不足，刷新后需重新载入。'); }
      state.mapping[state.currentCase.id] = { source: 'pdf', pdfHash: record.hash, page: currentReferenceMap().page, crop: currentReferenceMap().crop };
      saveMappings();
      await renderReference();
      await openReferenceSettings();
    } else if (file.type.startsWith('image/')) {
      const validationUrl = URL.createObjectURL(file);
      try { const previewImage = new Image(); previewImage.src = validationUrl; await previewImage.decode(); }
      finally { URL.revokeObjectURL(validationUrl); }
      const record = { blob: file, name: file.name };
      try { await dbAction('put', 'image:' + state.currentCase.id, record); } catch { throw new Error('浏览器无法保存图片，请检查可用存储空间。'); }
      state.mapping[state.currentCase.id] = { ...(state.mapping[state.currentCase.id] || {}), source: 'image' }; saveMappings();
      await renderReference(); toast('参考图片已保存在本浏览器，已关联当前案例。');
    } else throw new Error('请选择 PDF 或图片文件。');
  } catch (error) { toast(`无法载入参考：${error.message}`); }
  finally { $('#referenceBusy').hidden = true; $('#referenceFile').value = ''; }
}
let referenceRenderToken = 0;
async function renderReference() {
  if (!state.currentCase) return;
  const token = ++referenceRenderToken;
  const mapping = currentReferenceMap();
  let image;
  try { image = await dbAction('get', 'image:' + state.currentCase.id); } catch { /* Reference import remains optional. */ }
  if (token !== referenceRenderToken) return;
  const showImage = image && (mapping.source === 'image' || !state.pdf);
  resetReferenceView();
  $('#referenceZoomControls').hidden = !(showImage || state.pdf);
  $('#referenceEmpty').hidden = Boolean(showImage || state.pdf);
  $('#referenceImageWrap').hidden = !(showImage || state.pdf);
  $('#referenceBadge').hidden = !(showImage || state.pdf);
  $('#changeReference').hidden = !(showImage || state.pdf);
  $('#referenceSettings').disabled = !(showImage || state.pdf);
  if (state.imageUrl) { URL.revokeObjectURL(state.imageUrl); state.imageUrl = null; }
  if (showImage) {
    $('#referenceCanvas').hidden = true; $('#referenceImage').hidden = false;
    state.imageUrl = URL.createObjectURL(image.blob); $('#referenceImage').src = state.imageUrl;
    $('#referenceCaption').textContent = image.name;
    $('#referenceBadge').textContent = '本地图片 · 不上传';
    return;
  }
  $('#referenceImage').hidden = true; $('#referenceCanvas').hidden = false;
  if (!state.pdf) { $('#referenceCaption').textContent = '原始图像不包含在公开仓库中'; return; }
  $('#referenceBusy').hidden = false;
  try {
    const page = await state.pdf.getPage(mapping.page);
    const viewport = page.getViewport({ scale: Math.min(2, 1700 / page.getViewport({ scale: 1 }).width) });
    const offscreen = document.createElement('canvas'); offscreen.width = Math.floor(viewport.width); offscreen.height = Math.floor(viewport.height);
    await page.render({ canvasContext: offscreen.getContext('2d'), viewport }).promise;
    if (token !== referenceRenderToken) return;
    const crop = normalizeCrop(mapping.crop);
    const [x0, y0, x1, y1] = crop || [0, 0, 1, 1];
    const canvas = $('#referenceCanvas'); canvas.width = Math.max(1, Math.round((x1 - x0) * offscreen.width)); canvas.height = Math.max(1, Math.round((y1 - y0) * offscreen.height));
    canvas.getContext('2d').drawImage(offscreen, x0 * offscreen.width, y0 * offscreen.height, canvas.width, canvas.height, 0, 0, canvas.width, canvas.height);
    $('#referenceCaption').textContent = `PDF 第 ${mapping.page} 页${crop ? ' · 局部裁切' : ' · 完整页'}`;
    $('#referenceBadge').textContent = mapping.sourceMatch ? '摘要匹配 · 仅本地' : '本地 PDF · 请核对参考';
  } catch (error) { $('#referenceCaption').textContent = '参考页渲染失败'; toast(`本地 PDF：${error.message}`); }
  finally { if (token === referenceRenderToken) $('#referenceBusy').hidden = true; }
}
function applyReferenceView() {
  const view = state.refView;
  for (const element of [$('#referenceCanvas'), $('#referenceImage')]) element.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.scale})`;
  $('#referenceZoomReset').textContent = `${Math.round(view.scale * 100)}%`;
}
function resetReferenceView() { state.refView = { scale: 1, x: 0, y: 0 }; applyReferenceView(); }
function zoomReference(factor, center) {
  const view = state.refView;
  const next = Math.max(.5, Math.min(6, view.scale * factor));
  const ratio = next / view.scale;
  const stage = $('#referenceStage').getBoundingClientRect();
  const x = center ? center[0] - stage.left - stage.width / 2 : 0;
  const y = center ? center[1] - stage.top - stage.height / 2 : 0;
  view.x = x - (x - view.x) * ratio; view.y = y - (y - view.y) * ratio; view.scale = next;
  applyReferenceView();
}
function setupReferencePanZoom() {
  const wrap = $('#referenceImageWrap'), stage = $('#referenceStage'); let start;
  wrap.addEventListener('pointerdown', (event) => { if (event.button !== 0) return; start = { x: event.clientX, y: event.clientY, panX: state.refView.x, panY: state.refView.y }; wrap.setPointerCapture(event.pointerId); wrap.classList.add('is-dragging'); event.preventDefault(); });
  wrap.addEventListener('pointermove', (event) => { if (!start) return; state.refView.x = start.panX + event.clientX - start.x; state.refView.y = start.panY + event.clientY - start.y; applyReferenceView(); });
  const stop = () => { start = null; wrap.classList.remove('is-dragging'); };
  wrap.addEventListener('pointerup', stop); wrap.addEventListener('pointercancel', stop);
  stage.addEventListener('wheel', (event) => { if (wrap.hidden) return; event.preventDefault(); zoomReference(Math.exp(-event.deltaY * .002), [event.clientX, event.clientY]); }, { passive: false });
  $('#referenceZoomOut').addEventListener('click', () => zoomReference(1 / 1.25));
  $('#referenceZoomIn').addEventListener('click', () => zoomReference(1.25));
  $('#referenceZoomReset').addEventListener('click', resetReferenceView);
}
function normalizeCrop(crop) {
  if (!Array.isArray(crop) || crop.length !== 4 || crop.some((value) => !Number.isFinite(value))) return null;
  const values = crop.map((value) => Math.max(0, Math.min(1, value)));
  return values[2] - values[0] > .01 && values[3] - values[1] > .01 ? values : null;
}
async function openReferenceSettings() {
  if (!state.currentCase) return;
  let image;
  try { image = await dbAction('get', 'image:' + state.currentCase.id); } catch { /* Fall back to file picker. */ }
  const map = currentReferenceMap();
  const showImage = image && (map.source === 'image' || !state.pdf);
  if (!showImage && !state.pdf) { $('#referenceFile').click(); return; }
  const fileInfo = $('#referenceFileInfo'); fileInfo.replaceChildren();
  fileInfo.append(newNode('span', '', showImage ? image.name : state.pdfMeta.name));
  fileInfo.append(newNode('small', '', showImage ? `图片仅关联案例 ${getCaseNumber(state.currentCase)}` : `SHA-256 ${state.pdfMeta.hash.slice(0, 20)}… · ${state.pdf.numPages} 页`));
  $('#pdfControls').hidden = showImage; $('#pdfPreview').hidden = showImage;
  $('#applyReference').textContent = showImage ? '完成' : '应用到当前案例';
  $('#referenceMatch').textContent = showImage ? '图片保存在当前浏览器中；切换案例不会把它套用到其他形状。' : map.sourceMatch ? '源 PDF 摘要匹配。建议页码与裁切来自案例定义，你仍可调整。' : '此 PDF 的摘要与案例来源未匹配。请自行核对页码和图形；不会自动使用建议裁切。';
  $('#referenceDialog').dataset.source = showImage ? 'image' : 'pdf';
  if (!$('#referenceDialog').open) $('#referenceDialog').showModal();
  if (!showImage) { state.previewPage = map.page; state.previewCrop = normalizeCrop(map.crop); await renderPDFPreview(); }
}
async function renderPDFPreview() {
  if (!state.pdf) return;
  const token = ++state.previewToken;
  state.previewPage = Math.min(Math.max(1, Math.round(Number(state.previewPage) || 1)), state.pdf.numPages);
  $('#pdfPageNumber').value = state.previewPage; $('#pdfPageNumber').max = state.pdf.numPages;
  $('#pdfPageCount').textContent = `/ ${state.pdf.numPages}`;
  $('#pdfPrevious').disabled = state.previewPage <= 1; $('#pdfNext').disabled = state.previewPage >= state.pdf.numPages;
  $('#cropSelection').hidden = true;
  try {
    const page = await state.pdf.getPage(state.previewPage);
    const natural = page.getViewport({ scale: 1 });
    const scale = Math.min((Math.min(innerWidth - 85, 780)) / natural.width, (innerHeight * .49) / natural.height) * Math.min(devicePixelRatio, 2);
    const viewport = page.getViewport({ scale });
    const offscreen = document.createElement('canvas'); offscreen.width = Math.floor(viewport.width); offscreen.height = Math.floor(viewport.height);
    await page.render({ canvasContext: offscreen.getContext('2d'), viewport }).promise;
    if (token !== state.previewToken) return;
    const canvas = $('#pdfPreviewCanvas'); canvas.width = offscreen.width; canvas.height = offscreen.height; canvas.getContext('2d').drawImage(offscreen, 0, 0);
    requestAnimationFrame(updateCropOverlay);
  } catch (error) { toast('无法渲染预览：' + error.message); }
}
function updateCropOverlay() {
  const crop = normalizeCrop(state.previewCrop), overlay = $('#cropSelection');
  overlay.hidden = !crop;
  if (!crop) return;
  const rect = $('#pdfPreviewCanvas').getBoundingClientRect(), parent = $('#pdfPreview').getBoundingClientRect();
  Object.assign(overlay.style, { left: rect.left - parent.left + crop[0] * rect.width + 'px', top: rect.top - parent.top + crop[1] * rect.height + 'px', width: (crop[2] - crop[0]) * rect.width + 'px', height: (crop[3] - crop[1]) * rect.height + 'px' });
}
function changePreviewPage(delta) { state.previewPage = Number($('#pdfPageNumber').value) + delta; state.previewCrop = null; renderPDFPreview(); }
function setupCrop() {
  const preview = $('#pdfPreview'); let start = null;
  const point = (event) => { const rect = $('#pdfPreviewCanvas').getBoundingClientRect(); return [Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))]; };
  preview.addEventListener('pointerdown', (event) => { if (event.target !== $('#pdfPreviewCanvas')) return; start = point(event); preview.setPointerCapture(event.pointerId); state.previewCrop = [...start, ...start]; });
  preview.addEventListener('pointermove', (event) => { if (!start) return; const end = point(event); state.previewCrop = [Math.min(start[0], end[0]), Math.min(start[1], end[1]), Math.max(start[0], end[0]), Math.max(start[1], end[1])]; updateCropOverlay(); });
  preview.addEventListener('pointerup', () => { if (!start) return; start = null; state.previewCrop = normalizeCrop(state.previewCrop); updateCropOverlay(); });
  preview.addEventListener('pointercancel', () => { start = null; });
}
function openDetails(engine = null, tab = 'evidence') { if (!state.variant) return; state.detailEngine = engine; state.detailTab = tab; renderDetails(); $('#detailDialog').showModal(); }
function renderDetails() {
  if (!state.variant) return;
  const variant = state.variant;
  const detailName = { input: '基础模型与选边', occt: 'OCC 实际结果', smlib: 'SMLib 实际结果' }[state.detailEngine] || '判据与复现';
  $('#detailTitle').textContent = `${getCaseNumber(state.currentCase)} · ${detailName} · ${variantLabel(variant)}`;
  $$('.detail-tabs button').forEach((button) => { const active = button.dataset.tab === state.detailTab; button.classList.toggle('active', active); button.setAttribute('aria-selected', active); });
  const container = $('#detailContent'); container.replaceChildren();
  const engines = state.detailEngine === 'input' ? [] : state.detailEngine ? [state.detailEngine] : ['occt', 'smlib'];
  if (state.detailTab === 'raw') {
    const record = state.detailEngine && state.detailEngine !== 'input' ? { case: state.currentCase.id, variant: variant.id, radius_mm: variant.radius_mm, [state.detailEngine]: state.detailEngine === 'smlib' ? smlibResult(variant) : variant[state.detailEngine] } : { ...state.currentCase, variants: [variant] };
    container.append(newNode('pre', '', JSON.stringify(record, null, 2))); return;
  }
  if (state.detailTab === 'evidence') {
    container.append(newNode('h3', '', '验证边界'));
    container.append(newNode('p', '', '构建返回、网格生成、BRep 有效性、连续性与参考外观是独立判据。普通边圆角的通过不替代原始参考的特殊语义验收。'));
    const dl = newNode('dl');
    for (const [label, value] of [['案例', state.currentCase.id], ['测试变体', variant.id], ['半径 / mm', variant.radius_mm], ['输入说明', variant.input_construction_note || variant.input_note || variant.note], ['来源 PDF 页', state.currentCase.reference?.page], ['几何 SHA-256', state.currentCase.source_sha256], ['参考 PDF SHA-256', state.currentCase.reference?.expected_pdf_sha256]]) { dl.append(newNode('dt', '', label), newNode('dd', '', text(value))); }
    container.append(dl);
    if (!state.detailEngine || state.detailEngine === 'input') {
      if (isOriginal(state)) {
        const original = newNode('dl');
        for (const [label, value] of [['集合', COLLECTIONS.original.label], ['原版参数', variant.parameters], ['基础模型', baseMesh(variant)], ['实际操作输入', operationMesh(variant)], ['操作输入说明', variant.operation_note || variant.operation_input?.note], ['原选边 / 选面', { targets: variant.targets, selected_faces: variant.selected_faces }], ['历史处理状态', variant.historical_status], ['原人工状态', variant.human_status || state.currentCase.human_status], ['用户确认 / 备注', variant.human_note || state.currentCase.human_note], ['本次 OCC 证据', historicalResult(variant) ? '历史记录，本次未复跑' : '本次运行记录'], ['对应范围', variant.scope_note]]) original.append(newNode('dt', '', label), newNode('dd', '', text(value)));
        container.append(original);
        addModelDownloads(container, 'input');
        for (const [label, source] of [['打开原基础网格', baseMesh(variant)], ['打开实际操作输入网格', operationMesh(variant)]]) { const paragraph = newNode('p'); addDetailLink(paragraph, label, source); container.append(paragraph); }
      } else {
        const input = newNode('p'); addDetailLink(input, '打开实验基础输入网格', variant.input_mesh || variant.occt?.before_mesh || variant.smlib?.before_mesh); container.append(input);
        container.append(newNode('pre', '', JSON.stringify({ targets: variant.targets, selected_faces: variant.selected_faces }, null, 2)));
      }
    }
  }
  if (state.detailTab === 'reproduce' && state.detailEngine === 'input') container.append(newNode('p', '', '基础输入与选边记录见“判据与结果”。各内核的复现命令分别保留在对应的实际结果记录中。'));
  for (const engine of engines) {
    const result = engine === 'smlib' ? smlibResult(variant) : variant[engine] || {};
    const section = newNode('section', 'detail-engine');
    section.append(newNode('h3', '', engine.toUpperCase() + ' · ' + statusInfo(result).fullLabel));
    if (state.detailTab === 'reproduce') {
      const record = typeof result.reproduce === 'object' ? result.reproduce : null;
      const command = record?.command || (typeof result.reproduce === 'string' ? result.reproduce : null);
      section.append(newNode('p', '', record?.reason || '在仓库根目录运行。所需内核、许可证与环境见仓库说明。'));
      if (record?.exact_reproducible === false) section.append(newNode('p', '', '历史快照与新运行的产物分开记录；该命令不承诺逐字节重现历史产物。'));
      if (record?.dependencies?.length) section.append(newNode('p', '', '所需环境：' + record.dependencies.join(' · ')));
      section.append(newNode('pre', '', command || `此变体尚未记录 ${engine.toUpperCase()} 复现命令。`));
      if (command) { const copy = newNode('button', 'outline-button copy-command', '复制命令'); copy.addEventListener('click', async () => { try { await navigator.clipboard.writeText(command); toast('复现命令已复制。'); } catch { toast('无法访问剪贴板，请选择命令文本复制。'); } }); section.append(copy); }
    } else {
      section.append(newNode('p', '', text(result.reason || result.summary, '暂无完整验证说明。')));
      const dl = newNode('dl');
      for (const [label, value] of [['内核版本', result.version], ['构建方法', result.method_label || result.method], ['输入表示', result.input_representation || result.representation], ['网格', result.mesh ? '有实际网格产物；验收状态另列' : '未提供实际产物'], ['结果类别', result.outcome], ['证据来源', result.evidence_kind], ...(engine === 'smlib' ? [['对应状态', `${smlibPairingLabel(variant)} (${text(result.pairing_status)})`], ['SMLib 输入网格', result.before_mesh]] : [])]) dl.append(newNode('dt', '', label), newNode('dd', '', text(value)));
      for (const [key, value] of Object.entries(result.metrics || {})) dl.append(newNode('dt', '', key), newNode('dd', '', text(value)));
      section.append(dl);
      addModelDownloads(section, engine);
      if (result.criteria || result.validation || result.checks) section.append(newNode('pre', '', JSON.stringify(result.criteria || result.validation || result.checks, null, 2)));
      if (isOriginal(state) && engine === 'occt') {
        for (const [label, record] of [['输入关系与预处理', { relation: inputRelation(variant), note: variant.operation_relation_note, preprocess: result.preprocess }], ['实际处理步骤', variant.processing_steps || result.processing_steps]]) {
          if (!record) continue;
          const disclosure = newNode('details', 'processing-record'); disclosure.append(newNode('summary', '', label), newNode('pre', '', JSON.stringify(record, null, 2))); section.append(disclosure);
        }
      }
      for (const [label, path] of [['打开网格 JSON', result.mesh], ['打开日志', result.log || result.log_path], ['打开结果记录', result.report || result.summary_path]]) { if (path) { const paragraph = newNode('p'); addDetailLink(paragraph, label, path); section.append(paragraph); } }
    }
    container.append(section);
  }
}
function expandCard(id) {
  if (state.expanded) { state.expanded.classList.remove('is-expanded'); const button = $('.expand-button', state.expanded); if (button) { button.textContent = '⤢'; button.setAttribute('aria-label', '放大视图'); } }
  if (!id || state.expanded?.id === id) { state.expanded = null; $('#expandBackdrop').hidden = true; document.body.classList.remove('has-expanded'); return; }
  state.expanded = $('#' + id); state.expanded.classList.add('is-expanded'); $('.expand-button', state.expanded).textContent = '×'; $('.expand-button', state.expanded).setAttribute('aria-label', '关闭放大视图'); $('#expandBackdrop').hidden = false; document.body.classList.add('has-expanded');
}
function stepCase(delta) { if (!state.currentCase || !state.catalog) return; const index = state.catalog.cases.findIndex((item) => item.id === state.currentCase.id); const item = state.catalog.cases[index + delta]; if (item) selectCase(item); }
function wireUI() {
  $('.brand').addEventListener('click', (event) => { event.preventDefault(); const home = state.catalog?.cases[0]; if (home) selectCase(home); });
  $$('.collection-tabs button').forEach((button) => button.addEventListener('click', () => { if (button.dataset.series !== state.series || !state.catalog) selectCollection(button.dataset.series); }));
  $$('.input-stage-switch button').forEach((button) => button.addEventListener('click', () => { if (!state.variant) return; state.inputStage = button.dataset.inputStage; renderOriginalMetadata(); renderModels(++state.token); }));
  $('#variantSelect').addEventListener('change', (event) => { const variant = state.currentCase?.variants?.find((item) => item.id === event.target.value); if (variant) selectVariant(variant); });
  $('#caseSearch').addEventListener('input', (event) => { state.query = event.target.value.trim(); renderList(); });
  $$('.filters button').forEach((button) => button.addEventListener('click', () => { state.filter = button.dataset.filter; $$('.filters button').forEach((node) => node.classList.toggle('active', node === button)); renderList(); }));
  $('#previousCase').addEventListener('click', () => stepCase(-1)); $('#nextCase').addEventListener('click', () => stepCase(1));
  $('#mobileMenu').addEventListener('click', () => $('.sidebar').classList.toggle('is-open')); $('#mobileClose').addEventListener('click', () => $('.sidebar').classList.remove('is-open'));
  $('#beforeToggle').addEventListener('change', () => { if (state.variant) renderModels(++state.token); });
  $('#resetView').addEventListener('click', () => Object.values(state.viewers).forEach((viewer) => viewer.reset()));
  $('#syncToggle').addEventListener('change', () => { const viewers = Object.values(state.viewers).filter((viewer) => viewer.hasMesh); if ($('#syncToggle').checked && viewers.length > 1) for (const viewer of viewers.slice(1)) viewer.copyCamera(viewers[0]); });
  $$('.expand-button').forEach((button) => button.addEventListener('click', () => expandCard(button.dataset.expand))); $('#expandBackdrop').addEventListener('click', () => expandCard(null));
  $('#referenceStage').addEventListener('dblclick', () => { if (!$('#referenceImageWrap').hidden) expandCard('referenceCard'); });
  $('#importReference').addEventListener('click', () => $('#referenceFile').click());
  $('#referenceFile').addEventListener('change', (event) => importReference(event.target.files[0]));
  for (const id of ['referenceSettings', 'changeReference']) $('#' + id).addEventListener('click', openReferenceSettings);
  const stage = $('#referenceStage');
  stage.addEventListener('dragover', (event) => { event.preventDefault(); stage.classList.add('dragover'); });
  stage.addEventListener('dragleave', () => stage.classList.remove('dragover'));
  stage.addEventListener('drop', (event) => { event.preventDefault(); stage.classList.remove('dragover'); importReference(event.dataTransfer.files[0]); });
  $('#closeReferenceDialog').addEventListener('click', () => $('#referenceDialog').close());
  $('#replaceReference').addEventListener('click', () => { $('#referenceDialog').close(); $('#referenceFile').click(); });
  $('#pdfPrevious').addEventListener('click', () => changePreviewPage(-1)); $('#pdfNext').addEventListener('click', () => changePreviewPage(1)); $('#pdfPageNumber').addEventListener('change', () => changePreviewPage(0));
  $('#resetCrop').addEventListener('click', () => { state.previewCrop = null; updateCropOverlay(); });
  $('#suggestedCrop').addEventListener('click', async () => {
    const reference = state.currentCase?.reference || {};
    if (!state.pdf || state.pdfMeta?.hash !== reference.expected_pdf_sha256) { toast('当前 PDF 摘要未匹配，请手动选择区域。'); return; }
    state.previewPage = Math.min(state.pdf.numPages, Math.max(1, Number(reference.page) || 1));
    state.previewCrop = normalizeCrop(reference.suggested_crop);
    await renderPDFPreview();
  });
  $('#applyReference').addEventListener('click', async () => { if ($('#referenceDialog').dataset.source === 'pdf' && state.pdf) { state.mapping[state.currentCase.id] = { source: 'pdf', pdfHash: state.pdfMeta.hash, page: state.previewPage, crop: normalizeCrop(state.previewCrop) }; saveMappings(); await renderReference(); } $('#referenceDialog').close(); });
  $('#forgetReference').addEventListener('click', async () => { try { if ($('#referenceDialog').dataset.source === 'image') { await dbAction('delete', 'image:' + state.currentCase.id); delete state.mapping[state.currentCase.id]; } else { await dbAction('delete', 'pdf'); state.pdf?.destroy(); state.pdf = null; state.pdfMeta = null; } saveMappings(); $('#referenceDialog').close(); await renderReference(); toast('本地参考文件已清除。'); } catch (error) { toast('清除失败：' + error.message); } });
  setupCrop();
  setupReferencePanZoom();
  $('#openDetails').addEventListener('click', () => openDetails());
  $$('.inspect-button').forEach((button) => button.addEventListener('click', () => openDetails(button.dataset.engine)));
  $('#closeDetailDialog').addEventListener('click', () => $('#detailDialog').close());
  $$('.detail-tabs button').forEach((button) => button.addEventListener('click', () => { state.detailTab = button.dataset.tab; renderDetails(); }));
  $('#aboutButton').addEventListener('click', () => $('#aboutDialog').showModal()); $('#closeAboutDialog').addEventListener('click', () => $('#aboutDialog').close());
  $$('dialog').forEach((dialog) => dialog.addEventListener('click', (event) => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); } }));
  window.addEventListener('hashchange', () => routeHash());
  window.addEventListener('resize', () => { if ($('#referenceDialog').open) updateCropOverlay(); });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { expandCard(null); $('.sidebar').classList.remove('is-open'); }
    const editing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
    const dialogOpen = $$('dialog').some((dialog) => dialog.open);
    if (event.key === '/' && !editing && !dialogOpen) { event.preventDefault(); if (innerWidth <= 720) $('.sidebar').classList.add('is-open'); $('#caseSearch').focus(); }
    if (!editing && !dialogOpen && !state.expanded && !event.altKey && !event.metaKey && !event.ctrlKey) { if (event.key === 'ArrowLeft') stepCase(-1); if (event.key === 'ArrowRight') stepCase(1); }
  });
}
boot();
