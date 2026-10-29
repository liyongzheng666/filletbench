export const COLLECTIONS = {
  original: { path: 'data/original-occ/catalog.json', label: '基准案例', caseRoot: 'data/original-occ/cases/' },
  comparison: { path: 'data/catalog.json', label: '历史实验', caseRoot: 'data/cases/' },
};

export function isOriginal(state) { return state.series === 'original'; }
export function casePath(item, series) { return item.data || `${COLLECTIONS[series].caseRoot}${String(item.number).padStart(2, '0')}.json`; }
export function baseMesh(variant) { return variant.base_mesh || variant.base?.mesh || null; }
export function operationMesh(variant) { return variant.operation_mesh || variant.operation_input?.mesh || variant.occt?.before_mesh || baseMesh(variant); }
export function inputRelation(variant) {
  const relation = variant.input_relation || variant.operation_input?.relation;
  if (relation === 'same_as_base' || relation === 'identity') return 'same_as_base';
  if (relation === 'part_selection') return 'part_selection';
  if (relation === 'derived') return 'derived';
  if (relation === 'recorded_combination_input') return 'recorded_combination_input';
  for (const flag of [variant.operation_is_derived, variant.operation_input_is_derived, variant.operation_input?.is_derived]) if (typeof flag === 'boolean') return flag ? 'derived' : 'same_as_base';
  const recipe = variant.occt?.preprocess?.requested_recipe?.type || variant.parameters?.preprocess?.type;
  if (recipe && !['none', 'identity', 'read_base', 'source_base'].includes(recipe)) return 'derived';
  const base = baseMesh(variant), operation = operationMesh(variant);
  return operation && operation !== base ? 'recorded_input' : 'same_as_base';
}
export function hasDerivedInput(variant) { return inputRelation(variant) !== 'same_as_base'; }
export function selectionFor(variant, stage = 'base') {
  const record = variant.selection?.[stage] || variant[`${stage}_selection`] || {};
  const selection = Array.isArray(record) ? record.length === 1 ? record[0] : {} : record;
  const targets = selection.targets || variant[`${stage}_targets`] || (stage === 'base' || !hasDerivedInput(variant) ? variant.targets : []) || [];
  return {
    targets: targets.map((target) => ({ ...target, samples_mm: target.samples_mm || target.polyline || target.samples || target.points || (target.start && target.end ? [target.start, target.end] : []), target_kind: target.target_kind || selection.target_kind || variant[`${stage}_target_kind`] || variant.target_kind || 'native_edge' })),
    faces: selection.selected_faces || variant[`${stage}_selected_faces`] || (stage === 'base' || !hasDerivedInput(variant) ? variant.selected_faces : []) || [],
  };
}
export function historicalResult(variant) {
  const result = variant.occt || {};
  const kind = String(result.evidence_kind || variant.evidence_kind || '').toLowerCase();
  if (/historical|snapshot|source_freeze/.test(kind)) return true;
  if (result.fresh_run === true || variant.fresh_run === true) return false;
  return !/^(fresh_run|fresh_verified_run|current_run|rerun|fresh_observed_run)$/.test(kind);
}
export function failedResult(variant) {
  const result = variant.occt || {};
  return /fail|invalid|error|crash|reject|self_intersect/.test(String(result.status || '').toLowerCase()) || result.api_success === false;
}
export function originalMethod(variant) {
  const method = variant.occt?.method || variant.method || '';
  const names = { native_edge_fillet: 'native 普通边圆角', native_ordinary_fillet: 'native 普通边圆角', ordinary_native_reference: 'native 普通参考', native_edge_fillet_control: 'native 边圆角控制', native_sequential_edge_fillets: 'native 顺序边圆角', ordinary_native_free_propagation: 'native 自由传播', native_variable_radius_fillet: 'native 变半径圆角', native_circular_fillet_control: 'native 圆弧控制', ordinary_untrimmed_control: 'native 未裁剪控制', explicit_occ_composition: '显式 OCC 组合构造', input_only_preserved: '仅保留原输入', native: 'native 原生构建', composite: '组合构造', explicit: '显式组合构造', historical: '历史处理记录' };
  return variant.occt?.method_label || variant.method_label || names[method] || method || '处理方法未记录';
}
export function originalResultLabel(variant) {
  const result = variant.occt || {};
  if (result.method === 'input_admission_check' && result.native_call_executed === false) return '原输入检查完成 · 未调用圆角';
  if (!result.mesh) return failedResult(variant) ? '处理失败，仅显示输入' : '未执行处理，仅显示输入';
  const prefix = historicalResult(variant) ? '历史' : '本次';
  if (failedResult(variant)) {
    if (result.mesh === operationMesh(variant) || result.mesh === result.before_mesh || result.unchanged_input === true) return '调用失败，保留的未改变输入';
    const status = String(result.status || '').toLowerCase();
    if (/export|step/.test(status)) return `${prefix}实际 BREP 候选 · STEP 未通过`;
    if (/geometry|invalid|self_intersect/.test(status)) return `${prefix}无效 BREP 候选 · 几何未通过`;
    if (/api|error|crash|reject/.test(status)) return `${prefix} API 失败 · 实际保留候选`;
    return `${prefix}处理未通过 · 实际保留候选`;
  }
  return historicalResult(variant) ? '历史 OCC 实际输出 · 未复跑' : '本次 OCC 实际输出';
}
export function originalDisplay(variant, stage = 'base') {
  const result = variant.occt || {};
  const input = operationMesh(variant);
  const output = result.mesh || (result.display_input_on_missing_result === false ? null : input);
  return [
    { engine: 'occt', source: stage === 'operation' ? input : baseMesh(variant), ...selectionFor(variant, stage), label: stage === 'operation' ? '实际操作输入' : '基础模型', reason: stage === 'operation' ? '未提供实际操作输入网格。' : '未提供基础模型网格；不会使用衍生输入代替。' },
    { engine: 'smlib', source: output, ...(!result.mesh ? selectionFor(variant, 'operation') : { targets: result.result_witnesses || [], faces: [] }), label: originalResultLabel(variant), reason: result.reason || result.summary || '没有实际 OCC 输出；原目标与参数保持不变。' },
    { engine: 'smlibFourth', source: smlibResult(variant).mesh, targets: smlibResult(variant).result_witnesses || [], faces: [], label: smlibResultLabel(variant), reason: smlibResult(variant).reason || smlibResult(variant).summary || '尚无对应 SMLib 实际产物。' },
  ];
}

// The SDK column never falls back to an OCC result or to an input mesh.
export function smlibResult(variant) {
  return variant.smlib || { status: 'missing', label: '尚无对应 SMLib 结果', reason: '尚未记录与本案例输入、选边、半径和处理方法对应的 SMLib 实际产物。', pairing_status: 'unmatched' };
}
export function smlibPairingLabel(variant) {
  const pairing = smlibResult(variant).pairing_status;
  return pairing === 'matched' ? '输入、选边、半径与方法已匹配' : pairing === 'matched_constraints_different_representation' ? '同源输入与目标参数 · 内核表示不同' : '对应关系未完整确认';
}
export function smlibResultLabel(variant) {
  const result = smlibResult(variant);
  if (!result.mesh) return result.label || '尚无对应 SMLib 实际产物';
  const failed = /fail|invalid|error|crash|reject|self_intersect/.test(String(result.status || '').toLowerCase()) || result.api_success === false;
  const pairing = result.pairing_status === 'matched' ? '同输入与参数' : result.pairing_status === 'matched_constraints_different_representation' ? '同参 · 表示不同' : '匹配未确认';
  const provenance = result.evidence_kind === 'matched_existing_run' ? '已实跑记录' : '实际产物';
  if (failed && result.unchanged_input === true) return 'SMLib 调用失败 · 保留的输入未改变';
  return failed ? `SMLib ${provenance} · 失败候选 · ${pairing}` : `SMLib ${provenance} · ${pairing}`;
}
