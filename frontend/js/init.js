// Инициализация приложения

document.addEventListener('DOMContentLoaded', async () => {
  document.querySelectorAll('.nav-item').forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
  document.querySelectorAll('.settings-tab').forEach(btn => btn.addEventListener('click', () => switchSettings(btn.dataset.settings)));
  $('profileSwitcher').addEventListener('click', () => $('profileDropdown').classList.toggle('active'));
  document.addEventListener('click', event => {
    if (!event.target.closest('.profile-wrap')) $('profileDropdown').classList.remove('active');
    if (!event.target.closest('.action-menu-wrap')) closeDownloadMenu();
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
