// Дашборд и прогресс

async function loadProfiles() {
  const data = await api('/profiles');
  state.profiles = data.profiles || [];
  state.activeProfile = state.profiles.find(profile => profile.active) || state.profiles[0] || null;
  renderProfileSwitcher();
}

function renderProfileSwitcher() {
  if (!state.activeProfile) {
    $('profileName').textContent = 'Канал не выбран';
    $('profileDot').style.background = '#9ca3af';
    $('profileDropdown').innerHTML = '<div class="profile-dropdown-empty">Каналов нет</div>';
    return;
  }
  $('profileName').textContent = state.activeProfile.name || 'Канал';
  $('profileDot').style.background = '#7c3aed';
  $('profileDropdown').innerHTML = state.profiles.map(profile => `
    <button class="profile-option ${profile.active ? 'active' : ''}" type="button" onclick="switchProfile('${escAttr(profile.id)}')">
      <span>${esc(profile.name || profile.id)}</span>
      <small>ID: ${esc(profile.group_id || profile.vk?.group_id || '-')}</small>
    </button>
  `).join('') + '<button class="profile-option add" type="button" onclick="switchTab(\'channels\')">+ Добавить канал</button>';
}

async function loadConfig() {
  state.config = await api('/config/get');
}

async function loadDashboard() {
  const growthData = await api('/dashboard/growth').catch(() => null);
  const data = growthData?.dashboard || await api('/dashboard');
  state.dashboard = data;
  if (growthData?.status === 'ok') state.dashboardGrowth = growthData;
  $('statToday').textContent = data.published_today ?? 0;
  $('statErrors').textContent = data.errors_today ?? 0;
  $('queueCount').textContent = data.pending ?? 0;
  $('statErrorsCard').classList.toggle('has-errors', Number(data.errors_today || 0) > 0);
  setHealth('healthDownload', data.is_downloading);
  setHealth('healthPublish', data.is_publishing);
  setHealth('healthMonitor', data.is_monitoring);
  const busy = data.is_downloading || data.is_publishing || data.is_monitoring;
  $('statusDot').classList.toggle('busy', !!busy);
  $('statusText').textContent = busy ? 'Работает' : 'Готов';
  if (growthData?.status === 'ok') renderDashboardGrowth(growthData);
  else await loadDashboardGrowth();
  await loadDownloadProgress();
  await loadGrowth();
}

async function loadDashboardGrowth() {
  const data = await api('/dashboard/growth').catch(() => null);
  if (!data || data.status !== 'ok') return;
  state.dashboardGrowth = data;
  renderDashboardGrowth(data);
}

function renderDashboardGrowth(data) {
  const profile = data.profile || {};
  const dashboard = data.dashboard || {};
  const subscribers = data.subscribers || {};
  const tracker = data.tracker || {};
  const ga = data.growth_autopilot || {};
  const settings = ga.settings || {};
  const cycle = ga.cycle || {};
  const report = ga.report || {};
  const summary = report.summary || {};

  $('dashGaChannel').textContent = profile.name || profile.id || '-';
  $('dashGaGroup').textContent = `VK ID: ${profile.group_id || '-'}`;
  $('dashGaMembers').textContent = subscribers.members ?? subscribers.current ?? 0;
  $('dashGaMembersDiff').textContent = `сегодня: ${subscribers.diff_today ?? 0}, неделя: ${subscribers.diff_week ?? 0}`;
  $('dashGaViews').textContent = tracker.avg_views ?? 0;
  $('dashGaLikes').textContent = `лайки: ${tracker.avg_likes ?? 0}, проверено: ${tracker.checked ?? 0}`;
  if (data.phash_size != null && $('dashGaPhash')) $('dashGaPhash').textContent = `pHash: ${data.phash_size}`;
  $('dashGaCycle').textContent = cycle.running ? (cycle.phase || 'работает') : (cycle.phase || 'ожидание');
  $('dashGaQueue').textContent = `сегодня: ${dashboard.published_today ?? 0}`;
  if ($('dashGaQueue2')) $('dashGaQueue2').textContent = dashboard.pending ?? 0;

  if (!val('gaSingleSourceId')) setValue('gaSingleSourceId', settings.single_source_id || '');
  if (!val('gaHorizonDays')) setValue('gaHorizonDays', settings.horizon_days || 2);
  if (!val('gaPostsPerDay')) setValue('gaPostsPerDay', settings.posts_per_day || 12);
  if (!val('gaMinScore')) setValue('gaMinScore', settings.min_viral_score ?? 30);
  if (settings.source_mode) setValue('gaSourceMode', settings.source_mode);

  if (cycle.running) {
    $('gaStatusText').textContent = cycle.message || cycle.phase || 'Цикл работает...';
  } else if (cycle.phase === 'done') {
    $('gaStatusText').textContent = cycle.message || 'Цикл завершён';
  } else {
    $('gaStatusText').textContent = 'Автопилот готов.';
  }
  loadBotChanges();
}

function setHealth(id, enabled) {
  const el = $(id);
  if (!el) return;
  el.classList.toggle('ok', !!enabled);
  el.querySelector('b').textContent = enabled ? 'идет' : 'нет';
}

async function loadDownloadProgress() {
  const data = await api('/download/progress').catch(() => ({}));
  if (!$('progressTitle') || !$('downloadProgressBar')) return;
  const percent = Number(data.percent || 0);
  const busyDownload = !!data.is_downloading;
  const busyPublish = !!data.is_publishing;
  const busy = busyDownload || busyPublish;
  const phaseLabel = data.phase === 'publish' ? 'Публикация' : data.phase === 'download' ? 'Загрузка' : 'Прогресс';
  $('progressTitle').textContent = phaseLabel;
  $('progressPercent').textContent = `${percent}%`;
  $('downloadProgressBar').style.width = `${percent}%`;
  $('downloadProgressText').textContent = busy
    ? `${data.message || phaseLabel}: ${data.current || 0} из ${data.total || 0}, источник: ${data.source || '-'}`
    : 'Сейчас загрузка не идет';

  ['btnDownloadMenu', 'btnPublishQueue'].forEach(id => { if ($(id)) $(id).disabled = busy; });
  document.querySelectorAll('[data-download-source]').forEach(btn => { btn.disabled = busy || btn.dataset.enabled === 'false'; });
  if ($('btnStopDownload')) $('btnStopDownload').disabled = !busyDownload;
  if ($('btnStopPublish')) $('btnStopPublish').disabled = !busyPublish;
}

function renderDownloadMenu() {
  const menu = $('downloadMenu');
  if (!menu) return;
  const sources = state.config?.sources || [];
  const enabledSources = sources.filter(source => source.enabled !== false);
  const allDisabled = enabledSources.length === 0;
  const sourceItems = sources.map(source => {
    const enabled = source.enabled !== false;
    return `
      <button class="action-menu-item" type="button" data-download-source="${escAttr(source.community_id)}" data-enabled="${enabled ? 'true' : 'false'}" ${enabled ? '' : 'disabled'} onclick="downloadOne('${escAttr(source.community_id)}')">
        <span>${esc(source.name || source.community_id || 'Источник')}</span>
        <small>${enabled ? `ID: ${esc(source.community_id)}` : `Выключен · ID: ${esc(source.community_id)}`}</small>
      </button>`;
  }).join('');

  menu.innerHTML = `
    <button class="action-menu-item action-menu-primary" type="button" data-download-source="all" data-enabled="${allDisabled ? 'false' : 'true'}" ${allDisabled ? 'disabled' : ''} onclick="downloadAllSources()">
      <span>Все источники</span>
      <small>${enabledSources.length ? `${enabledSources.length} активных` : 'Нет активных источников'}</small>
    </button>
    ${sources.length ? '<div class="action-menu-separator"></div>' : ''}
    ${sources.length ? sourceItems : '<div class="action-menu-empty">Источников пока нет</div>'}
  `;
}

async function toggleDownloadMenu(event) {
  event?.stopPropagation();
  if (!state.config) {
    await loadConfig().catch(() => {});
  }
  renderDownloadMenu();
  const menu = $('downloadMenu');
  if (!menu) return;
  menu.classList.toggle('active');
}

function closeDownloadMenu() {
  $('downloadMenu')?.classList.remove('active');
}

async function downloadAllSources() {
  closeDownloadMenu();
  await post('/download/start_all', {}, 'Загрузка запущена');
}

async function loadAllStats() {
  const container = $('allStatsContent');
  if (!container) return;
  try {
    const data = await api('/statistics/all_profiles');
    renderAllStats(data.profiles || []);
  } catch (e) {
    container.innerHTML = '<div class="form-hint" style="padding:16px;color:var(--error,#ef4444)">Ошибка загрузки статистики</div>';
  }
}

function renderAllStats(profiles) {
  const container = $('allStatsContent');
  if (!container) return;
  if (!profiles.length) {
    container.innerHTML = '<div class="form-hint" style="padding:16px">Нет профилей</div>';
    return;
  }

  const rows = profiles.map(p => {
    const activeBadge = p.active ? '<span class="allstats-badge">активный</span>' : '';
    const dot = `<span class="allstats-dot" style="background:${p.color || '#7c3aed'}"></span>`;
    return `<tr class="${p.active ? 'allstats-row-active' : ''}">
      <td>${dot}${p.name}${activeBadge}</td>
      <td class="allstats-num">${p.published}</td>
      <td class="allstats-num allstats-today">${p.today_published}</td>
      <td class="allstats-num">${p.pending}</td>
      <td class="allstats-num ${p.failed > 0 ? 'allstats-error' : ''}">${p.failed}</td>
      <td class="allstats-num ${p.today_errors > 0 ? 'allstats-error' : ''}">${p.today_errors}</td>
      <td class="allstats-num">${p.storage_mb} МБ</td>
      <td class="allstats-ts">${p.last_scheduled}</td>
    </tr>`;
  }).join('');

  const totals = profiles.reduce((acc, p) => {
    acc.published += p.published;
    acc.today_published += p.today_published;
    acc.pending += p.pending;
    acc.failed += p.failed;
    acc.today_errors += p.today_errors;
    acc.storage_mb += p.storage_mb;
    return acc;
  }, { published: 0, today_published: 0, pending: 0, failed: 0, today_errors: 0, storage_mb: 0 });

  container.innerHTML = `
    <div class="allstats-summary">
      <div class="allstats-sum-card"><div class="allstats-sum-label">Всего опубл.</div><div class="allstats-sum-val">${totals.published}</div></div>
      <div class="allstats-sum-card"><div class="allstats-sum-label">Сегодня</div><div class="allstats-sum-val allstats-today">${totals.today_published}</div></div>
      <div class="allstats-sum-card"><div class="allstats-sum-label">В очереди</div><div class="allstats-sum-val">${totals.pending}</div></div>
      <div class="allstats-sum-card"><div class="allstats-sum-label">Ошибок всего</div><div class="allstats-sum-val ${totals.failed > 0 ? 'allstats-error' : ''}">${totals.failed}</div></div>
      <div class="allstats-sum-card"><div class="allstats-sum-label">Хранилище</div><div class="allstats-sum-val">${totals.storage_mb.toFixed(1)} МБ</div></div>
    </div>
    <div class="allstats-table-wrap">
      <table class="allstats-table">
        <thead>
          <tr>
            <th>Профиль</th><th>Опубл. всего</th><th>Сегодня</th><th>В очереди</th>
            <th>Ошибок</th><th>Ошибок сегодня</th><th>Хранилище</th><th>Последняя публ.</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}
