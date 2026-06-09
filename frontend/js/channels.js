// Профили и источники

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
  const configuredCount = state.config?.publishing_settings?.posts_to_publish || 50;
  const quickCount = Math.max(1, Math.min(50, num('quickPublishCount') || configuredCount));
  await post('/publish/start', { count: quickCount }, 'Публикация запущена');
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
