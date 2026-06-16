// Автопилот, Growth Autopilot, логи, мониторинг, библиотека

function renderAutopilotReport(report = {}) {
  const candidates = report.top_candidates || [];
  const schedule = report.schedule_preview || [];
  const checks = report.checks || [];
  const warnings = report.warnings || [];

  $('autopilotCandidates').innerHTML = candidates.length ? candidates.slice(0, 10).map(item => `
    <div class="post-item">
      <div class="post-meta"><span class="post-id">${esc(item.file)}</span><span class="score-pill">${esc(item.score)}</span><span>${esc(item.likes)} лайков</span><span>${esc(item.views)} просмотров</span></div>
      <div class="post-text">${esc(item.text_preview || 'Без текста')}</div>
      <div class="post-date">${(item.reasons || []).map(esc).join(' / ')}</div>
    </div>
  `).join('') : '<div class="empty"><div class="empty-text">Нажми "Собрать отчет", чтобы увидеть кандидатов</div></div>';

  const checkHtml = checks.length ? checks.map(item => `
    <div class="source-item">
      <div class="source-dot ${item.ok ? '' : 'off'}"></div>
      <div class="source-info"><div class="source-name">${esc(item.name)}</div><div class="source-id">${esc(item.value ?? (item.ok ? 'ок' : 'нет'))}</div></div>
    </div>
  `).join('') : '';

  const scheduleHtml = schedule.length ? schedule.slice(0, 12).map(item => `
    <div class="post-item">
      <div class="post-meta"><span class="post-id">пост ${esc(item.post_id || '-')}</span><span>${esc(item.publish_at)}</span><span class="score-pill">${esc(item.score)}</span></div>
      <div class="post-text">${esc(item.caption?.text || '')}</div>
    </div>
  `).join('') : '<div class="empty"><div class="empty-text">Расписание появится после тест-прогона</div></div>';

  $('autopilotSchedule').innerHTML = `
    ${warnings.length ? `<div class="warning-box">${warnings.map(esc).join('<br>')}</div>` : ''}
    ${checkHtml}
    <div class="divider"></div>
    ${scheduleHtml}
  `;
}

async function loadAutopilot() {
  const [auto, tokens] = await Promise.all([
    api('/autopilot/status').catch(() => ({})),
    api('/tokens/status').catch(() => ({})),
  ]);
  state.autopilot = auto;
  state.tokens = tokens;
  const report = auto.last_report || {};
  const summary = report.summary || {};
  setChecked('autopilotDryRun', auto.dry_run !== false);
  $('autopilotStats').innerHTML = `
    <div class="stat-card"><div class="stat-label">Режим</div><div class="stat-value small">${auto.running ? 'Работает' : 'Готов'}</div><div class="stat-sub">${auto.live_enabled ? 'публикация разрешена' : 'публикация выключена'}</div></div>
    <div class="stat-card"><div class="stat-label">Источники</div><div class="stat-value">${summary.sources ?? 0}</div><div class="stat-sub">активных</div></div>
    <div class="stat-card"><div class="stat-label">Кандидаты</div><div class="stat-value">${summary.candidate_count ?? 0}</div><div class="stat-sub">после фильтра рейтинга</div></div>
    <div class="stat-card"><div class="stat-label">Отчет</div><div class="stat-value small">${esc(report.generated_at || 'нет')}</div><div class="stat-sub">${report.dry_run === false ? 'публикация' : 'тест-прогон'}</div></div>
  `;
  renderTokenStatus(tokens);
  renderAutopilotReport(report);
}

async function runAutopilotDryRun() {
  await post('/autopilot/run_once', { dry_run: true }, 'Тест-прогон завершён');
}

async function startAutopilot() {
  await post('/autopilot/start', { dry_run: checked('autopilotDryRun') }, 'Автопилот запущен');
}

// ── Growth Autopilot ─────────────────────────────────────────────────

async function loadGrowth() {
  const phash = await api('/growth/phash_size').catch(() => ({}));
  if ($('dashGaPhash')) $('dashGaPhash').textContent = `pHash: ${phash.size ?? 0}`;
}

async function syncStats() {
  notify('Синхронизирую статистику с VK...', 'info');
  const data = await api('/growth/sync_stats', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => ({ status: 'error', message: 'Нет ответа' }));
  notify(data.message || (data.status === 'ok' ? 'Готово' : 'Ошибка'), data.status === 'ok' ? 'success' : 'error');
  if (data.status === 'ok') await loadDashboard();
}

function gaSettings() {
  return {
    source_mode: val('gaSourceMode') || 'single',
    single_source_id: val('gaSingleSourceId').trim(),
    horizon_days: Number(val('gaHorizonDays') || 2),
    posts_per_day: Number(val('gaPostsPerDay') || 12),
    posts_per_day_min: Number(val('gaPostsPerDay') || 12),
    posts_per_day_max: Number(val('gaPostsPerDay') || 12),
    allowed_hours_start: Number(val('gaHoursStart') || 8),
    allowed_hours_end: Number(val('gaHoursEnd') || 23),
    min_viral_score: Number(val('gaMinScore') || 30),
    hard_antiplagiat: true,
    smart_24h_schedule: true,
    exploitation_percent: 75,
  };
}

function gaRenderReport(report) {
  const summary = report.summary || {};
  $('gaCandidateCount').textContent = summary.candidate_count || 0;
  $('gaScheduledCount').textContent = summary.scheduled_preview || 0;
  $('gaQueueCount').textContent = summary.queue_files || 0;
  $('gaStatusText').textContent = report.generated_at ? `Отчёт: ${report.generated_at}` : 'Автопилот готов.';

  const checks = report.checks || [];
  $('gaChecksList').innerHTML = checks.length ? checks.map(item =>
    `<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)"><span>${esc(item.name)} ${esc(item.value ?? '')}</span><b style="color:${item.ok ? 'var(--success)' : 'var(--error)'}">${item.ok ? 'ОК' : 'СТОП'}</b></div>`
  ).join('') : '<div class="form-hint">Проверок пока нет</div>';

  const candidates = report.top_candidates || [];
  $('gaCandidatesBody_table').innerHTML = candidates.length ? candidates.slice(0, 30).map(item =>
    `<tr><td style="padding:8px;border-bottom:1px solid var(--border)"><b>${esc(item.viral_score)}</b></td><td style="padding:8px;border-bottom:1px solid var(--border)">${esc(item.source_id || '-')}</td><td style="padding:8px;border-bottom:1px solid var(--border)">${esc(item.post_id || '-')}</td><td style="padding:8px;border-bottom:1px solid var(--border)">${esc((item.reasons || []).join(', '))}</td><td style="padding:8px;border-bottom:1px solid var(--border)">${esc(item.text_preview || '')}</td></tr>`
  ).join('') : '<tr><td colspan="5" class="form-hint">Нет кандидатов</td></tr>';

  const schedule = report.schedule_preview || [];
  $('gaScheduleList').innerHTML = schedule.length ? schedule.map(item =>
    `<div style="padding:8px 0;border-bottom:1px solid var(--border)"><b>${esc(item.publish_at)}</b> | ${esc(item.schedule_source || 'слот')} | рейтинг ${esc(item.viral_score)} | пост ${esc(item.post_id || item.file)}</div>`
  ).join('') : '<div class="form-hint">План пуст</div>';
}

async function gaRunPlan() {
  $('gaStatusText').textContent = 'Строю предварительный план...';
  const data = await api('/growth-autopilot/cycle/dry-run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings: gaSettings() }),
  }).catch(error => ({ status: 'error', message: error.message }));
  if (data.status !== 'ok') {
    $('gaStatusText').textContent = data.message || 'Ошибка построения плана';
    return;
  }
  gaRenderReport(data.report);
}

async function gaStartCycle() {
  const btn = $('btnStartCycle');
  if (btn) { btn.disabled = true; btn.textContent = 'Запускается...'; }
  $('gaStatusText').textContent = 'Запускаю цикл...';
  const data = await api('/growth-autopilot/cycle/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  }).catch(error => ({ status: 'error', message: error.message }));
  $('gaStatusText').textContent = data.message || (data.status === 'ok' ? 'Цикл запущен' : 'Ошибка запуска');
  if (btn) { btn.disabled = false; btn.textContent = 'Запустить цикл'; }
  _pollCycleStatus();
}

function _pollCycleStatus() {
  const interval = setInterval(async () => {
    const data = await api('/growth-autopilot/cycle/status').catch(() => null);
    if (!data) return;
    const cycle = data.cycle || data;
    const phase = cycle.phase || '';
    const running = cycle.running === true;
    const phaseLabel = {
      download: 'Скачиваю посты',
      publish: 'Ставлю в очередь VK',
      media: 'Видео и клипы',
      stats: 'Синхронизирую статистику',
      learn: 'Обучаюсь на данных',
      done: 'Цикл завершён',
      error: 'Ошибка цикла',
      empty: 'Нет постов для публикации',
    }[phase] || cycle.message || phase;
    $('gaStatusText').textContent = running ? phaseLabel : (cycle.message || phaseLabel);
    $('dashGaCycle').textContent = running ? (phase || 'работает') : (phase || 'ожидание');
    if (!running) {
      clearInterval(interval);
      loadDashboard();
    }
  }, 3000);
}

// ── Циклы автопилота по типам медиа ──────────────────────────────

const AP_LOOP_LABELS = { posts: 'постов', photos: 'фото', videos: 'видео', clips: 'клипов' };
const AP_PHASE_LABELS = { working: 'работает', stopped: 'остановлен' };
const AP_PROGRESS_PHASE_LABELS = { download: 'Скачивание', publish: 'Публикация', idle: '' };

async function apToggleLoop(type) {
  const btn = $(`apLoopBtn-${type}`);
  const running = btn?.dataset.running === '1';
  const data = await api(`/autopilot/loop/${type}/${running ? 'stop' : 'start'}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  }).catch(error => ({ status: 'error', message: error.message }));
  notify(message(data, 'Готово'), data.status === 'ok' ? 'success' : 'error');
  await apRefreshLoops();
}

function formatApStatus(type, st) {
  if (!st.running) return 'Остановлен';
  const phase = AP_PHASE_LABELS[st.phase] || st.phase || 'работает';
  const progress = st.progress || {};
  const progressLabel = AP_PROGRESS_PHASE_LABELS[progress.phase];
  const parts = [phase];
  if (progressLabel) parts.push(progressLabel);
  return parts.join(' · ');
}

async function apRefreshLoops() {
  const data = await api('/autopilot/loops').catch(() => null);
  if (!data || !data.loops) return;
  const active = [];
  for (const [type, st] of Object.entries(data.loops)) {
    const btn = $(`apLoopBtn-${type}`);
    if (btn) {
      btn.dataset.running = st.running ? '1' : '0';
      btn.classList.toggle('btn-danger', !!st.running);
      btn.classList.toggle('btn-primary', !st.running);
      btn.textContent = st.running ? `■ Стоп ${AP_LOOP_LABELS[type]}` : `Цикл ${AP_LOOP_LABELS[type]}`;
    }
    if (st.running) {
      const phase = AP_PHASE_LABELS[st.phase] || st.phase || 'работает';
      active.push(`${AP_LOOP_LABELS[type]}: ${phase}`);
    }
    apFillLoopInput(`apDownload-${type}`, st.download_count || 1);
    apFillLoopInput(`apPublish-${type}`, st.publish_count || 1);

    const dot = $(`apStatusDot-${type}`);
    if (dot) dot.classList.toggle('running', !!st.running && st.phase === 'working');

    const statusEl = $(`apStatusText-${type}`);
    if (statusEl) statusEl.textContent = formatApStatus(type, st);

    const progress = st.progress || {};
    const total = progress.total || 0;
    const current = progress.current || 0;
    const pct = total > 0 ? Math.round((current / total) * 100) : 0;

    const fill = $(`apProgressFill-${type}`);
    const label = $(`apProgressLabel-${type}`);
    const pctEl = $(`apProgressPct-${type}`);
    if (fill) {
      fill.style.width = total > 0 ? `${pct}%` : '0%';
      fill.classList.toggle('idle', total === 0);
    }
    if (label) label.textContent = total > 0 ? `${current} из ${total}` : '—';
    if (pctEl) pctEl.textContent = total > 0 ? `${pct}%` : '—';
  }
  const statusEl = $('gaStatusText');
  if (statusEl) statusEl.textContent = active.length ? `Работают: ${active.join(' · ')}` : 'Автопилот готов.';
  const cycleEl = $('dashGaCycle');
  if (cycleEl) cycleEl.textContent = active.length ? `${active.length} цикл.` : 'ожидание';
}

function apFillLoopInput(id, value) {
  const input = $(id);
  if (input && document.activeElement !== input) input.value = value;
}

function apLoopSettingsPatch(type) {
  const downloadCount = num(`apDownload-${type}`) || 1;
  const publishCount = num(`apPublish-${type}`) || 1;
  const patch = {};
  if (type === 'posts') {
    patch.download_settings = { posts_to_download: downloadCount };
    patch.publishing_settings = { posts_to_publish: publishCount };
  } else if (type === 'photos') {
    patch.photos_settings = {
      photos_download_per_run: downloadCount,
      photos_publish_per_run: publishCount,
      photos_per_run: publishCount,
    };
  } else if (type === 'videos') {
    patch.videos_settings = {
      videos_download_per_run: downloadCount,
      videos_publish_per_run: publishCount,
      videos_per_run: publishCount,
    };
  } else if (type === 'clips') {
    patch.clips_settings = {
      clips_download_per_run: downloadCount,
      clips_publish_per_run: publishCount,
      clips_per_run: publishCount,
    };
  }
  return patch;
}

async function apSaveLoopSettings(type) {
  await post('/config/save', apLoopSettingsPatch(type), 'Настройки цикла сохранены');
  await apRefreshLoops();
}

let gaLastRecommendationPatch = null;

async function gaAnalyze() {
  $('gaStatusText').textContent = 'Анализирую статистику...';
  const data = await api('/growth-autopilot/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  }).catch(error => ({ status: 'error', message: error.message }));
  if (data.status !== 'ok') {
    $('gaRecommendationBlock').innerHTML = `<div class="form-hint">${esc(data.message || 'Ошибка анализа')}</div>`;
    $('gaStatusText').textContent = data.message || 'Ошибка анализа';
    return;
  }
  const rec = data.recommendation || {};
  gaLastRecommendationPatch = rec.patch || null;
  const autoApplied = data.auto_applied === true;
  $('gaRecommendationBlock').innerHTML = `
    ${autoApplied ? '<div style="color:var(--success,#4caf50);font-size:12px;margin-bottom:6px">✓ Рекомендации применены автоматически</div>' : ''}
    <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)"><span>Постов в день</span><b>${esc(rec.posts_per_day || '-')}</b></div>
    <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)"><span>Лучшие часы</span><b>${esc(rec.hours && rec.hours.length ? rec.hours.join(', ') : 'ещё нет данных')}</b></div>
    <div class="form-hint">${esc(rec.reason || '')}</div>
  `;
  $('gaStatusText').textContent = autoApplied ? 'Анализ готов — рекомендации применены' : 'Анализ готов';
}

async function gaApplyRecommendation() {
  if (!gaLastRecommendationPatch) return;
  const data = await api('/growth-autopilot/apply-recommendation', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ patch: gaLastRecommendationPatch }),
  }).catch(error => ({ status: 'error', message: error.message }));
  $('gaStatusText').textContent = data.message || 'Рекомендации применены';
  gaLastRecommendationPatch = null;
}

async function fillSlots() {
  const btn = document.querySelector('button[onclick="fillSlots()"]');
  if (btn) { btn.disabled = true; btn.textContent = 'Ищу слоты...'; }
  try {
    const data = await api('/publish/fill_slots', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) }).catch(e => ({ status: 'error', message: e.message }));
    if (data.slots && data.slots.length > 0) {
      const preview = data.slots.slice(0, 5).map(s => s.display).join(', ');
      const more = data.slots.length > 5 ? ` и ещё ${data.slots.length - 5}...` : '';
      const confirmed = confirm(`Найдено ${data.slots.length} свободных слотов:\n${preview}${more}\n\nЗаполнить постами из очереди?`);
      if (confirmed) {
        const res = await api('/publish/fill_slots_apply', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ slots: data.slots }) }).catch(e => ({ filled: 0, failed: 0 }));
        showToast(`Заполнено: ${res.filled}, ошибок: ${res.failed}`, res.failed > 0 ? 'warning' : 'success');
        if (document.querySelector('.tab-content.active')?.id === 'logs') loadLogs();
      }
    } else {
      showToast(data.message || 'Свободных слотов не найдено', 'info');
    }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Заполнить пустые слоты'; }
  }
}

async function checkEngagement() {
  const btn = document.querySelector('button[onclick="checkEngagement()"]');
  if (btn) { btn.disabled = true; btn.textContent = 'Проверяю...'; }
  try {
    const data = await api('/publish/check_engagement', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) }).catch(e => ({ checked: 0, message: e.message }));
    showToast(data.message || `Проверено постов: ${data.checked || 0}`, 'success');
    if (document.querySelector('.tab-content.active')?.id === 'logs') loadLogs();
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Проверить engagement'; }
  }
}

// ── Логи ─────────────────────────────────────────────────────────────

let _logsAll = [];
let _logFilter = 'all';

function setLogFilter(filter, btn) {
  _logFilter = filter;
  document.querySelectorAll('.log-filter-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderLogFiltered();
}

function _classifyLog(msg) {
  if (!msg) return 'other';
  const m = msg.toLowerCase();
  if (m.includes('[публикация]') || m.includes('запланирован') || m.includes('опубликован') || m.includes('publish')) return 'publish';
  if (m.includes('[обучение]') || m.includes('[умное расписание]') || m.includes('модель') || m.includes('engagement')) return 'learn';
  if (m.includes('[слоты]') || m.includes('slot') || m.includes('пустые слоты')) return 'slots';
  if (m.includes('ошибка') || m.includes('error') || m.includes('failed') || m.includes('критичн')) return 'error';
  return 'other';
}

function renderLogFiltered() {
  const logs = _logFilter === 'all'
    ? _logsAll
    : _logFilter === 'error'
      ? _logsAll.filter(l => (l.level === 'error' || l.level === 'warning') || _classifyLog(l.message || l) === 'error')
      : _logsAll.filter(l => _classifyLog(l.message || l) === _logFilter);
  renderLog('logsList', logs);
}

async function loadLogs() {
  const data = await api('/logs').catch(() => ({ logs: [] }));
  _logsAll = data.logs || [];
  renderLogFiltered();
  await loadCleanupStatus();
}

async function loadCleanupStatus() {
  const data = await api('/cleanup/status').catch(() => ({}));
  if (!$('cleanupStatus')) return;
  $('cleanupStatus').innerHTML = `
    <div class="cleanup-grid">
      <div class="stat-card flat"><div class="stat-label">Скачанные посты</div><div class="stat-value">${data.downloaded_posts ?? 0}</div><div class="stat-sub">${data.posts_mb ?? 0} MB</div></div>
      <div class="stat-card flat"><div class="stat-label">Папки фото</div><div class="stat-value">${data.photo_dirs ?? 0}</div><div class="stat-sub">мусорных: ${data.orphan_photo_dirs ?? 0}</div></div>
      <div class="stat-card flat"><div class="stat-label">Медиа</div><div class="stat-value">${data.media_files ?? 0}</div><div class="stat-sub">${data.media_mb ?? 0} MB</div></div>
      <div class="stat-card flat"><div class="stat-label">Storage</div><div class="stat-value small">${data.storage_mb ?? 0} MB</div><div class="stat-sub">активный профиль</div></div>
    </div>
  `;
}

function renderLog(id, logs) {
  const el = $(id);
  if (!el) return;
  if (!logs.length) {
    el.innerHTML = '<div class="log-line"><span class="log-message">Лог пуст</span></div>';
    return;
  }
  el.innerHTML = logs.slice(0, 200).map(item => {
    const text = typeof item === 'string' ? item : item.message;
    return `<div class="log-line"><span class="log-time">${esc(item.timestamp || '')}</span><span class="log-level ${esc(item.level || 'info')}">${esc(item.level || 'info')}</span><span class="log-message">${esc(looksBroken(text) ? '[сообщение из старой кодировки]' : text)}</span></div>`;
  }).join('');
}

async function clearLogs() {
  await post('/logs/clear', {}, 'Логи очищены');
}

// ── Библиотека ────────────────────────────────────────────────────────

async function loadLibrary() {
  const [data, niches, promo] = await Promise.all([
    api('/library').catch(() => ({})),
    api('/library/niches').catch(() => ({ niches: [] })),
    api('/library/promo').catch(() => ({ promo_enabled: false, promo_messages: [] })),
  ]);
  state.library = data;
  $('libraryControls').innerHTML = `
    <label class="toggle-row"><span class="toggle-info"><span class="toggle-label">Включить библиотеку</span><span class="toggle-desc">Заменять оригинальный текст случайной заготовкой</span></span><span class="toggle"><input id="libraryEnabled" type="checkbox" ${data.enabled ? 'checked' : ''}><span class="toggle-slider"></span></span></label>
    <label class="toggle-row"><span class="toggle-info"><span class="toggle-label">CTA</span><span class="toggle-desc">Добавлять призыв к действию</span></span><span class="toggle"><input id="libraryCtaEnabled" type="checkbox" ${data.cta_enabled ? 'checked' : ''}><span class="toggle-slider"></span></span></label>
    <div class="form-row"><select class="form-input" id="libraryNiche">${(niches.niches || []).map(n => `<option value="${escAttr(n.id)}" ${n.id === data.niche ? 'selected' : ''}>${esc(n.label)} (${n.entries_count})</option>`).join('')}</select><button class="btn btn-secondary" onclick="applyLibraryNiche()">Применить нишу</button></div>
  `;

  // ── Promo-сообщения ───────────────────────────────────────────────
  const promoMsgs = promo.promo_messages || [];
  const promoEnabled = promo.promo_enabled || false;
  const promoHtml = `
    <div class="card" style="margin-top:16px">
      <div class="card-header">
        <div class="card-title">Сообщения для продвижения</div>
        <div style="display:flex;gap:8px;align-items:center">
          <label class="toggle" title="Добавлять к каждому посту">
            <input type="checkbox" id="promoEnabled" ${promoEnabled ? 'checked' : ''} onchange="togglePromo(this.checked)">
            <span class="toggle-slider"></span>
          </label>
        </div>
      </div>
      <div class="form-hint" style="padding:0 16px 8px">Активное сообщение заменяет текст поста. Хэштеги добавляются в конец.</div>
      <div id="promoList" style="padding:0 16px 12px">
        ${promoMsgs.length ? promoMsgs.map(m => `
          <div class="post-item" style="border:2px solid ${m.active ? 'var(--accent,#7c3aed)' : 'var(--border)'}">
            <div class="post-meta">
              <span class="post-id">${esc(m.name)}</span>
              ${m.active ? '<span class="score-pill" style="background:var(--accent,#7c3aed);color:#fff">Активное</span>' : `<button class="btn btn-secondary btn-sm" onclick="activatePromo('${escAttr(m.id)}')">Выбрать</button>`}
              <button class="btn btn-danger btn-sm" onclick="deletePromo('${escAttr(m.id)}')">Удалить</button>
            </div>
            <div class="post-text" style="white-space:pre-wrap">${esc(m.text)}</div>
            <div class="post-date">${esc(m.hashtags || '')}</div>
          </div>`).join('') : '<div class="form-hint">Нет сообщений — добавьте первое ниже</div>'}
      </div>
      <div class="form-section" style="border-top:1px solid var(--border);padding:12px 16px">
        <div class="form-group">
          <label class="form-label">Название шаблона</label>
          <input class="form-input" id="promoName" placeholder="Марафон 1 000 000">
        </div>
        <div class="form-group">
          <label class="form-label">Текст сообщения (3-4 строки)</label>
          <textarea class="form-input" id="promoText" rows="5" placeholder="🌿 НАША ЦЕЛЬ — 1 000 000 ПОДПИСЧИКОВ&#10;&#10;Каждый лайк помогает нам расти.&#10;Подпишитесь — и станьте частью движения. 🌍"></textarea>
        </div>
        <div class="form-group">
          <label class="form-label">Хэштеги</label>
          <input class="form-input" id="promoHashtags" placeholder="#природа #экология #марафон">
        </div>
        <button class="btn btn-primary" onclick="addPromo()">Добавить шаблон</button>
      </div>
    </div>
  `;

  const entries = data.entries || [];
  $('libraryBlock').innerHTML = promoHtml + (entries.length ? entries.slice(0, 60).map((entry, index) => `
    <div class="post-item">
      <div class="post-meta"><span class="post-id">#${index + 1}</span><button class="btn btn-danger btn-sm" onclick="del('/library/entry/${index}', 'Заготовка удалена')">Удалить</button></div>
      <div class="post-text">${esc(entry.text || entry.title || JSON.stringify(entry).slice(0, 240))}</div>
      <div class="post-date">${esc(entry.tags || '')}</div>
    </div>`).join('') : '<div class="empty"><div class="empty-text">Библиотека пустая</div></div>');
}

async function togglePromo(enabled) {
  await post('/library/promo/toggle', { enabled }, enabled ? 'Promo включено' : 'Promo выключено');
}

async function addPromo() {
  const name = val('promoName').trim();
  const text = val('promoText').trim();
  const hashtags = val('promoHashtags').trim();
  if (!text) { showToast('Введите текст сообщения', 'error'); return; }
  await post('/library/promo/add', { name: name || 'Новый шаблон', text, hashtags }, 'Шаблон добавлен');
  setValue('promoName', ''); setValue('promoText', ''); setValue('promoHashtags', '');
  await loadLibrary();
}

async function activatePromo(id) {
  const r = await api(`/library/promo/activate/${id}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => ({ status: 'error' }));
  if (r.status === 'ok') { showToast('Шаблон активирован', 'success'); await loadLibrary(); }
  else showToast('Ошибка активации', 'error');
}

async function deletePromo(id) {
  const r = await api(`/library/promo/${id}`, { method: 'DELETE' }).catch(() => ({ status: 'error' }));
  if (r.status === 'ok') { showToast('Шаблон удалён', 'success'); await loadLibrary(); }
  else showToast('Ошибка удаления', 'error');
}

async function saveLibrarySettings() {
  await post('/library/save', {
    enabled: checked('libraryEnabled'),
    cta_enabled: checked('libraryCtaEnabled'),
  }, 'Библиотека сохранена');
}

async function applyLibraryNiche() {
  await post('/library/apply_niche', { niche: val('libraryNiche') }, 'Пресет применен');
}

