const API = `${window.location.origin}/api`;

const state = {
  config: null,
  profiles: [],
  activeProfile: null,
  dashboard: null,
  dashboardGrowth: null,
  library: null,
  autopilot: null,
  tokens: null,
};

const titles = {
  dashboard: 'Дашборд',
  channels: 'Каналы',
  settings: 'Настройки',
  media: 'Медиа',
  library: 'Библиотека',
  monitor: 'Новости',
  allstats: 'Все профили',
  logs: 'Логи',
};

const $ = id => document.getElementById(id);
const val = id => $(id)?.value ?? '';
const num = id => Number(val(id) || 0);
const checked = id => !!$(id)?.checked;
const setValue = (id, value) => { const el = $(id); if (el) el.value = value ?? ''; };
const setChecked = (id, value) => { const el = $(id); if (el) el.checked = !!value; };
const esc = value => String(value ?? '').replace(/[&<>"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char]));
const escAttr = value => String(value ?? '').replace(/[&<>"'\\]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '\\': '\\\\' }[char]));

function looksBroken(text) {
  const value = String(text || '');
  return [
    '\u00d0',
    '\u00d1',
    '\u0432\u0402',
    '\u0412\u00ab',
    '\u0412\u00bb',
    '\u0440\u045f',
  ].some(token => value.includes(token));
}

function message(data, fallback) {
  if (data && data.message && !looksBroken(data.message)) return data.message;
  return fallback || (data?.status === 'error' ? 'Ошибка' : 'Готово');
}

async function api(path, opts = {}) {
  const response = await fetch(API + path, opts);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

async function post(path, data = {}, okText = 'Готово') {
  try {
    const result = await api(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    notify(message(result, result.status === 'error' ? 'Ошибка' : okText), result.status === 'error' ? 'error' : 'success');
    await refreshAll(true);
    return result;
  } catch (error) {
    notify(`Backend не отвечает: ${error.message}`, 'error');
    return { status: 'error', message: String(error) };
  }
}

async function del(path, okText = 'Удалено') {
  try {
    const result = await api(path, { method: 'DELETE' });
    notify(message(result, okText), result.status === 'error' ? 'error' : 'success');
    await refreshAll(true);
  } catch (error) {
    notify(`Не удалось удалить: ${error.message}`, 'error');
  }
}

function notify(text, type = 'info') {
  const old = document.querySelector('.toast');
  if (old) old.remove();
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = text;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

function switchTab(tab) {
  document.querySelectorAll('.nav-item').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === tab));
  document.querySelectorAll('.tab-content').forEach(section => section.classList.toggle('active', section.id === tab));
  $('topbarTitle').textContent = titles[tab] || tab;
  $('profileDropdown').classList.remove('active');
  renderActiveTab(tab);
}

function renderActiveTab(tab = document.querySelector('.tab-content.active')?.id || 'dashboard') {
  if (tab === 'channels') { renderProfiles(); renderSources(); }
  if (tab === 'settings') renderSettings();
  if (tab === 'media') { renderMediaSettings(); loadMediaStatus(); }
  if (tab === 'library') loadLibrary();
  if (tab === 'monitor') loadMonitor();
  if (tab === 'allstats') loadAllStats();
  if (tab === 'logs') loadLogs();
}

function switchSettings(panel) {
  document.querySelectorAll('.settings-tab').forEach(btn => btn.classList.toggle('active', btn.dataset.settings === panel));
  document.querySelectorAll('.settings-panel').forEach(el => el.classList.toggle('active', el.id === `settings-${panel}`));
}

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
  $('dashGaQueue').textContent = `очередь: ${dashboard.pending ?? 0}, сегодня: ${dashboard.published_today ?? 0}`;

  if (!val('gaSingleSourceId')) setValue('gaSingleSourceId', settings.single_source_id || '');
  if (!val('gaHorizonDays')) setValue('gaHorizonDays', settings.horizon_days || 2);
  if (!val('gaPostsPerDay')) setValue('gaPostsPerDay', settings.posts_per_day || 12);
  if (!val('gaMinScore')) setValue('gaMinScore', settings.min_viral_score ?? 30);
  if (settings.source_mode) setValue('gaSourceMode', settings.source_mode);

  $('gaStatusText').textContent = cycle.running
    ? `Цикл запущен: ${cycle.message || cycle.phase || 'работает'}`
    : `Последний план: ${summary.candidate_count ?? 0} кандидатов, ${summary.scheduled_preview ?? 0} запланировано`;
}

function setHealth(id, enabled) {
  const el = $(id);
  if (!el) return;
  el.classList.toggle('ok', !!enabled);
  el.querySelector('b').textContent = enabled ? 'идет' : 'нет';
}

async function loadDownloadProgress() {
  const data = await api('/download/progress').catch(() => ({}));
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

function renderProfiles() {
  const list = $('profilesList');
  if (!state.profiles.length) {
    list.innerHTML = '<div class="empty"><div class="empty-text">Каналов пока нет</div></div>';
    return;
  }
  list.innerHTML = state.profiles.map(profile => {
    const gid = profile.group_id || profile.vk?.group_id || '';
    return `
      <div class="channel-card ${profile.active ? 'active' : ''}">
        <div class="channel-avatar">VK</div>
        <div class="channel-info">
          <div class="form-row">
            <input class="form-input" id="profileName_${escAttr(profile.id)}" value="${escAttr(profile.name || '')}" placeholder="Название">
            <input class="form-input" id="profileGroup_${escAttr(profile.id)}" value="${escAttr(gid)}" placeholder="ID канала">
          </div>
          <div class="channel-meta">Очередь: ${profile.pending || 0}</div>
        </div>
        <div class="channel-actions">
          <button class="btn btn-secondary btn-sm" onclick="switchProfile('${escAttr(profile.id)}')">Выбрать</button>
          <button class="btn btn-primary btn-sm" onclick="updateProfile('${escAttr(profile.id)}')">Сохранить</button>
          <button class="btn btn-danger btn-sm" onclick="deleteProfile('${escAttr(profile.id)}')">Удалить</button>
        </div>
      </div>`;
  }).join('');
}

async function createProfile() {
  await post('/profiles/create', { name: val('profileNewName'), group_id: val('profileNewGroupId') }, 'Канал создан');
  setValue('profileNewName', '');
  setValue('profileNewGroupId', '');
}

async function updateProfile(id) {
  await post('/profiles/update', {
    id,
    name: val(`profileName_${id}`),
    group_id: val(`profileGroup_${id}`),
  }, 'Канал сохранен');
}

async function switchProfile(id) {
  $('profileDropdown').classList.remove('active');
  await post('/profiles/switch', { id }, 'Канал переключен');
}

async function deleteProfile(id) {
  await del(`/profiles/${encodeURIComponent(id)}`, 'Канал удален');
}

function renderSources() {
  const list = $('sourcesList');
  const sources = state.config?.sources || [];
  if (!sources.length) {
    list.innerHTML = '<div class="empty"><div class="empty-text">Источников пока нет. Добавь VK community ID.</div></div>';
    return;
  }
  list.innerHTML = sources.map(source => `
    <div class="source-item">
      <div class="source-dot ${source.enabled ? '' : 'off'}"></div>
      <div class="source-info"><div class="source-name">${esc(source.name)}</div><div class="source-id">ID: ${esc(source.community_id)}</div></div>
      <div class="source-btns">
        <button class="btn btn-secondary btn-sm" onclick="downloadOne('${escAttr(source.community_id)}')">Скачать</button>
        <button class="btn btn-danger btn-sm" onclick="removeSource(${Number(source.id)})">Удалить</button>
      </div>
    </div>`).join('');
}

async function addSource() {
  await post('/sources/add', { name: val('sourceName'), community_id: val('sourceCommunityId') }, 'Источник добавлен');
  setValue('sourceName', '');
  setValue('sourceCommunityId', '');
}

async function addSourceDirect(name, community_id) {
  await post('/sources/add', { name, community_id }, 'Источник добавлен');
}

async function removeSource(id) {
  await post('/sources/remove', { id }, 'Источник удален');
}

async function downloadOne(community_id) {
  closeDownloadMenu();
  await post('/download/start', { community_id, count: state.config?.download_settings?.posts_to_download || 100 }, 'Загрузка источника запущена');
}

async function publishQueue() {
  await post('/publish/start', { count: state.config?.publishing_settings?.posts_to_publish || 50 }, 'Публикация запущена');
}

function renderSettings() {
  const cfg = state.config || {};
  const vk = cfg.vk || {};
  const dl = cfg.download_settings || {};
  const pub = cfg.publishing_settings || {};
  const processing = cfg.processing || {};
  const filters = cfg.filters || {};
  const anti = cfg.antiplagiaat || {};
  const peak = cfg.peak_hours || {};
  const polls = cfg.polls || {};

  setValue('userToken', vk.user_token || '');
  setValue('groupToken', vk.group_token || '');
  setValue('postsToDownload', dl.posts_to_download || 100);
  setValue('downloadDelayMin', dl.delay_min ?? 3);
  setValue('downloadDelayMax', dl.delay_max ?? 6);
  setChecked('checkDuplicates', dl.check_duplicates !== false);
  setValue('postsToPublish', pub.posts_to_publish || 50);
  setValue('publishDelayMin', pub.publish_delay_min ?? 7200);
  setValue('publishDelayMax', pub.publish_delay_max ?? 10800);
  setChecked('postponedEnabled', pub.postponed_enabled !== false);
  setChecked('publishHoursEnabled', pub.publish_hours_enabled !== false);
  setValue('publishStart', pub.publish_hours_start ?? 8);
  setValue('publishEnd', pub.publish_hours_end ?? 22);
  setValue('hashtags', (processing.hashtags || []).join(' '));
  setChecked('photoOnly', processing.photo_only);
  setChecked('allowVideo', processing.allow_video);
  setChecked('clearOriginalText', anti.clear_text !== false);
  setValue('antiMaxPhotos', anti.max_photos || 4);
  const tr = anti.transforms || {};
  setChecked('transformCrop', tr.crop !== false);
  setChecked('transformColor', tr.color_shift !== false);
  setChecked('transformMirror', tr.mirror !== false);
  setValue('peakHours', (peak.hours || [8, 10, 13, 17, 19, 21]).join(','));
  setChecked('filtersEnabled', filters.enable_auto_filters);
  setChecked('adStopperEnabled', filters.ad_stopper_enabled !== false);
  setValue('adStopKeywords', (filters.ad_stop_keywords || []).join(', '));
  setValue('blockKeywords', (filters.block_keywords || []).join(', '));
  setValue('minContentLength', filters.min_content_length || 0);
  setChecked('pollsEnabled', polls.enabled);
  setValue('pollFrequency', polls.frequency || 5);
  setChecked('pollAnonymous', polls.is_anonymous !== false);
  setChecked('pollMultiple', polls.multiple);
  loadLastScheduled();

  // Водяной знак
  const wm = cfg.watermark || {};
  setChecked('wmEnabled', wm.enabled);
  setValue('wmMode', wm.mode || 'text');
  setValue('wmPosition', wm.position || 'bottom_right');
  setValue('wmText', wm.text || '');
  setValue('wmFontSize', wm.font_size || 0);
  setValue('wmOpacity', wm.opacity ?? 180);
  const wmColorArr = wm.color || [255, 255, 255];
  const wmHex = '#' + wmColorArr.map(v => v.toString(16).padStart(2, '0')).join('');
  setValue('wmColor', wmHex);
  setValue('wmLogoPath', wm.logo_path || '');
  setValue('wmLogoScale', wm.logo_scale ?? 0.12);
  toggleWmMode(wm.mode || 'text');

}

function collectSettings() {
  const hashtags = val('hashtags').split(/\s+/).filter(Boolean);
  const peakHours = val('peakHours').split(/[,\s]+/).map(x => Number(x)).filter(x => x >= 0 && x <= 23);
  return {
    vk: {
      user_token: val('userToken'),
      group_token: val('groupToken'),
      api_version: '5.131',
    },
    download_settings: {
      posts_to_download: num('postsToDownload') || 100,
      delay_min: num('downloadDelayMin'),
      delay_max: num('downloadDelayMax'),
      check_duplicates: checked('checkDuplicates'),
    },
    publishing_settings: {
      posts_to_publish: num('postsToPublish') || 50,
      publish_delay_min: num('publishDelayMin') || 7200,
      publish_delay_max: num('publishDelayMax') || 10800,
      postponed_enabled: checked('postponedEnabled'),
      publish_hours_enabled: checked('publishHoursEnabled'),
      publish_hours_start: num('publishStart'),
      publish_hours_end: num('publishEnd'),
    },
    processing: {
      add_hashtags: hashtags.length > 0,
      hashtags,
      photo_only: checked('photoOnly'),
      allow_video: checked('allowVideo'),
    },
    filters: {
      enable_auto_filters: checked('filtersEnabled'),
      ad_stopper_enabled: checked('adStopperEnabled'),
      ad_stop_keywords: val('adStopKeywords').split(',').map(x => x.trim()).filter(Boolean),
      block_keywords: val('blockKeywords').split(',').map(x => x.trim()).filter(Boolean),
      min_content_length: num('minContentLength'),
    },
    antiplagiaat: {
      enabled: true,
      clear_text: checked('clearOriginalText'),
      max_photos: Math.max(1, num('antiMaxPhotos') || 4),
      remove_photo: 'random',
      transforms: {
        crop: checked('transformCrop'),
        color_shift: checked('transformColor'),
        mirror: checked('transformMirror'),
      },
    },
    peak_hours: {
      enabled: true,
      hours: peakHours.length ? peakHours : [8, 10, 13, 17, 19, 21],
    },
    watermark: (() => {
      const hex = val('wmColor') || '#ffffff';
      const r = parseInt(hex.slice(1,3), 16) || 255;
      const g = parseInt(hex.slice(3,5), 16) || 255;
      const b = parseInt(hex.slice(5,7), 16) || 255;
      return {
        enabled: checked('wmEnabled'),
        mode: val('wmMode') || 'text',
        text: val('wmText') || '@channel',
        logo_path: val('wmLogoPath') || '',
        position: val('wmPosition') || 'bottom_right',
        font_size: num('wmFontSize') || 0,
        opacity: num('wmOpacity') ?? 180,
        color: [r, g, b],
        logo_scale: parseFloat(val('wmLogoScale') || '0.12'),
      };
    })(),
    polls: {
      enabled: checked('pollsEnabled'),
      frequency: Math.max(1, num('pollFrequency') || 5),
      is_anonymous: checked('pollAnonymous'),
      multiple: checked('pollMultiple'),
    },
  };
}

function toggleWmMode(mode) {
  const textBlock = document.getElementById('wmTextBlock');
  const logoBlock = document.getElementById('wmLogoBlock');
  if (!textBlock || !logoBlock) return;
  textBlock.style.display = (mode === 'text') ? '' : 'none';
  logoBlock.style.display = (mode === 'logo') ? '' : 'none';
}

document.addEventListener('change', function(e) {
  if (e.target && e.target.id === 'wmMode') toggleWmMode(e.target.value);
});

async function saveSettings() {
  await post('/config/save', collectSettings(), 'Настройки сохранены');
}

async function validateVk() {
  await post('/vk/validate', {}, 'VK токены проверены');
}

async function loadLastScheduled() {
  const data = await api('/publish/last_scheduled').catch(() => ({}));
  setValue('lastScheduledInput', data.datetime || '');
}

async function saveLastScheduled() {
  await post('/publish/last_scheduled', { datetime: val('lastScheduledInput') }, 'Время сохранено');
}

async function loadMediaStatus() {
  const data = await api('/media/status').catch(() => ({}));
  const types = [
    ['photos', 'Фото', 'photos_settings'],
    ['videos', 'Видео', 'videos_settings'],
    ['clips', 'Клипы', 'clips_settings'],
  ];
  $('mediaCards').innerHTML = types.map(([key, label, settingsKey]) => {
    const media = data[key] || {};
    const cfg = state.config?.[settingsKey] || {};
    const busy = media.is_downloading || media.is_publishing;
    return `<div class="card">
      <div class="card-header"><div class="card-title"><span class="icon">VK</span>${label}</div><span class="badge ${busy ? 'badge-warning' : 'badge-neutral'}">${media.is_downloading ? 'скачивает' : media.is_publishing ? 'публикует' : 'готово'}</span></div>
      <div class="stat-card flat"><div class="stat-label">Очередь</div><div class="stat-value">${media.queue || 0}</div><div class="stat-sub">${cfg.enabled === false && key === 'photos' ? 'выключено в настройках' : 'готово к работе'}</div></div>
      <div class="button-row">
        <button class="btn btn-secondary btn-sm" onclick="post('/media/${key}/download/start', {}, 'Загрузка ${label.toLowerCase()} запущена')">Скачать</button>
        <button class="btn btn-primary btn-sm" onclick="post('/media/${key}/publish/start', {}, 'Публикация ${label.toLowerCase()} запущена')">Публиковать</button>
        <button class="btn btn-ghost btn-sm" onclick="post('/media/${key}/download/stop', {}, 'Загрузка остановлена')">Стоп загрузки</button>
        <button class="btn btn-ghost btn-sm" onclick="post('/media/${key}/publish/stop', {}, 'Публикация остановлена')">Стоп публикации</button>
      </div>
    </div>`;
  }).join('');
}

function renderMediaSettings() {
  const photos = state.config?.photos_settings || {};
  const videos = state.config?.videos_settings || {};
  const clips = state.config?.clips_settings || {};
  setChecked('photosEnabled', photos.enabled);
  setValue('photosPerRun', photos.photos_per_run || 50);
  setChecked('videosWallPost', videos.create_wall_post !== false);
  setValue('videosPerRun', videos.videos_per_run || 10);
  setValue('videosMaxMb', videos.max_filesize_mb || 500);
  setChecked('clipsWallPost', clips.create_wall_post !== false);
  setValue('clipsPerRun', clips.clips_per_run || 10);
  setValue('clipsMaxSec', clips.max_duration_sec || 180);
}

async function saveMediaSettings() {
  await post('/config/save', {
    photos_settings: { enabled: checked('photosEnabled'), photos_per_run: num('photosPerRun') || 50, publish_delay_min: 7200, publish_delay_max: 10800, create_wall_post: true },
    videos_settings: { enabled: true, create_wall_post: checked('videosWallPost'), videos_per_run: num('videosPerRun') || 10, max_filesize_mb: num('videosMaxMb') || 500 },
    clips_settings: { enabled: true, create_wall_post: checked('clipsWallPost'), clips_per_run: num('clipsPerRun') || 10, max_duration_sec: num('clipsMaxSec') || 180 },
  }, 'Медиа настройки сохранены');
}

async function loadGrowth() {
  const phash = await api('/growth/phash_size').catch(() => ({}));
  if ($('dashGaPhash')) $('dashGaPhash').textContent = `pHash: ${phash.size ?? 0}`;
}

function tokenBadgeClass(status) {
  if (status === 'ok') return 'badge-success';
  if (status === 'warning') return 'badge-warning';
  if (status === 'expired' || status === 'missing') return 'badge-error';
  return 'badge-neutral';
}

function renderTokenStatus(tokens = {}) {
  const user = tokens.user || {};
  const group = tokens.group || {};
  $('tokenStatus').innerHTML = `
    <div class="token-grid">
      <div class="token-row"><span>User</span><b>${esc(user.masked || 'не задан')}</b><span class="badge ${tokenBadgeClass(user.status)}">${esc(user.expires_label || user.status || '-')}</span></div>
      <div class="token-row"><span>Group</span><b>${esc(group.masked || 'не задан')}</b><span class="badge ${tokenBadgeClass(group.status)}">${esc(group.expires_label || group.status || '-')}</span></div>
    </div>
    <div class="form-hint">Последняя проверка: ${esc(tokens.last_check || '-')}</div>
    ${tokens.last_error ? `<div class="form-hint danger-text">${esc(tokens.last_error)}</div>` : ''}
  `;
}

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
  `).join('') : '<div class="empty"><div class="empty-text">Нажми “Собрать отчет”, чтобы увидеть кандидатов</div></div>';

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

async function savePastedToken() {
  const value = val('tokenPasteInput').trim();
  if (!value) return notify('Вставь токен или URL', 'error');
  await post('/tokens/parse', { kind: val('tokenKind'), value, save: true }, 'Токен сохранен');
  setValue('tokenPasteInput', '');
}

async function validateTokens() {
  await post('/tokens/validate', {}, 'Токены проверены');
}

async function searchSources() {
  const q = val('sourceSearchQuery').trim();
  if (!q) return notify('Введи запрос', 'error');
  const data = await api(`/growth/search_sources?q=${encodeURIComponent(q)}`).catch(() => ({ groups: [] }));
  const items = data.groups || data.items || data.sources || data.results || [];
  $('sourceSearchResults').innerHTML = items.length ? items.slice(0, 20).map(item => `
    <div class="source-item"><div class="source-dot"></div><div class="source-info"><div class="source-name">${esc(item.name || item.title || item.screen_name || 'Источник')}</div><div class="source-id">ID: ${esc(item.id || item.community_id || '-')} / подписчики: ${esc(item.members || '-')}</div></div><button class="btn btn-secondary btn-sm" onclick="addSourceDirect('${escAttr(item.name || item.title || 'Источник')}', '${escAttr(item.id || item.community_id || '')}')">Добавить</button></div>
  `).join('') : '<div class="empty"><div class="empty-text">Ничего не найдено</div></div>';
}

async function loadLibrary() {
  const [data, niches] = await Promise.all([
    api('/library').catch(() => ({})),
    api('/library/niches').catch(() => ({ niches: [] })),
  ]);
  state.library = data;
  $('libraryControls').innerHTML = `
    <label class="toggle-row"><span class="toggle-info"><span class="toggle-label">Включить библиотеку</span><span class="toggle-desc">Заменять оригинальный текст случайной заготовкой</span></span><span class="toggle"><input id="libraryEnabled" type="checkbox" ${data.enabled ? 'checked' : ''}><span class="toggle-slider"></span></span></label>
    <label class="toggle-row"><span class="toggle-info"><span class="toggle-label">CTA</span><span class="toggle-desc">Добавлять призыв к действию</span></span><span class="toggle"><input id="libraryCtaEnabled" type="checkbox" ${data.cta_enabled ? 'checked' : ''}><span class="toggle-slider"></span></span></label>
    <div class="form-row"><select class="form-input" id="libraryNiche">${(niches.niches || []).map(n => `<option value="${escAttr(n.id)}" ${n.id === data.niche ? 'selected' : ''}>${esc(n.label)} (${n.entries_count})</option>`).join('')}</select><button class="btn btn-secondary" onclick="applyLibraryNiche()">Применить нишу</button></div>
  `;
  const entries = data.entries || [];
  $('libraryBlock').innerHTML = entries.length ? entries.slice(0, 60).map((entry, index) => `
    <div class="post-item">
      <div class="post-meta"><span class="post-id">#${index + 1}</span><button class="btn btn-danger btn-sm" onclick="del('/library/entry/${index}', 'Заготовка удалена')">Удалить</button></div>
      <div class="post-text">${esc(entry.text || entry.title || JSON.stringify(entry).slice(0, 240))}</div>
      <div class="post-date">${esc(entry.tags || '')}</div>
    </div>`).join('') : '<div class="empty"><div class="empty-text">Библиотека пустая</div></div>';
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

async function addLibraryEntry() {
  await post('/library/entry/add', { text: val('libraryEntryText'), tags: val('libraryEntryTags') }, 'Заготовка добавлена');
  setValue('libraryEntryText', '');
  setValue('libraryEntryTags', '');
}

async function addLibraryPoll() {
  const answers = val('libraryPollAnswers').split(',').map(x => x.trim()).filter(Boolean);
  await post('/library/poll/add', { question: val('libraryPollQuestion'), answers }, 'Опрос добавлен');
  setValue('libraryPollQuestion', '');
  setValue('libraryPollAnswers', '');
}

async function loadMonitor() {
  const status = await api('/monitor/status').catch(() => ({}));
  $('monitorStatus').innerHTML = `
    <div class="stat-card flat"><div class="stat-label">Статус</div><div class="stat-value small">${status.is_monitoring ? 'Работает' : 'Остановлен'}</div><div class="stat-sub">следующая проверка: ${esc(status.next_check || '-')}</div></div>
  `;
  setValue('monInterval', status.check_interval || 180);
  setValue('monMaxCycle', status.max_per_cycle || 2);
  setValue('monCatchDays', status.catch_up_days || 3);
  setValue('monMinViews', status.min_views || 0);
  renderMonitorSources(status.sources || []);
  const log = await api('/monitor/log').catch(() => ({ logs: [] }));
  renderLog('monitorLogList', log.logs || []);
}

function renderMonitorSources(sources) {
  $('monitorSources').innerHTML = sources.length ? sources.map(source => `
    <div class="source-item">
      <div class="source-dot ${source.enabled === false ? 'off' : ''}"></div>
      <div class="source-info"><div class="source-name">${esc(source.name)}</div><div class="source-id">ID: ${esc(source.community_id)}</div></div>
      <div class="source-btns"><button class="btn btn-secondary btn-sm" onclick="post('/monitor/sources/toggle', {id:${Number(source.id)}}, 'Источник переключен')">Вкл/выкл</button><button class="btn btn-danger btn-sm" onclick="post('/monitor/sources/remove', {id:${Number(source.id)}}, 'Источник удален')">Удалить</button></div>
    </div>`).join('') : '<div class="empty"><div class="empty-text">Источников мониторинга нет</div></div>';
}

async function addMonitorSource() {
  await post('/monitor/sources/add', { name: val('monSourceName'), community_id: val('monSourceId') }, 'Источник мониторинга добавлен');
  setValue('monSourceName', '');
  setValue('monSourceId', '');
}

async function saveMonitorSettings() {
  await post('/monitor/settings', {
    check_interval_min: num('monInterval'),
    max_per_cycle: num('monMaxCycle'),
    catch_up_days: num('monCatchDays'),
    min_views: num('monMinViews'),
  }, 'Мониторинг сохранен');
}

async function loadLogs() {
  const data = await api('/logs').catch(() => ({ logs: [] }));
  renderLog('logsList', data.logs || []);
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

async function refreshAll(keepTab = true) {
  try {
    const active = document.querySelector('.tab-content.active')?.id || 'dashboard';
    await loadProfiles();
    await loadConfig();
    await loadDashboard();
    if (keepTab) renderActiveTab(active);
  } catch (error) {
    notify(`Backend не отвечает: ${error.message}`, 'error');
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  document.querySelectorAll('.nav-item').forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
  document.querySelectorAll('.settings-tab').forEach(btn => btn.addEventListener('click', () => switchSettings(btn.dataset.settings)));
  $('profileSwitcher').addEventListener('click', () => $('profileDropdown').classList.toggle('active'));
  document.addEventListener('click', event => {
    if (!event.target.closest('.profile-wrap')) $('profileDropdown').classList.remove('active');
  });
  await refreshAll();
  setInterval(() => loadDashboard().catch(() => {}), 5000);
  setInterval(() => {
    const active = document.querySelector('.tab-content.active')?.id;
    if (active === 'logs') loadLogs().catch(() => {});
    if (active === 'monitor') loadMonitor().catch(() => {});
    if (active === 'media') loadMediaStatus().catch(() => {});
  }, 12000);
});

// ── Logo drag-and-drop ────────────────────────────────────────────
async function uploadLogoFile(file) {
  if (!file || !file.name.toLowerCase().endsWith('.png')) {
    showToast('Только PNG файлы', 'error');
    return;
  }
  const statusEl = document.getElementById('logoUploadStatus');
  if (statusEl) { statusEl.style.display = 'block'; statusEl.textContent = 'Загружаю...'; }
  try {
    const fd = new FormData();
    fd.append('file', file);
    const resp = await fetch('/api/config/upload_logo', { method: 'POST', body: fd });
    const data = await resp.json();
    if (data.status === 'ok') {
      setValue('wmLogoPath', data.path);
      if (statusEl) statusEl.textContent = '✓ Загружено: ' + file.name;
      showToast('Логотип загружен', 'success');
    } else {
      if (statusEl) { statusEl.style.color = '#ef4444'; statusEl.textContent = data.message || 'Ошибка'; }
      showToast(data.message || 'Ошибка загрузки', 'error');
    }
  } catch (e) {
    if (statusEl) { statusEl.style.color = '#ef4444'; statusEl.textContent = 'Ошибка сети'; }
    showToast('Ошибка загрузки логотипа', 'error');
  }
}

function handleLogoDrop(event) {
  event.preventDefault();
  const zone = document.getElementById('logoDropZone');
  if (zone) zone.classList.remove('dragover');
  const file = event.dataTransfer?.files?.[0];
  if (file) uploadLogoFile(file);
}

function handleLogoFile(file) {
  if (file) uploadLogoFile(file);
}

document.addEventListener('dragover', function(e) {
  const zone = document.getElementById('logoDropZone');
  if (zone && zone.contains(e.target)) zone.classList.add('dragover');
});
document.addEventListener('dragleave', function(e) {
  const zone = document.getElementById('logoDropZone');
  if (zone && !zone.contains(e.relatedTarget)) zone.classList.remove('dragover');
});

// ── All profiles stats ────────────────────────────────────────

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
            <th>Профиль</th>
            <th>Опубл. всего</th>
            <th>Сегодня</th>
            <th>В очереди</th>
            <th>Ошибок</th>
            <th>Ошибок сегодня</th>
            <th>Хранилище</th>
            <th>Последняя публ.</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function toggleAccordion(bodyId, headerEl) {
  const body = $(bodyId);
  if (!body) return;
  const open = body.style.display !== 'none';
  body.style.display = open ? 'none' : 'block';
  const chevron = headerEl.querySelector('.accordion-chevron');
  if (chevron) chevron.textContent = open ? '▼' : '▲';
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
  $('gaStatusText').textContent = 'Запускаю цикл: скачивание и постановка постов в очередь...';
  const data = await api('/growth-autopilot/cycle/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings: gaSettings() }),
  }).catch(error => ({ status: 'error', message: error.message }));
  $('gaStatusText').textContent = data.message || (data.status === 'ok' ? 'Цикл запущен: посты будут поставлены в очередь' : 'Ошибка запуска цикла');
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
  $('gaRecommendationBlock').innerHTML = `
    <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)"><span>Постов в день</span><b>${esc(rec.posts_per_day || '-')}</b></div>
    <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)"><span>Лучшие часы</span><b>${esc((rec.hours || []).join(', '))}</b></div>
    <div class="form-hint">${esc(rec.reason || '')}</div>
    ${gaLastRecommendationPatch ? `<button class="btn btn-secondary" onclick="gaApplyRecommendation()">Применить рекомендации</button>` : ''}
  `;
  $('gaStatusText').textContent = 'Анализ готов';
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

