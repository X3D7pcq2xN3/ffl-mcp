const api = (typeof browser !== 'undefined') ? browser : chrome;
const url = document.getElementById('url');
const token = document.getElementById('token');
const saved = document.getElementById('saved');

api.storage.local.get(['webAppUrl', 'token']).then((c) => {
  url.value = c.webAppUrl || '';
  token.value = c.token || '';
});

document.getElementById('save').addEventListener('click', () => {
  api.storage.local.set({ webAppUrl: url.value.trim(), token: token.value.trim() }).then(() => {
    saved.textContent = 'saved';
    setTimeout(() => (saved.textContent = ''), 1500);
  });
});
