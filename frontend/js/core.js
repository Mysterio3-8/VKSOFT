// Глобальное состояние и утилиты

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
  monitor: 'Мониторинг',
  allstats: 'Все каналы',
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
  return ['Ð', 'Ñ', 'вЂ', 'В«', 'В»', 'рџ'].some(token => value.includes(token));
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

const showToast = notify;

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

function toggleAccordion(bodyId, headerEl) {
  const body = $(bodyId);
  if (!body) return;
  const open = body.style.display !== 'none';
  body.style.display = open ? 'none' : 'block';
  const chevron = headerEl.querySelector('.accordion-chevron');
  if (chevron) chevron.textContent = open ? '▼' : '▲';
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
