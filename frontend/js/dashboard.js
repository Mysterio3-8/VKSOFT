// Дашборд и прогресс

async function loadProfiles() {
  const data = await api('/profiles');
  state.profiles = data.profiles || [];
  state.activeProfile = state.profiles.find(profile => profile.active) || state.profiles[0] || null;
  renderProfileSwitcher();
}

function renderProfileSwitcher() {
  const dot = $('profileDot');
  if (!state.activeProfile) {
    setText('profileName', 'Канал не выбран');
    if (dot) dot.style.background = '#9ca3af';
    setHtml('profileDropdown', '<div class="profile-dropdown-empty">Каналов нет</div>');
    return;
  }
  setText('profileName', state.activeProfile.name || 'Канал');
  if (dot) dot.style.background = '#7c3aed';
  setHtml('profileDropdown', state.profiles.map(profile => `
    <button class="profile-option ${profile.active ? 'active' : ''}" type="button" onclick="switchProfile('${escAttr(profile.id)}')">
      <span>${esc(profile.name || profile.id)}</span>
      <small>ID: ${esc(profile.group_id || profile.vk?.group_id || '-')}</small>
    </button>
  `).join('') + '<button class="profile-option add" type="button" onclick="switchTab(\'channels\')">+ Добавить канал</button>');
}

async function loadConfig() {
  state.config = await api('/config/get');
}

async function loadDashboard() {
  const growthData = await api('/dashboard/growth').catch(() => null);
  const data = growthData?.dashboard || await api('/dashboard');
  state.dashboard = data;
  if (growthData?.status === 'ok') state.dashboardGrowth = growthData;
  setText('statToday', data.published_today ?? 0);
  setText('statErrors', data.errors_today ?? 0);
  $('statErrorsCard')?.classList.toggle('has-errors', Number(data.errors_today || 0) > 0);
  const busy = data.is_downloading || data.is_publishing;
  $('statusDot')?.classList.toggle('busy', !!busy);
  setText('statusText', busy ? 'Работает' : 'Готов');
  if (growthData?.status === 'ok') renderDashboardGrowth(growthData);
  else await loadDashboardGrowth();
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

  setText('dashGaChannel', profile.name || profile.id || '-');
  setText('dashGaGroup', `VK ID: ${profile.group_id || '-'}`);
  setText('dashGaMembers', subscribers.members ?? subscribers.current ?? 0);
  setText('dashGaMembersDiff', `сегодня: ${subscribers.diff_today ?? 0}, неделя: ${subscribers.diff_week ?? 0}`);
  setText('dashGaViews', tracker.avg_views ?? 0);
  setText('dashGaLikes', `лайки: ${tracker.avg_likes ?? 0}, проверено: ${tracker.checked ?? 0}`);
  if (data.phash_size != null) setText('dashGaPhash', `pHash: ${data.phash_size}`);
  // dashGaCycle обновляет apRefreshLoops (autopilot.js) — циклы по типам медиа
  setText('dashGaQueue', `сегодня: ${dashboard.published_today ?? 0}`);
  setText('dashGaQueue2', dashboard.pending ?? 0);

  if (!val('gaSingleSourceId')) setValue('gaSingleSourceId', settings.single_source_id || '');
  if (!val('gaHorizonDays')) setValue('gaHorizonDays', settings.horizon_days || 2);
  if (!val('gaPostsPerDay')) setValue('gaPostsPerDay', settings.posts_per_day || 12);
  if (!val('gaMinScore')) setValue('gaMinScore', settings.min_viral_score ?? 30);
  if (settings.source_mode) setValue('gaSourceMode', settings.source_mode);

  if (cycle.running) {
    setText('gaStatusText', cycle.message || cycle.phase || 'Цикл работает...');
  } else if (cycle.phase === 'done') {
    setText('gaStatusText', cycle.message || 'Цикл завершён');
  } else {
    setText('gaStatusText', 'Автопилот готов.');
  }
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
