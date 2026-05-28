const API = 'http://localhost:8000/api';

const state = {
  config: null,
  profiles: [],
  activeProfile: null,
  monitor: null,
};

const titles = {
  dashboard: 'Дашборд',
  channels: 'Каналы',
  settings: 'Настройки',
  media: 'Медиа',
  growth: 'Рост',
  monitor: 'Новости',
  library: 'Библиотека',
  logs: 'Логи',
};

const $ = id => document.getElementById(id);
const val = id => $(id)?.value ?? '';
const num = id => Number(val(id) || 0);
const checked = id => !!$(id)?.checked;
const setValue = (id, value) => { const el = $(id); if (el) el.value = value ?? ''; };
const setChecked = (id, value) => { const el = $(id); if (el) el.checked = !!value; };
const esc = value => String(value ?? '').replace(/[&<>"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char]));

function looksBroken(text) {
  return /Р.|С.|вЂ|вњ|в”|РЃ|Рђ|Р±|РЅ/.test(String(text || ''));
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
    notify('Нет соединения с backend', 'error');
    return { status: 'error', message: String(error) };
  }
}

async function del(path, okText = 'Удалено') {
  try {
    const result = await api(path, { method: 'DELETE' });
    notify(message(result, okText), result.status === 'error' ? 'error' : 'success');
    await refreshAll(true);
  } catch {
    notify('Не удалось удалить', 'error');
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
  if (tab === 'channels') { renderProfiles(); renderSources(); }
  if (tab === 'settings') renderSettings();
  if (tab === 'media') { renderMediaSettings(); loadMediaStatus(); }
  if (tab === 'growth') loadGrowth();
  if (tab === 'monitor') loadMonitor();
  if (tab === 'library') loadLibrary();
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
  if (state.activeProfile) {
    $('profileName').textContent = state.activeProfile.name || 'Канал';
    $('profileDot').style.background = state.activeProfile.color || '#7c3aed';
  }
}

async function loadConfig() {
  state.config = await api('/config/get');
}

async function loadDashboard() {
  const data = await api('/dashboard');
  $('statPending').textContent = data.pending ?? 0;
  $('statPublished').textContent = data.published_total ?? 0;
  $('statToday').textContent = data.published_today ?? 0;
  $('statErrors').textContent = data.errors_today ?? 0;
  $('statErrorsCard').classList.toggle('has-errors', Number(data.errors_today || 0) > 0);
  setHealth('healthDownload', data.is_downloading);
  setHealth('healthPublish', data.is_publishing);
  setHealth('healthMonitor', data.is_monitoring);
  $('healthLastSched').textContent = data.last_scheduled || '-';
  renderChart(data.chart_data || []);
  const busy = data.is_downloading || data.is_publishing || data.is_monitoring;
  $('statusDot').classList.toggle('busy', !!busy);
  $('statusText').textContent = busy ? 'Работает' : 'Готов';
  await loadDownloadProgress();
  await loadPending();
  await loadLastScheduled();
}

function setHealth(id, enabled) {
  const el = $(id);
  el.classList.toggle('ok', !!enabled);
  el.querySelector('b').textContent = enabled ? 'идет' : 'нет';
}

function renderChart(items) {
  const max = Math.max(1, ...items.map(item => Number(item.published || 0) + Number(item.errors || 0)));
  $('activityChart').innerHTML = items.map(item => {
    const value = Number(item.published || 0);
    const errors = Number(item.errors || 0);
    const height = Math.max(4, Math.round(((value + errors) / max) * 72));
    return `<div class="chart-bar-wrap"><div class="chart-bar ${errors ? 'has-errors' : ''}" style="height:${height}px" data-tip="${esc(item.label)}: ${value} / ошибок ${errors}"></div><div class="chart-label">${esc(item.label)}</div></div>`;
  }).join('');
}

async function loadDownloadProgress() {
  const data = await api('/download/progress').catch(() => ({}));
  $('downloadProgressBar').style.width = `${data.percent || 0}%`;
  $('downloadProgressText').textContent = data.total ? `${data.current || 0} из ${data.total} (${data.percent || 0}%), источник: ${data.source || '-'}` : 'Сейчас загрузка не идет';
}

async function loadPending() {
  const data = await api('/posts/pending').catch(() => ({ posts: [], count: 0 }));
  const posts = data.posts || [];
  if (!posts.length) {
    $('pendingList').innerHTML = '<div class="empty"><div class="empty-text">Очередь пустая</div></div>';
    return;
  }
  $('pendingList').innerHTML = `<div class="posts-count">Всего в очереди: ${data.count || posts.length}</div>` + posts.slice(0, 8).map(post => `
    <div class="post-preview">
      <div class="post-preview-text">${esc(post.text || 'Без текста')}</div>
      <div class="post-preview-meta"><span>ID: ${esc(post.id)}</span><span>${esc(post.date)}</span><span>Фото: ${post.photo_count || 0}</span></div>
    </div>`).join('');
}

async function loadLastScheduled() {
  const data = await api('/publish/last_scheduled').catch(() => ({}));
  setValue('lastScheduledInput', data.datetime || '');
}

function renderProfiles() {
  const list = $('profilesList');
  if (!state.profiles.length) {
    list.innerHTML = '<div class="empty"><div class="empty-text">Каналов пока нет</div></div>';
    return;
  }
  list.innerHTML = state.profiles.map(profile => `
    <div class="channel-card ${profile.active ? 'active' : ''}">
      <div class="channel-avatar" style="background:${esc(profile.color || '#7c3aed')}">${esc((profile.name || 'K').slice(0, 1).toUpperCase())}</div>
      <div class="channel-info">
        <div class="channel-name">${esc(profile.name || profile.id)}</div>
        <div class="channel-meta">${esc(profile.id)} / очередь: ${profile.pending || 0}</div>
      </div>
      <div class="channel-actions">
        <button class="btn btn-secondary btn-sm" onclick="switchProfile('${esc(profile.id)}')">Открыть</button>
        <button class="btn btn-danger btn-sm" onclick="deleteProfile('${esc(profile.id)}')">Удалить</button>
      </div>
    </div>`).join('');
}

async function createProfile() {
  await post('/profiles/create', { name: val('profileNewName'), color: val('profileNewColor') }, 'Канал создан');
  setValue('profileNewName', '');
}

async function switchProfile(id) {
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
        <button class="btn btn-secondary btn-sm" onclick="downloadOne('${esc(source.community_id)}')">Скачать</button>
        <button class="btn btn-danger btn-sm" onclick="removeSource(${Number(source.id)})">Удалить</button>
      </div>
    </div>`).join('');
}

async function addSource() {
  await post('/sources/add', { name: val('sourceName'), community_id: val('sourceCommunityId') }, 'Источник добавлен');
  setValue('sourceName', '');
  setValue('sourceCommunityId', '');
}

async function removeSource(id) {
  await post('/sources/remove', { id }, 'Источник удален');
}

async function downloadOne(community_id) {
  await post('/download/start', { community_id, count: state.config?.download_settings?.posts_to_download || 100 }, 'Загрузка источника запущена');
}

function renderSettings() {
  const cfg = state.config || {};
  const vk = cfg.vk || {};
  const dl = cfg.download_settings || {};
  const pub = cfg.publishing_settings || {};
  const processing = cfg.processing || {};
  const filters = cfg.filters || {};
  const ollama = cfg.ollama || {};

  setValue('userToken', vk.user_token || '');
  setValue('groupToken', vk.group_token || '');
  setValue('groupId', vk.group_id || '');
  setValue('apiVersion', vk.api_version || '5.131');
  setValue('postsToDownload', dl.posts_to_download || 100);
  setValue('downloadDelayMin', dl.delay_min ?? 2);
  setValue('downloadDelayMax', dl.delay_max ?? 5);
  setChecked('checkDuplicates', dl.check_duplicates);
  setValue('postsToPublish', pub.posts_to_publish || 50);
  setValue('publishDelayMin', pub.publish_delay_min ?? 7200);
  setValue('publishDelayMax', pub.publish_delay_max ?? 10800);
  setChecked('postponedEnabled', pub.postponed_enabled);
  setChecked('publishHoursEnabled', pub.publish_hours_enabled);
  setValue('publishStart', pub.publish_hours_start ?? 8);
  setValue('publishEnd', pub.publish_hours_end ?? 22);
  setValue('hashtags', (processing.hashtags || []).join(' '));
  setChecked('photoOnly', processing.photo_only);
  setChecked('allowVideo', processing.allow_video);
  setChecked('filtersEnabled', filters.enable_auto_filters);
  setValue('blockKeywords', (filters.block_keywords || []).join(', '));
  setValue('minContentLength', filters.min_content_length || 0);
  setChecked('ollamaEnabled', ollama.enabled);
  setValue('ollamaUrl', ollama.url || 'http://localhost:11434');
  setValue('ollamaModel', ollama.model || 'llama3.2:3b');
  setValue('ollamaWordsMin', ollama.target_words_min || 50);
  setValue('ollamaWordsMax', ollama.target_words_max || 80);
}

function collectSettings() {
  return {
    vk: {
      user_token: val('userToken'),
      group_token: val('groupToken'),
      group_id: val('groupId'),
      api_version: val('apiVersion') || '5.131',
    },
    download_settings: {
      posts_to_download: num('postsToDownload'),
      delay_min: num('downloadDelayMin'),
      delay_max: num('downloadDelayMax'),
      check_duplicates: checked('checkDuplicates'),
    },
    publishing_settings: {
      posts_to_publish: num('postsToPublish'),
      publish_delay_min: num('publishDelayMin'),
      publish_delay_max: num('publishDelayMax'),
      postponed_enabled: checked('postponedEnabled'),
      publish_hours_enabled: checked('publishHoursEnabled'),
      publish_hours_start: num('publishStart'),
      publish_hours_end: num('publishEnd'),
    },
    processing: {
      add_hashtags: val('hashtags').trim().length > 0,
      hashtags: val('hashtags').split(/\s+/).filter(Boolean),
      photo_only: checked('photoOnly'),
      allow_video: checked('allowVideo'),
    },
    filters: {
      enable_auto_filters: checked('filtersEnabled'),
      block_keywords: val('blockKeywords').split(',').map(x => x.trim()).filter(Boolean),
      min_content_length: num('minContentLength'),
    },
    ollama: {
      enabled: checked('ollamaEnabled'),
      url: val('ollamaUrl'),
      model: val('ollamaModel'),
      target_words_min: num('ollamaWordsMin'),
      target_words_max: num('ollamaWordsMax'),
    },
  };
}

async function saveSettings() {
  await post('/config/save', collectSettings(), 'Настройки сохранены');
}

async function validateVk() {
  await post('/vk/validate', {}, 'VK токены проверены');
}

async function testOllama() {
  await post('/ollama/test', { url: val('ollamaUrl'), model: val('ollamaModel') }, 'Ollama отвечает');
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
    return `<div class="card">
      <div class="card-header"><div class="card-title"><span class="icon">VK</span>${label}</div><span class="badge ${media.is_downloading || media.is_publishing ? 'badge-warning' : 'badge-neutral'}">${media.is_downloading ? 'скачивает' : media.is_publishing ? 'публикует' : 'готово'}</span></div>
      <div class="stat-card"><div class="stat-label">Очередь</div><div class="stat-value">${media.queue || 0}</div><div class="stat-sub">${cfg.enabled === false && key === 'photos' ? 'в настройках выключено' : 'готово к работе'}</div></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
        <button class="btn btn-secondary btn-sm" onclick="post('/media/${key}/download/start', {}, 'Загрузка ${label.toLowerCase()} запущена')">Скачать</button>
        <button class="btn btn-primary btn-sm" onclick="post('/media/${key}/publish/start', {}, 'Публикация ${label.toLowerCase()} запущена')">Публиковать</button>
        <button class="btn btn-ghost btn-sm" onclick="post('/media/${key}/download/stop', {}, 'Остановлено')">Стоп</button>
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
  setChecked('videosWallPost', videos.create_wall_post);
  setValue('videosPerRun', videos.videos_per_run || 10);
  setValue('videosMaxMb', videos.max_filesize_mb || 500);
  setChecked('clipsWallPost', clips.create_wall_post);
  setValue('clipsPerRun', clips.clips_per_run || 10);
  setValue('clipsMaxSec', clips.max_duration_sec || 180);
}

async function saveMediaSettings() {
  await post('/config/save', {
    photos_settings: { enabled: checked('photosEnabled'), photos_per_run: num('photosPerRun') },
    videos_settings: { create_wall_post: checked('videosWallPost'), videos_per_run: num('videosPerRun'), max_filesize_mb: num('videosMaxMb') },
    clips_settings: { create_wall_post: checked('clipsWallPost'), clips_per_run: num('clipsPerRun'), max_duration_sec: num('clipsMaxSec') },
  }, 'Медиа настройки сохранены');
}

async function loadGrowth() {
  const tracker = await api('/growth/tracker').catch(() => ({}));
  const subscribers = await api('/growth/subscribers').catch(() => ({}));
  const phash = await api('/growth/phash_size').catch(() => ({}));
  const items = tracker.items || tracker.posts || [];
  $('growthStats').innerHTML = `
    <div class="stat-card"><div class="stat-label">Подписчики</div><div class="stat-value">${subscribers.current ?? subscribers.count ?? '-'}</div><div class="stat-sub">текущий замер</div></div>
    <div class="stat-card"><div class="stat-label">Трекинг постов</div><div class="stat-value">${Array.isArray(items) ? items.length : '-'}</div><div class="stat-sub">записей статистики</div></div>
    <div class="stat-card"><div class="stat-label">pHash база</div><div class="stat-value">${phash.size ?? phash.count ?? '-'}</div><div class="stat-sub">отпечатков картинок</div></div>
  `;
}

async function searchSources() {
  const q = val('sourceSearchQuery').trim();
  if (!q) return notify('Введи запрос', 'error');
  const data = await api(`/growth/search_sources?q=${encodeURIComponent(q)}`).catch(() => ({ items: [] }));
  const items = data.groups || data.items || data.sources || data.results || [];
  $('sourceSearchResults').innerHTML = items.length ? items.slice(0, 20).map(item => `
    <div class="source-item"><div class="source-dot"></div><div class="source-info"><div class="source-name">${esc(item.name || item.title || item.screen_name || 'Источник')}</div><div class="source-id">ID: ${esc(item.id || item.community_id || '-')} / подписчики: ${esc(item.members || '-')}</div></div></div>
  `).join('') : '<div class="empty"><div class="empty-text">Ничего не найдено</div></div>';
}

async function loadMonitor() {
  const status = await api('/monitor/status').catch(() => ({}));
  state.monitor = status;
  $('monitorStatus').innerHTML = `
    <div class="stat-card"><div class="stat-label">Статус</div><div class="stat-value" style="font-size:22px">${status.is_monitoring ? 'Работает' : 'Остановлен'}</div><div class="stat-sub">следующая проверка: ${esc(status.next_check || '-')}</div></div>
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

async function loadLibrary() {
  const data = await api('/library').catch(() => ({}));
  const entries = data.entries || data.library || data.templates || [];
  if (!Array.isArray(entries) || !entries.length) {
    $('libraryBlock').innerHTML = '<div class="empty"><div class="empty-text">Библиотека пустая или не загружена</div></div>';
    return;
  }
  $('libraryBlock').innerHTML = entries.slice(0, 40).map((entry, index) => `
    <div class="post-item">
      <div class="post-meta"><span class="post-id">#${index + 1}</span><button class="btn btn-danger btn-sm" onclick="del('/library/entry/${index}', 'Заготовка удалена')">Удалить</button></div>
      <div class="post-text">${esc(entry.title || entry.text || entry.content || JSON.stringify(entry).slice(0, 240))}</div>
    </div>`).join('');
}

async function addLibraryEntry() {
  await post('/library/entry/add', { text: val('libraryEntryText') }, 'Заготовка добавлена');
  setValue('libraryEntryText', '');
}

async function loadLogs() {
  const data = await api('/logs').catch(() => ({ logs: [] }));
  renderLog('logsList', data.logs || []);
}

function renderLog(id, logs) {
  const el = $(id);
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
    if (keepTab && active !== 'dashboard') switchTab(active);
  } catch (error) {
    notify('Backend не отвечает', 'error');
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  document.querySelectorAll('.nav-item').forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
  document.querySelectorAll('.settings-tab').forEach(btn => btn.addEventListener('click', () => switchSettings(btn.dataset.settings)));
  $('profileSwitcher').addEventListener('click', () => switchTab('channels'));
  await refreshAll();
  setInterval(() => loadDashboard().catch(() => {}), 7000);
  setInterval(() => {
    const active = document.querySelector('.tab-content.active')?.id;
    if (active === 'logs') loadLogs().catch(() => {});
    if (active === 'monitor') loadMonitor().catch(() => {});
  }, 12000);
});
