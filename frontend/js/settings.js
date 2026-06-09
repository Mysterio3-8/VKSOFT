// Настройки, токены, медиа

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
  setChecked('checkDuplicates', false);
  if ($('checkDuplicates')) $('checkDuplicates').disabled = true;
  setValue('postsToPublish', pub.posts_to_publish || 50);
  setValue('publishDelayMin', pub.publish_delay_min ?? 7200);
  setValue('publishDelayMax', pub.publish_delay_max ?? 10800);
  setChecked('postponedEnabled', pub.postponed_enabled !== false);
  setChecked('publishHoursEnabled', pub.publish_hours_enabled !== false);
  setValue('publishStart', pub.publish_hours_start ?? 8);
  setValue('publishEnd', pub.publish_hours_end ?? 22);
  setValue('publishTimezone', pub.timezone || 'Europe/Moscow');
  setValue('maxPostsPerDay', pub.max_posts_per_day ?? 4);
  setChecked('smartScheduleEnabled', pub.smart_schedule_enabled !== false);
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

  const wm = cfg.watermark || {};
  setChecked('wmEnabled', wm.enabled);
  setValue('wmMode', wm.mode || 'text');
  setValue('wmPosition', wm.position || 'bottom_right');
  setValue('wmText', wm.text || '');
  setValue('wmFontSize', wm.font_size || 0);
  setValue('wmOpacity', wm.opacity ?? 230);
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
  const hex = val('wmColor') || '#ffffff';
  const r = parseInt(hex.slice(1, 3), 16) || 255;
  const g = parseInt(hex.slice(3, 5), 16) || 255;
  const b = parseInt(hex.slice(5, 7), 16) || 255;
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
      check_duplicates: false,
    },
    publishing_settings: {
      posts_to_publish: num('postsToPublish') || 50,
      publish_delay_min: num('publishDelayMin') || 7200,
      publish_delay_max: num('publishDelayMax') || 10800,
      postponed_enabled: checked('postponedEnabled'),
      publish_hours_enabled: checked('publishHoursEnabled'),
      publish_hours_start: num('publishStart'),
      publish_hours_end: num('publishEnd'),
      timezone: val('publishTimezone') || 'Europe/Moscow',
      max_posts_per_day: num('maxPostsPerDay') || 4,
      smart_schedule_enabled: checked('smartScheduleEnabled'),
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
    watermark: {
      enabled: checked('wmEnabled'),
      mode: val('wmMode') || 'text',
      text: val('wmText') || '@channel',
      logo_path: val('wmLogoPath') || '',
      position: val('wmPosition') || 'bottom_right',
      font_size: num('wmFontSize') || 0,
      opacity: num('wmOpacity') ?? 180,
      color: [r, g, b],
      logo_scale: parseFloat(val('wmLogoScale') || '0.12'),
    },
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

async function savePastedToken() {
  const value = val('tokenPasteInput').trim();
  if (!value) return notify('Вставь токен или URL', 'error');
  await post('/tokens/parse', { kind: val('tokenKind'), value, save: true }, 'Токен сохранен');
  setValue('tokenPasteInput', '');
}

async function validateTokens() {
  await post('/tokens/validate', {}, 'Токены проверены');
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
