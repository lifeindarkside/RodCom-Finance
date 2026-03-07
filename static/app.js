// Configuration
const API_URL = '/api';

// State
let currentUser = null;
let currentTransactions = [];
let dashRecentTxs = [];
let currentPage = 1;
let totalPages = 1;
let collections = [];
let pendingDeletePhotos = [];
let existingPhotos = [];
let navSource = null; // 'dashboard' if came from dashboard, null if from menu

// DOM Elements
const screens = {
    auth: document.getElementById('auth-screen'),
    app: document.getElementById('app-screen')
};

// --- Auth ---
let authPollingInterval = null;

async function tryTelegramMiniAppAuth() {
    if (!window.Telegram || !window.Telegram.WebApp || !window.Telegram.WebApp.initData) return false;
    var tg = window.Telegram.WebApp;
    var initData = tg.initData;
    if (!initData) return false;
    try {
        var res = await fetch(API_URL + "/auth/tma", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ init_data: initData })
        });
        if (res.ok) {
            var data = await res.json();
            localStorage.setItem("token", data.token);
            tg.ready();
            tg.expand();
            return true;
        }
        return false;
    } catch (e) {
        return false;
    }
}

function loadTelegramWidget() {
    fetch(API_URL + '/config')
        .then(function(res) { return res.json(); })
        .then(function(cfg) {
            if (!cfg.bot_name) return;
            var container = document.getElementById('telegram-widget-container');
            if (!container) return;
            var script = document.createElement('script');
            script.src = 'https://telegram.org/js/telegram-widget.js?22';
            script.setAttribute('data-telegram-login', cfg.bot_name);
            script.setAttribute('data-size', 'large');
            script.setAttribute('data-radius', '10');
            script.setAttribute('data-onauth', 'onTelegramAuth(user)');
            script.setAttribute('data-request-access', 'write');
            script.async = true;
            container.appendChild(script);
        })
        .catch(function() {});
}

function initAuth() {
    document.getElementById('mobile-menu-toggle')?.addEventListener('click', () => {
        document.getElementById('sidebar').classList.add('open');
    });
    document.getElementById('sidebar-close')?.addEventListener('click', () => {
        document.getElementById('sidebar').classList.remove('open');
    });
    document.getElementById('btn-login-tg')?.addEventListener('click', startTelegramLogin);

    const urlParams = new URLSearchParams(window.location.search);
    const urlToken = urlParams.get('token');
    if (urlToken) {
        localStorage.setItem('token', urlToken);
        window.history.replaceState({}, document.title, window.location.pathname);
    }
    tryTelegramMiniAppAuth().then(function(tmaSuccess) {
        var token = localStorage.getItem('token');
        if (token) {
            checkAuth(token);
        } else if (!tmaSuccess) {
            showScreen('auth');
            loadTelegramWidget();
        }
    });
}

window.onTelegramAuth = async function (user) {
    var authCard = document.querySelector('.auth-card');
    var oldContent = authCard.innerHTML;
    authCard.innerHTML = '<div class="auth-loading"><div class="auth-spinner"></div><p>Входим...</p><p class="auth-loading-sub">Проверяем данные Telegram</p></div>';
    try {
        var params = new URLSearchParams(user);
        var res = await fetch(API_URL + '/auth/widget?' + params.toString());
        if (res.ok) {
            var data = await res.json();
            authCard.querySelector('p').textContent = 'Готово! Загружаем...';
            localStorage.setItem('token', data.token);
            checkAuth(data.token);
        } else {
            var text = await res.text();
            var detail;
            try { detail = JSON.parse(text).detail; } catch(e) { detail = text; }
            var errMsg = detail || 'Неизвестная ошибка';
            authCard.innerHTML = '<div class="auth-loading auth-error"><div class="auth-error-icon">\u26a0\ufe0f</div><p>' + errMsg + '</p><button class="btn btn-primary" onclick="window.location.reload()">Попробовать снова</button></div>';
        }
    } catch (e) {
        authCard.innerHTML = '<div class="auth-loading auth-error"><div class="auth-error-icon">\u26a0\ufe0f</div><p>Ошибка сети. Проверьте интернет.</p><button class="btn btn-primary" onclick="window.location.reload()">Попробовать снова</button></div>';
    }
};

async function startTelegramLogin() {
    const btn = document.getElementById('btn-login-tg');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = 'Ожидание...';
    try {
        const res = await fetch(API_URL + '/auth/request');
        const data = await res.json();
        window.open(data.bot_url, '_blank');
        if (authPollingInterval) clearInterval(authPollingInterval);
        authPollingInterval = setInterval(function() { pollAuthStatus(data.auth_id, btn, originalText); }, 2000);
    } catch (e) {
        btn.disabled = false;
        btn.innerHTML = originalText;
        alert('Ошибка при запросе авторизации');
    }
}

async function pollAuthStatus(authId, btn, originalText) {
    try {
        const res = await fetch(API_URL + '/auth/check/' + authId);
        const data = await res.json();
        if (data.status === 'completed') {
            clearInterval(authPollingInterval);
            localStorage.setItem('token', data.token);
            checkAuth(data.token);
        } else if (data.status === 'cancelled') {
            clearInterval(authPollingInterval);
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    } catch (e) {}
}

async function checkAuth(token) {
    try {
        const response = await fetch(API_URL + '/auth/me', {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        if (response.ok) {
            currentUser = await response.json();
            updateUserInfo();
            showScreen('app');
            loadPage('dashboard');
        } else {
            logout();
        }
    } catch (e) {
        logout();
    }
}

function logout() {
    localStorage.removeItem('token');
    currentUser = null;
    if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) {
        window.Telegram.WebApp.close();
    } else {
        showScreen('auth');
    }
}

document.getElementById('btn-logout').addEventListener('click', logout);

// --- Navigation ---
function showScreen(screenName) {
    Object.values(screens).forEach(function(el) { el.classList.remove('active'); });
    screens[screenName].classList.add('active');
}

var navLinks = document.querySelectorAll('.nav-link');
navLinks.forEach(function(link) {
    link.addEventListener('click', function(e) {
        e.preventDefault();
        loadPage(link.getAttribute('data-page'));
    });
});

function loadPage(pageName, source) {
    navLinks.forEach(function(l) { l.classList.remove('active'); });
    document.querySelector('.nav-link[data-page="' + pageName + '"]').classList.add('active');
    document.querySelectorAll('.page').forEach(function(p) { p.classList.remove('active'); });
    document.getElementById('page-' + pageName).classList.add('active');
    document.getElementById('sidebar').classList.remove('open');
    // Track navigation source for back button
    if (source) {
        navSource = source;
    } else {
        navSource = null;
    }
    // Show/hide back button on transactions page
    var backBtn = document.getElementById('btn-back-to-dash');
    if (backBtn) {
        backBtn.style.display = (pageName === 'transactions' && navSource === 'dashboard') ? 'inline-flex' : 'none';
    }
    if (pageName === 'dashboard') loadDashboard();
    if (pageName === 'transactions') loadTransactions();
    if (pageName === 'users') loadUsers();
    if (pageName === 'compliance') initCompliancePage();
    if (pageName === 'stats') loadStats();
}

function updateUserInfo() {
    document.getElementById('user-name').textContent = currentUser.name;
    document.getElementById('user-role-badge').textContent = formatRole(currentUser.role);
    var dn = document.getElementById('dropdown-name');
    var dr = document.getElementById('dropdown-role');
    if (dn) dn.textContent = currentUser.name;
    if (dr) dr.textContent = formatRole(currentUser.role);
    if (currentUser.role === 'admin') {
        document.getElementById('nav-users').style.display = 'block';
        document.getElementById('nav-stats').style.display = 'block';
    }
    if (currentUser.role === 'admin' || currentUser.role === 'treasurer') {
        document.getElementById('nav-compliance').style.display = 'block';
    }
    var canEdit = ['admin', 'treasurer'].indexOf(currentUser.role) !== -1;
    document.getElementById('btn-add-tx').style.display = canEdit ? 'inline-flex' : 'none';
}

function formatRole(role) {
    var map = { 'admin': 'Администратор', 'treasurer': 'Казначей', 'viewer': 'Наблюдатель' };
    return map[role] || role;
}

// --- API Helpers ---
async function apiCall(endpoint, options) {
    options = options || {};
    var token = localStorage.getItem('token');
    var headers = Object.assign({ 'Authorization': 'Bearer ' + token }, options.headers || {});
    var response = await fetch(API_URL + endpoint, Object.assign({}, options, { headers: headers }));
    if (response.status === 401) { logout(); throw new Error('Unauthorized'); }
    var data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Ошибка запроса');
    return data;
}

// --- Dashboard ---
var EXPENSE_COLORS = ['#7c5cfc','#60a5fa','#00d4aa','#f59e0b','#fb923c','#ff6b6b','#f472b6','#94a3b8'];
var dashShowArchive = false;
var _dashData = null;

function shortNum(n) {
    if (n >= 1000000) return (n/1000000).toFixed(1).replace(/\.0$/, '') + 'M';
    if (n >= 1000) return (n/1000).toFixed(1).replace(/\.0$/, '') + 'K';
    return n.toLocaleString();
}

function fmtMoney(n) {
    return n.toLocaleString('ru-RU') + ' \u20bd';
}

function _isArchived(c) {
    return c.income > 0 && Math.abs(c.balance) < 0.01;
}

function renderCollections(data) {
    var allColls = data.coll_balances.filter(function(c) { return !(c.income === 0 && c.expense === 0); });
    var activeCount = allColls.filter(function(c) { return !_isArchived(c); }).length;
    var archiveCount = allColls.filter(function(c) { return _isArchived(c); }).length;

    // Render toggle
    var toggleEl = document.getElementById('coll-toggle');
    if (archiveCount === 0 && !dashShowArchive) {
        toggleEl.innerHTML = '';
    } else {
        toggleEl.innerHTML =
            '<button class="coll-toggle-btn' + (!dashShowArchive ? ' active' : '') + '" data-mode="active">' +
                'Активные <span class="coll-toggle-count">' + activeCount + '</span>' +
            '</button>' +
            '<button class="coll-toggle-btn' + (dashShowArchive ? ' active' : '') + '" data-mode="archive">' +
                'Архив <span class="coll-toggle-count">' + archiveCount + '</span>' +
            '</button>';
        toggleEl.querySelectorAll('.coll-toggle-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                dashShowArchive = btn.getAttribute('data-mode') === 'archive';
                if (_dashData) renderCollections(_dashData);
            });
        });
    }

    // Filter by current mode
    var filtered = allColls.filter(function(c) {
        return dashShowArchive ? _isArchived(c) : !_isArchived(c);
    });
    var generalColls = filtered.filter(function(c) { return c.collection_type !== 'event'; });
    var eventColls = filtered.filter(function(c) { return c.collection_type === 'event'; });
    var isArch = dashShowArchive;

    // Render General Collections
    var generalGrid = document.getElementById('general-collections-grid');
    generalGrid.innerHTML = '';
    if (generalColls.length === 0) {
        generalGrid.innerHTML = '<div class="dash-empty">' + (isArch ? 'Нет завершённых периодов' : 'Нет активных периодов бюджета') + '</div>';
    } else {
        generalColls.forEach(function(c) {
            var maxInc = Math.max.apply(null, generalColls.map(function(x) { return x.income || 0; }).concat([1]));
            var pct = maxInc ? Math.min(c.income / maxInc * 100, 100) : 0;
            var spentPct = c.income ? Math.min(c.expense / c.income * 100, 100) : 0;
            var balClass = c.balance >= 0 ? 'positive' : 'negative';
            var card = document.createElement('div');
            card.className = 'budget-card' + (isArch ? ' archived' : '');
            card.setAttribute('data-cid', c.id);
            card.innerHTML =
                '<div class="budget-card-name">' + c.name + (isArch ? '<span class="archived-badge">Завершён</span>' : '') + '</div>' +
                '<div class="budget-card-balance ' + balClass + '">' + fmtMoney(c.balance) + '</div>' +
                '<div class="budget-card-stats">' +
                    '<div class="budget-card-stat income">' +
                        '<svg viewBox="0 0 16 16" fill="none" width="14" height="14"><path d="M8 12V4M5 7l3-3 3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
                        fmtMoney(c.income) +
                    '</div>' +
                    '<div class="budget-card-stat expense">' +
                        '<svg viewBox="0 0 16 16" fill="none" width="14" height="14"><path d="M8 4v8M5 9l3 3 3-3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
                        fmtMoney(c.expense) +
                    '</div>' +
                '</div>' +
                '<div class="budget-bar">' +
                    '<div class="budget-bar-fill" style="width:' + pct + '%"></div>' +
                    '<div class="budget-bar-spent" style="width:' + spentPct + '%"></div>' +
                '</div>' +
                (c.payers_count > 0 ? '<div class="budget-card-payers">' +
                    '<svg viewBox="0 0 16 16" fill="none" width="14" height="14"><circle cx="5.5" cy="5.5" r="2.5" stroke="currentColor" stroke-width="1.2"/><path d="M1 13c0-2.2 2-4 4.5-4s4.5 1.8 4.5 4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/><circle cx="11" cy="5.5" r="2" stroke="currentColor" stroke-width="1.2"/><path d="M12 9c1.7.3 3 1.5 3 4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>' +
                    c.payers_count + ' сдали' +
                '</div>' : '');
            card.addEventListener('click', function() {
                loadPage('transactions', 'dashboard');
                setTimeout(function() {
                    document.getElementById('filter-collection').value = c.id;
                    loadTransactions(1);
                }, 100);
            });
            generalGrid.appendChild(card);
        });
    }

    // Render Event Collections
    var eventsSection = document.getElementById('events-section');
    var eventsScroll = document.getElementById('events-scroll');
    var eventsCount = document.getElementById('events-count');
    eventsScroll.innerHTML = '';
    if (eventColls.length === 0) {
        eventsSection.style.display = 'none';
    } else {
        eventsSection.style.display = 'block';
        eventsCount.textContent = eventColls.length;
        eventColls.forEach(function(c) {
            var card = document.createElement('div');
            card.className = 'event-card' + (isArch ? ' archived' : '');
            card.innerHTML =
                '<div class="event-card-accent"></div>' +
                '<div class="event-card-name">' + c.name + (isArch ? '<span class="archived-badge">Завершён</span>' : '') + '</div>' +
                '<div class="event-card-amount">' + fmtMoney(c.income) + '</div>' +
                '<div class="event-card-info">' +
                    (c.payers_count > 0 ? '<span>' + c.payers_count + ' сдали</span>' : '') +
                    (c.expense > 0 ? '<span>Расход: ' + fmtMoney(c.expense) + '</span>' : '') +
                '</div>';
            card.addEventListener('click', function() {
                loadPage('transactions', 'dashboard');
                setTimeout(function() {
                    document.getElementById('filter-collection').value = c.id;
                    loadTransactions(1);
                }, 100);
            });
            eventsScroll.appendChild(card);
        });
    }
}

async function loadDashboard() {
    try {
        var data = await apiCall('/dashboard');

        // Hero balance
        document.getElementById('stat-balance').textContent = fmtMoney(data.balance);
        document.getElementById('stat-income').textContent = fmtMoney(data.total_income);
        document.getElementById('stat-expense').textContent = fmtMoney(data.total_expense);

        var total = data.total_income + data.total_expense || 1;
        var incPct = Math.round(data.total_income / total * 100);
        var expPct = 100 - incPct;
        document.getElementById('ratio-bar').innerHTML =
            '<div class="ratio-seg ratio-seg-income" style="width:' + incPct + '%"></div>' +
            '<div class="ratio-seg ratio-seg-expense" style="width:' + expPct + '%"></div>';

        // Store data for toggle re-render
        _dashData = data;
        renderCollections(data);

        // Donut
        var donutEl = document.getElementById('donut-chart');
        var legendEl = document.getElementById('donut-legend');
        donutEl.innerHTML = '';
        legendEl.innerHTML = '';
        var cats = data.expense_by_category;
        if (cats.length === 0) {
            donutEl.style.background = 'rgba(255,255,255,0.04)';
            donutEl.innerHTML = '<div class="donut-center"><span>Нет<br>расходов</span></div>';
        } else {
            var totalExp = cats.reduce(function(s, i) { return s + i.amount; }, 0);
            var gradParts = [];
            var angle = 0;
            cats.forEach(function(item, i) {
                var color = EXPENSE_COLORS[i % EXPENSE_COLORS.length];
                var deg = totalExp ? (item.amount / totalExp * 360) : 0;
                gradParts.push(color + ' ' + angle + 'deg ' + (angle + deg) + 'deg');
                angle += deg;
                var pct = totalExp ? Math.round(item.amount / totalExp * 100) : 0;
                legendEl.innerHTML += '<div class="donut-leg-item" data-category="' + item.category + '">' +
                    '<div class="donut-leg-color" style="background:' + color + '"></div>' +
                    '<span class="donut-leg-name">' + item.category + '</span>' +
                    '<span class="donut-leg-val">' + fmtMoney(item.amount) + ' <small style="color:var(--text-3);font-weight:500">' + pct + '%</small></span></div>';
            });
            donutEl.style.background = 'conic-gradient(' + gradParts.join(', ') + ')';
            donutEl.innerHTML = '<div class="donut-center"><b>' + shortNum(totalExp) + ' \u20bd</b>Итого</div>';
        }

        legendEl.querySelectorAll('.donut-leg-item').forEach(function(el) {
            el.addEventListener('click', function() {
                var cat = el.getAttribute('data-category');
                loadPage('transactions', 'dashboard');
                setTimeout(function() {
                    document.getElementById('filter-type').value = 'expense';
                    var cf = document.getElementById('filter-category');
                    if (cf) cf.value = cat;
                    loadTransactions(1);
                }, 150);
            });
        });

        // Recent transactions
        dashRecentTxs = data.recent_transactions;
        var txEl = document.getElementById('recent-transactions');
        txEl.innerHTML = '';
        if (data.recent_transactions.length === 0) {
            txEl.innerHTML = '<div class="dash-empty">Нет операций</div>';
        }
        data.recent_transactions.forEach(function(tx, idx) {
            var inc = tx.type === 'income';
            var sign = inc ? '+' : '-';
            var cls = inc ? 'tx-income' : 'tx-expense';
            var icon = inc ? '\u2191' : '\u2193';
            var title = tx.payer_name || tx.description || tx.collection_name || (inc ? 'Взнос' : 'Расход');
            var sub = [tx.collection_name, new Date(tx.date).toLocaleDateString()].filter(Boolean).join(' \u00b7 ');
            txEl.innerHTML += '<div class="tx-card ' + cls + '" data-dash-idx="' + idx + '">' +
                '<div class="tx-card-icon">' + icon + '</div>' +
                '<div class="tx-card-info">' +
                    '<div class="tx-card-title">' + title + '</div>' +
                    '<div class="tx-card-sub">' + sub + '</div>' +
                '</div>' +
                '<div class="tx-card-amount ' + (inc ? 'text-income' : 'text-expense') + '">' + sign + fmtMoney(tx.amount) + '</div></div>';
        });
        txEl.querySelectorAll('.tx-card').forEach(function(el) {
            el.addEventListener('click', function() {
                var idx = parseInt(el.getAttribute('data-dash-idx'));
                if (dashRecentTxs[idx]) showDetail(dashRecentTxs[idx]);
            });
        });

    } catch (e) {
        console.error('Dashboard load error', e);
    }
}

// --- Detail Modal ---
function showDetail(tx) {
    var body = document.getElementById('detail-body');
    var isIncome = tx.type === 'income';
    var badgeCls = isIncome ? 'income' : 'expense';
    var typeLabel = isIncome ? 'Взнос' : 'Расход';
    var sign = isIncome ? '+' : '-';

    var html = '<div class="detail-badge ' + badgeCls + '">' + typeLabel + '</div>';
    html += '<div class="detail-amount ' + (isIncome ? 'text-income' : 'text-expense') + '">' + sign + fmtMoney(tx.amount) + '</div>';
    html += '<div class="detail-grid">';
    if (tx.payer_name && tx.payer_name !== '\u2014' && tx.payer_name !== '') {
        html += '<div class="detail-field"><div class="detail-label">За кого</div><div class="detail-value">' + tx.payer_name + '</div></div>';
    }
    if (tx.collection_name && tx.collection_name !== '\u2014' && tx.collection_name !== '') {
        html += '<div class="detail-field"><div class="detail-label">Сбор</div><div class="detail-value">' + tx.collection_name + '</div></div>';
    }
    if (tx.category) {
        html += '<div class="detail-field"><div class="detail-label">Категория</div><div class="detail-value">' + tx.category + '</div></div>';
    }
    if (tx.date) {
        html += '<div class="detail-field"><div class="detail-label">Дата</div><div class="detail-value">' + new Date(tx.date).toLocaleDateString() + '</div></div>';
    }
    if (tx.created_by_name && tx.created_by_name !== '\u2014' && tx.created_by_name !== '') {
        html += '<div class="detail-field"><div class="detail-label">Записал(а)</div><div class="detail-value">' + tx.created_by_name + '</div></div>';
    }
    html += '</div>';
    if (tx.description) {
        html += '<div class="detail-field" style="margin-top:16px"><div class="detail-label">Описание</div><div class="detail-value">' + tx.description + '</div></div>';
    }
    if (tx.photo_path) {
        var photoPaths = tx.photo_path.split(',').filter(Boolean);
        html += '<div class="detail-field" style="margin-top:16px"><div class="detail-label">Фото чека</div><div class="detail-photos">';
        photoPaths.forEach(function(p) {
            html += '<img class="detail-photo" src="/uploads/' + p.trim() + '" alt="Чек" data-path="' + p.trim() + '">';
        });
        html += '</div></div>';
    }
    body.innerHTML = html;
    document.getElementById('detail-modal').classList.add('active');
    document.body.style.overflow = 'hidden';
    document.getElementById('content').style.overflow = 'hidden';
    body.querySelectorAll('.detail-photo').forEach(function(dp) {
        dp.addEventListener('click', function() { viewPhoto(dp.getAttribute('data-path')); });
    });
}

function closeDetail() {
    document.getElementById('detail-modal').classList.remove('active');
    document.body.style.overflow = '';
    document.getElementById('content').style.overflow = '';
}

document.querySelector('.detail-close')?.addEventListener('click', closeDetail);
document.getElementById('detail-modal')?.addEventListener('click', function(e) {
    if (e.target === this) closeDetail();
});

// --- Transactions ---
async function loadCollections() {
    try {
        collections = await apiCall('/collections');
        var filterColl = document.getElementById('filter-collection');
        var currentVal = filterColl.value;
        filterColl.innerHTML = '<option value="">Все сборы</option>';
        collections.forEach(function(c) {
            var opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = c.name + (c.collection_type === 'event' ? ' (целевой)' : '');
            filterColl.appendChild(opt);
        });
        filterColl.value = currentVal;

        var modalColl = document.getElementById('tx-collection');
        modalColl.innerHTML = '<option value="">\u2014 Выбрать сбор \u2014</option><option value="new">+ Новый тип (вручную)...</option>';
        collections.forEach(function(c) {
            var opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = c.name;
            modalColl.appendChild(opt);
        });
    } catch (e) { }
}

async function loadCategories() {
    try {
        var cats = await apiCall('/categories');
        var filterCat = document.getElementById('filter-category');
        if (!filterCat) return;
        var currentVal = filterCat.value;
        filterCat.innerHTML = '<option value="">Все категории</option>';
        cats.forEach(function(c) {
            var opt = document.createElement('option');
            opt.value = c;
            opt.textContent = c;
            filterCat.appendChild(opt);
        });
        filterCat.value = currentVal;
    } catch (e) { }
}

async function loadTransactions(page) {
    page = page || 1;
    var type = document.getElementById('filter-type').value;
    var collectionId = document.getElementById('filter-collection').value;
    var category = document.getElementById('filter-category')?.value || '';

    await loadCollections();
    await loadCategories();

    try {
        var query = new URLSearchParams({ page: page, per_page: 20 });
        if (type) query.append('type', type);
        if (collectionId) query.append('collection_id', collectionId);
        if (category) query.append('category', category);

        var data = await apiCall('/transactions?' + query);
        currentPage = data.page;
        totalPages = data.pages;
        currentTransactions = data.items;

        renderTransactionsTable(data.items);
        renderTransactionsCards(data.items);
        renderPagination(data.page, data.pages);
    } catch (e) {
        console.error('Load tx error', e);
    }
}

function renderTransactionsTable(items) {
    var tbody = document.getElementById('transactions-body');
    tbody.innerHTML = '';
    items.forEach(function(tx) {
        var row = document.createElement('tr');
        row.className = 'tx-row-clickable';
        var isIncome = tx.type === 'income';
        var amountClass = isIncome ? 'text-income' : 'text-expense';
        var prefix = isIncome ? '+' : '-';
        var photoHtml = '';
        if (tx.photo_path) {
            var _pp = tx.photo_path.split(',').filter(Boolean);
            var _first = _pp[0].trim();
            var _label = _pp.length > 1 ? 'Фото (' + _pp.length + ')' : 'Фото';
            photoHtml = '<span class="check-link" onclick="event.stopPropagation();viewPhoto(\'' + _first + '\')">' + _label + '</span>';
        }
        var actionsHtml = '';
        var canEdit = currentUser.role === 'admin' || (currentUser.role === 'treasurer' && tx.created_by_name === currentUser.name);
        if (canEdit) {
            actionsHtml = '<button class="btn-action btn-edit" onclick="event.stopPropagation();editTx(' + tx.id + ')">Ред.</button>';
        }
        if (currentUser.role === 'admin') {
            actionsHtml += ' <button class="btn-action btn-delete" onclick="event.stopPropagation();deleteTx(' + tx.id + ')">Уд.</button>';
        }
        var desc = tx.description ? '<small style="color:var(--text-3);display:block">' + tx.description + '</small>' : '';
        row.innerHTML =
            '<td>' + new Date(tx.date).toLocaleDateString() + '</td>' +
            '<td class="' + amountClass + '" style="font-weight:600">' + prefix + fmtMoney(tx.amount) + '</td>' +
            '<td>' +
                '<div style="font-weight:500">' + tx.payer_name + '</div>' +
                '<small style="color:var(--text-3)">' + tx.collection_name + '</small>' +
                desc +
            '</td>' +
            '<td>' + photoHtml + '</td>' +
            '<td class="col-actions">' + actionsHtml + '</td>';
        row.addEventListener('click', function() { showDetail(tx); });
        tbody.appendChild(row);
    });
}

function renderTransactionsCards(items) {
    var container = document.getElementById('transactions-cards');
    if (!container) return;
    container.innerHTML = '';
    items.forEach(function(tx) {
        var isIncome = tx.type === 'income';
        var cls = isIncome ? 'tx-income' : 'tx-expense';
        var amountCls = isIncome ? 'text-income' : 'text-expense';
        var prefix = isIncome ? '+' : '-';
        var icon = isIncome ? '\u2191' : '\u2193';
        var card = document.createElement('div');
        card.className = 'tx-card-m ' + cls;
        var title = tx.payer_name && tx.payer_name !== '\u2014' ? tx.payer_name : (tx.category || tx.description || (isIncome ? 'Взнос' : 'Расход'));
        var subParts = [];
        if (tx.collection_name && tx.collection_name !== '\u2014') subParts.push(tx.collection_name);
        if (tx.category && tx.payer_name && tx.payer_name !== '\u2014') subParts.push(tx.category);
        var sub = subParts.join(' \u00b7 ');
        var descHtml = tx.description ? '<div class="tx-card-m-desc">' + tx.description + '</div>' : '';
        var footerHtml = '';
        var canEdit = currentUser.role === 'admin' || (currentUser.role === 'treasurer' && tx.created_by_name === currentUser.name);
        var hasActions = canEdit || currentUser.role === 'admin' || tx.photo_path;
        if (hasActions) {
            footerHtml = '<div class="tx-card-m-footer">';
            if (canEdit) footerHtml += '<button class="btn-action btn-edit" onclick="event.stopPropagation();editTx(' + tx.id + ')">Ред.</button>';
            if (currentUser.role === 'admin') footerHtml += '<button class="btn-action btn-delete" onclick="event.stopPropagation();deleteTx(' + tx.id + ')">Уд.</button>';
            if (tx.photo_path) {
                var _cp = tx.photo_path.split(',').filter(Boolean);
                var _cf = _cp[0].trim();
                var _cl = _cp.length > 1 ? 'Фото (' + _cp.length + ')' : 'Фото';
                footerHtml += '<span class="check-link" onclick="event.stopPropagation();viewPhoto(\'' + _cf + '\')">' + _cl + '</span>';
            }
            footerHtml += '</div>';
        }
        card.innerHTML =
            '<div class="tx-card-m-top">' +
                '<span class="tx-card-m-icon ' + cls + '">' + icon + '</span>' +
                '<span class="tx-card-m-amount ' + amountCls + '">' + prefix + fmtMoney(tx.amount) + '</span>' +
                '<span class="tx-card-m-date">' + new Date(tx.date).toLocaleDateString() + '</span>' +
            '</div>' +
            '<div class="tx-card-m-body">' +
                '<div class="tx-card-m-name">' + title + '</div>' +
                (sub ? '<div class="tx-card-m-sub">' + sub + '</div>' : '') +
                descHtml +
            '</div>' + footerHtml;
        card.addEventListener('click', function() { showDetail(tx); });
        container.appendChild(card);
    });
}

function renderPagination(current, total) {
    var container = document.getElementById('pagination');
    container.innerHTML = '';
    if (total <= 1) return;
    if (current > 1) {
        var prev = document.createElement('button');
        prev.className = 'btn btn-secondary';
        prev.textContent = '\u2190';
        prev.onclick = function() { loadTransactions(current - 1); };
        container.appendChild(prev);
    }
    var pageInfo = document.createElement('span');
    pageInfo.style.cssText = 'margin:0 10px;color:var(--text-2);font-size:14px';
    pageInfo.textContent = current + ' / ' + total;
    container.appendChild(pageInfo);
    if (current < total) {
        var next = document.createElement('button');
        next.className = 'btn btn-secondary';
        next.textContent = '\u2192';
        next.onclick = function() { loadTransactions(current + 1); };
        container.appendChild(next);
    }
}

document.getElementById('filter-type').addEventListener('change', function() { loadTransactions(1); });
document.getElementById('filter-collection').addEventListener('change', function() { loadTransactions(1); });
document.getElementById('filter-category')?.addEventListener('change', function() { loadTransactions(1); });

// --- Transaction Modal ---
var modalOverlay = document.getElementById('modal-overlay');
var txForm = document.getElementById('tx-form');
var photoPreview = document.getElementById('photo-preview');

document.getElementById('btn-add-tx').addEventListener('click', function() { openModal(); });
document.querySelectorAll('.modal-close').forEach(function(b) { b.addEventListener('click', closeModal); });

document.querySelectorAll('input[name="type"]').forEach(function(radio) {
    radio.addEventListener('change', function(e) {
        var isIncome = e.target.value === 'income';
        document.getElementById('group-payer').style.display = isIncome ? 'block' : 'none';
        document.getElementById('group-category').style.display = isIncome ? 'none' : 'block';
        if (!isIncome) document.getElementById('tx-payer').value = '';
        if (isIncome) document.getElementById('tx-category').value = '';
    });
});

document.getElementById('tx-collection').addEventListener('change', function(e) {
    document.getElementById('group-new-collection').style.display = e.target.value === 'new' ? 'block' : 'none';
});

function renderExistingPhotos(photoPath) {
    var gallery = document.getElementById('photo-gallery');
    gallery.innerHTML = '';
    photoPreview.innerHTML = '';
    existingPhotos = [];
    pendingDeletePhotos = [];
    document.getElementById('tx-photo').value = '';
    if (!photoPath) return;
    var paths = photoPath.split(',').filter(Boolean);
    existingPhotos = paths.map(function(p) { return p.trim(); });
    existingPhotos.forEach(function(p) {
        var item = document.createElement('div');
        item.className = 'photo-gallery-item';
        item.setAttribute('data-photo', p);
        item.innerHTML = '<img src="/uploads/' + p + '" alt="">' +
            '<button type="button" class="photo-remove">\u2715</button>';
        item.querySelector('.photo-remove').addEventListener('click', function() {
            pendingDeletePhotos.push(p);
            item.remove();
        });
        item.querySelector('img').addEventListener('click', function(e) {
            e.preventDefault();
            viewPhoto(p);
        });
        gallery.appendChild(item);
    });
}

function openModal(tx) {
    tx = tx || null;
    document.getElementById('tx-id').value = tx ? tx.id : '';
    document.getElementById('modal-title').textContent = tx ? 'Редактировать' : 'Новая операция';
    if (tx) {
        document.querySelector('input[name="type"][value="' + tx.type + '"]').checked = true;
        document.getElementById('tx-amount').value = tx.amount;
        document.getElementById('tx-collection').value = tx.collection_id || '';
        document.getElementById('tx-payer').value = tx.payer_name === '\u2014' ? '' : tx.payer_name;
        document.getElementById('tx-description').value = tx.description || '';
        document.getElementById('tx-date').value = tx.date.split('T')[0];
        document.getElementById('group-payer').style.display = tx.type === 'income' ? 'block' : 'none';
        document.getElementById('group-category').style.display = tx.type === 'expense' ? 'block' : 'none';
        document.getElementById('group-new-collection').style.display = 'none';
        document.getElementById('tx-category').value = tx.category || '';
        document.getElementById('tx-category-custom').value = '';
        document.querySelectorAll('.cat-chip').forEach(function(ch) {
            ch.classList.toggle('active', ch.getAttribute('data-cat') === (tx.category || ''));
        });
        if (tx.category && !document.querySelector('.cat-chip.active')) {
            document.getElementById('tx-category-custom').value = tx.category;
        }
        renderExistingPhotos(tx.photo_path);
    } else {
        txForm.reset();
        document.getElementById('type-income').checked = true;
        document.getElementById('group-payer').style.display = 'block';
        document.getElementById('group-category').style.display = 'none';
        document.getElementById('group-new-collection').style.display = 'none';
        document.getElementById('tx-date').valueAsDate = new Date();
        photoPreview.innerHTML = '';
        document.getElementById('photo-gallery').innerHTML = '';
        existingPhotos = [];
        pendingDeletePhotos = [];
    }
    modalOverlay.classList.add('active');
    document.body.style.overflow = 'hidden';
    document.getElementById('content').style.overflow = 'hidden';
}

function closeModal() {
    modalOverlay.classList.remove('active');
    document.body.style.overflow = '';
    document.getElementById('content').style.overflow = '';
}

document.getElementById('tx-photo').addEventListener('change', function(e) {
    var files = e.target.files;
    for (var i = 0; i < files.length; i++) {
        (function(file) {
            var reader = new FileReader();
            reader.onload = function(ev) {
                var item = document.createElement('div');
                item.className = 'photo-gallery-item pending';
                item.innerHTML = '<img src="' + ev.target.result + '" alt="Preview"><button type="button" class="photo-remove">\u2715</button>';
                item.querySelector('.photo-remove').addEventListener('click', function() { item.remove(); });
                photoPreview.appendChild(item);
            };
            reader.readAsDataURL(file);
        })(files[i]);
    }
});

txForm.addEventListener('submit', async function(e) {
    e.preventDefault();
    var submitBtn = txForm.querySelector('button[type="submit"]');
    if (submitBtn.disabled) return;
    submitBtn.disabled = true;
    submitBtn.textContent = 'Сохранение...';

    var id = document.getElementById('tx-id').value;
    var formData = new FormData();
    var type = document.querySelector('input[name="type"]:checked').value;
    formData.append('type', type);
    formData.append('amount', document.getElementById('tx-amount').value);

    var collVal = document.getElementById('tx-collection').value;
    if (collVal === 'new') {
        formData.append('collection_name', document.getElementById('tx-new-collection').value);
        var collType = document.querySelector('input[name="new_coll_type"]:checked');
        if (collType) formData.append('collection_type', collType.value);
    } else if (collVal) {
        formData.append('collection_id', collVal);
    }

    formData.append('payer_name', document.getElementById('tx-payer').value);
    var catVal = document.getElementById('tx-category').value || document.getElementById('tx-category-custom').value;
    if (catVal) formData.append('category', catVal);
    formData.append('description', document.getElementById('tx-description').value);
    formData.append('date', document.getElementById('tx-date').value);

    var photoInput = document.getElementById('tx-photo');
    var pendingItems = photoPreview.querySelectorAll('.photo-gallery-item.pending');
    if (photoInput.files.length > 0 && pendingItems.length > 0) {
        for (var pi = 0; pi < photoInput.files.length; pi++) {
            formData.append('photos', photoInput.files[pi]);
        }
    }
    if (pendingDeletePhotos.length > 0) {
        formData.append('delete_photos', pendingDeletePhotos.join(','));
    }

    try {
        var url = id ? '/transactions/' + id : '/transactions';
        var method = id ? 'PUT' : 'POST';
        var token = localStorage.getItem('token');
        var response = await fetch(API_URL + url, {
            method: method,
            headers: { 'Authorization': 'Bearer ' + token },
            body: formData
        });
        if (!response.ok) {
            var err = await response.json();
            throw new Error(err.detail || 'Ошибка');
        }
        closeModal();
        loadTransactions(currentPage);
        loadDashboard();
    } catch (e) {
        alert(e.message);
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Сохранить';
    }
});

window.editTx = function(id) {
    var tx = currentTransactions.find(function(t) { return t.id === id; });
    if (tx) openModal(tx);
};

window.deleteTx = async function(id) {
    if (!confirm('Удалить эту операцию?')) return;
    try {
        await apiCall('/transactions/' + id, { method: 'DELETE' });
        loadTransactions(currentPage);
        loadDashboard();
    } catch (e) {
        alert(e.message);
    }
};

// === Photo Viewer with Zoom/Pan ===
var _pv = { scale: 1, tx: 0, ty: 0, pinchDist: 0, dragging: false, dragStart: {x:0,y:0}, lastTap: 0, mouseDown: false };
var _pvModal = document.getElementById('photo-modal');
var _pvImg = document.getElementById('photo-viewer-img');

function _pvUpdate() {
    _pvImg.style.transform = 'translate(' + _pv.tx + 'px,' + _pv.ty + 'px) scale(' + _pv.scale + ')';
}
function _pvReset() {
    _pv.scale = 1; _pv.tx = 0; _pv.ty = 0;
    _pvImg.style.transform = '';
    _pvImg.classList.remove('dragging');
}

window.viewPhoto = function(path) {
    _pvImg.src = '/uploads/' + path;
    _pvReset();
    _pvModal.classList.add('active');
    document.body.style.overflow = 'hidden';
    document.getElementById('content').style.overflow = 'hidden';
};

function _pvClose() {
    _pvModal.classList.remove('active');
    _pvReset();
    document.body.style.overflow = '';
    document.getElementById('content').style.overflow = '';
}

document.querySelector('.photo-close').addEventListener('click', function(e) {
    e.stopPropagation();
    _pvClose();
});

// Close on background click (not on image) when not zoomed
_pvModal.addEventListener('click', function(e) {
    if (_pv.scale <= 1 && (e.target === _pvModal || e.target.classList.contains('photo-viewer'))) {
        _pvClose();
    }
});

// Escape key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && _pvModal.classList.contains('active')) _pvClose();
});

// --- Touch: pinch-zoom, pan, double-tap ---
_pvModal.addEventListener('touchstart', function(e) {
    if (e.touches.length === 2) {
        e.preventDefault();
        _pv.pinchDist = Math.hypot(
            e.touches[0].clientX - e.touches[1].clientX,
            e.touches[0].clientY - e.touches[1].clientY
        );
    } else if (e.touches.length === 1 && _pv.scale > 1) {
        _pv.dragging = true;
        _pv.dragStart.x = e.touches[0].clientX - _pv.tx;
        _pv.dragStart.y = e.touches[0].clientY - _pv.ty;
    }
}, { passive: false });

_pvModal.addEventListener('touchmove', function(e) {
    if (e.touches.length === 2 && _pv.pinchDist > 0) {
        e.preventDefault();
        var dist = Math.hypot(
            e.touches[0].clientX - e.touches[1].clientX,
            e.touches[0].clientY - e.touches[1].clientY
        );
        _pv.scale = Math.max(1, Math.min(6, _pv.scale * (dist / _pv.pinchDist)));
        _pv.pinchDist = dist;
        if (_pv.scale <= 1) { _pv.tx = 0; _pv.ty = 0; }
        _pvUpdate();
    } else if (e.touches.length === 1 && _pv.dragging && _pv.scale > 1) {
        e.preventDefault();
        _pv.tx = e.touches[0].clientX - _pv.dragStart.x;
        _pv.ty = e.touches[0].clientY - _pv.dragStart.y;
        _pvUpdate();
    }
}, { passive: false });

_pvModal.addEventListener('touchend', function(e) {
    if (e.touches.length < 2) _pv.pinchDist = 0;
    _pv.dragging = false;
    if (_pv.scale <= 1.05) { _pv.scale = 1; _pv.tx = 0; _pv.ty = 0; _pvUpdate(); }
    // Double tap to zoom
    if (e.changedTouches.length === 1 && e.touches.length === 0) {
        var now = Date.now();
        if (now - _pv.lastTap < 300) {
            e.preventDefault();
            if (_pv.scale > 1.1) {
                _pvReset(); _pvUpdate();
            } else {
                _pv.scale = 2.5;
                var rect = _pvImg.getBoundingClientRect();
                var tapX = e.changedTouches[0].clientX - rect.left - rect.width / 2;
                var tapY = e.changedTouches[0].clientY - rect.top - rect.height / 2;
                _pv.tx = -tapX * (_pv.scale - 1);
                _pv.ty = -tapY * (_pv.scale - 1);
                _pvUpdate();
            }
            _pv.lastTap = 0;
        } else {
            _pv.lastTap = now;
        }
    }
});

// --- Mouse: wheel zoom, click+drag pan ---
_pvModal.addEventListener('wheel', function(e) {
    e.preventDefault();
    var factor = e.deltaY > 0 ? 0.9 : 1.1;
    _pv.scale = Math.max(1, Math.min(6, _pv.scale * factor));
    if (_pv.scale <= 1) { _pv.tx = 0; _pv.ty = 0; }
    _pvUpdate();
}, { passive: false });

_pvImg.addEventListener('mousedown', function(e) {
    if (_pv.scale > 1) {
        e.preventDefault();
        _pv.mouseDown = true;
        _pv.dragStart.x = e.clientX - _pv.tx;
        _pv.dragStart.y = e.clientY - _pv.ty;
        _pvImg.classList.add('dragging');
    }
});
document.addEventListener('mousemove', function(e) {
    if (_pv.mouseDown && _pv.scale > 1) {
        _pv.tx = e.clientX - _pv.dragStart.x;
        _pv.ty = e.clientY - _pv.dragStart.y;
        _pvUpdate();
    }
});
document.addEventListener('mouseup', function() {
    _pv.mouseDown = false;
    _pvImg.classList.remove('dragging');
});

// --- Users ---
async function loadUsers() {
    try {
        var users = await apiCall('/users');
        var tbody = document.getElementById('users-body');
        tbody.innerHTML = '';
        users.forEach(function(u) {
            var row = document.createElement('tr');
            row.innerHTML =
                '<td style="font-weight:500">' + u.name + '</td>' +
                '<td style="color:var(--text-3);font-size:13px">' + u.telegram_id + '</td>' +
                '<td>' +
                    '<select onchange="updateRole(' + u.id + ', this.value)" class="input" style="padding:6px 10px;width:auto">' +
                        '<option value="viewer"' + (u.role === 'viewer' ? ' selected' : '') + '>Наблюдатель</option>' +
                        '<option value="treasurer"' + (u.role === 'treasurer' ? ' selected' : '') + '>Казначей</option>' +
                        '<option value="admin"' + (u.role === 'admin' ? ' selected' : '') + '>Администратор</option>' +
                    '</select>' +
                '</td>' +
                '<td>\u2014</td>';
            tbody.appendChild(row);
        });
    } catch (e) {
        console.error('Load users error', e);
    }
}

window.updateRole = async function(userId, newRole) {
    try {
        var formData = new FormData();
        formData.append('role', newRole);
        var token = localStorage.getItem('token');
        var response = await fetch(API_URL + '/users/' + userId + '/role', {
            method: 'PUT',
            headers: { 'Authorization': 'Bearer ' + token },
            body: formData
        });
        if (!response.ok) {
            var text = await response.text();
            var detail;
            try { detail = JSON.parse(text).detail; } catch(e) { detail = text; }
            alert('Ошибка: ' + (detail || response.statusText));
            loadUsers();
            return;
        }
        if (currentUser.id === userId) {
            alert('Роль изменена. Страница будет перезагружена.');
            window.location.reload();
        } else {
            loadUsers();
        }
    } catch (e) {
        alert('Ошибка обновления роли');
        loadUsers();
    }
};

// Category chips
document.querySelectorAll('.cat-chip').forEach(function(chip) {
    chip.addEventListener('click', function() {
        var wasActive = chip.classList.contains('active');
        document.querySelectorAll('.cat-chip').forEach(function(c) { c.classList.remove('active'); });
        if (!wasActive) {
            chip.classList.add('active');
            document.getElementById('tx-category').value = chip.getAttribute('data-cat');
            document.getElementById('tx-category-custom').value = '';
        } else {
            document.getElementById('tx-category').value = '';
        }
    });
});
document.getElementById('tx-category-custom').addEventListener('input', function() {
    document.querySelectorAll('.cat-chip').forEach(function(c) { c.classList.remove('active'); });
    document.getElementById('tx-category').value = this.value;
});

// Mobile user dropdown
document.getElementById('mobile-user-btn')?.addEventListener('click', function(e) {
    e.stopPropagation();
    document.getElementById('user-dropdown').classList.toggle('open');
});
document.addEventListener('click', function() {
    document.getElementById('user-dropdown')?.classList.remove('open');
});
document.getElementById('btn-logout-mobile')?.addEventListener('click', logout);

// --- Toast ---
function showToast(message, type) {
    type = type || 'info';
    var container = document.getElementById('toast-container');
    var toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(function() {
        toast.classList.add('toast-out');
        setTimeout(function() { toast.remove(); }, 300);
    }, 3000);
}

// --- Compliance ---
var _complLoaded = false;

function initCompliancePage() {
    if (!_complLoaded) {
        _complLoaded = true;
        // Set default dates: 1 Jan of current year to today
        var now = new Date();
        var yearStart = now.getFullYear() + '-01-01';
        var today = now.toISOString().split('T')[0];
        document.getElementById('compl-date-from').value = yearStart;
        document.getElementById('compl-date-to').value = today;

        document.getElementById('compl-btn-load').addEventListener('click', loadCompliance);
        document.getElementById('compl-btn-export').addEventListener('click', exportCompliance);
        document.getElementById('compl-btn-export-zip').addEventListener('click', exportComplianceZip);
    }
}

async function loadCompliance() {
    var dateFrom = document.getElementById('compl-date-from').value;
    var dateTo = document.getElementById('compl-date-to').value;
    if (!dateFrom || !dateTo) {
        showToast('Укажите период', 'error');
        return;
    }

    var loadingEl = document.getElementById('compl-loading');
    var emptyEl = document.getElementById('compl-empty');
    var resultsEl = document.getElementById('compl-results');
    var exportBtn = document.getElementById('compl-btn-export');
    var exportZipBtn = document.getElementById('compl-btn-export-zip');

    loadingEl.style.display = 'block';
    emptyEl.style.display = 'none';
    resultsEl.style.display = 'none';
    exportBtn.disabled = true;
    exportZipBtn.disabled = true;

    try {
        var params = 'date_from=' + dateFrom + '&date_to=' + dateTo;
        var [summary, collSummary, payers] = await Promise.all([
            apiCall('/compliance/summary?' + params),
            apiCall('/compliance/collections-summary?' + params),
            apiCall('/compliance/payers?' + params),
        ]);

        loadingEl.style.display = 'none';

        if (summary.transaction_count === 0) {
            emptyEl.style.display = 'block';
            return;
        }

        resultsEl.style.display = 'block';
        exportBtn.disabled = false;
        exportZipBtn.disabled = false;

        // Summary cards
        document.getElementById('compl-income').textContent = fmtMoney(summary.total_income);
        document.getElementById('compl-expense').textContent = fmtMoney(summary.total_expense);
        document.getElementById('compl-balance').textContent = fmtMoney(summary.balance);
        document.getElementById('compl-tx-count').textContent = summary.transaction_count;

        // Categories
        var catEl = document.getElementById('compl-categories');
        catEl.innerHTML = '';
        if (summary.expense_by_category.length === 0) {
            catEl.innerHTML = '<div class="stats-empty">Нет расходов</div>';
        } else {
            var maxCat = Math.max.apply(null, summary.expense_by_category.map(function(c) { return c.amount; }));
            var catColors = ['#7c5cfc','#60a5fa','#00d4aa','#f59e0b','#fb923c','#ff6b6b','#f472b6','#94a3b8'];
            summary.expense_by_category.forEach(function(c, i) {
                var pct = maxCat > 0 ? Math.round(c.amount / maxCat * 100) : 0;
                var color = catColors[i % catColors.length];
                var row = document.createElement('div');
                row.className = 'compl-cat-row';
                row.innerHTML =
                    '<div class="compl-cat-name">' + c.category + '</div>' +
                    '<div class="compl-cat-bar"><div class="compl-cat-fill" style="width:' + pct + '%;background:' + color + '">' +
                    (pct > 25 ? '<span class="compl-cat-val">' + fmtMoney(c.amount) + '</span>' : '') +
                    '</div></div>' +
                    (pct <= 25 ? '<span class="compl-cat-val-out">' + fmtMoney(c.amount) + '</span>' : '');
                catEl.appendChild(row);
            });
        }

        // Collections table
        var collEl = document.getElementById('compl-collections');
        if (collSummary.length === 0) {
            collEl.innerHTML = '<div class="stats-empty">Нет данных</div>';
        } else {
            var html = '<table class="compl-table"><thead><tr><th>Сбор</th><th class="text-right">Поступления</th><th class="text-right">Расходы</th><th class="text-right">Баланс</th><th class="text-right">Операций</th></tr></thead><tbody>';
            collSummary.forEach(function(c) {
                var balClass = c.balance >= 0 ? 'text-income' : 'text-expense';
                html += '<tr><td>' + c.name + '</td><td class="text-right text-income">' + fmtMoney(c.income) + '</td><td class="text-right text-expense">' + fmtMoney(c.expense) + '</td><td class="text-right ' + balClass + '" style="font-weight:600">' + fmtMoney(c.balance) + '</td><td class="text-right">' + c.count + '</td></tr>';
            });
            html += '</tbody></table>';
            collEl.innerHTML = html;
        }

        // Payers table
        var payEl = document.getElementById('compl-payers');
        if (payers.length === 0) {
            payEl.innerHTML = '<div class="stats-empty">Нет данных</div>';
        } else {
            var html2 = '<table class="compl-table"><thead><tr><th>За кого (ФИО ребёнка)</th><th class="text-right">Сумма</th><th class="text-right">Взносов</th><th>Сборы</th></tr></thead><tbody>';
            payers.forEach(function(p) {
                html2 += '<tr><td>' + p.payer_name + '</td><td class="text-right text-income">' + fmtMoney(p.total) + '</td><td class="text-right">' + p.count + '</td><td style="font-size:12px;color:var(--text-3)">' + p.collections.join(', ') + '</td></tr>';
            });
            html2 += '</tbody></table>';
            payEl.innerHTML = html2;
        }

        showToast('Данные загружены', 'success');
    } catch (e) {
        loadingEl.style.display = 'none';
        showToast(e.message || 'Ошибка загрузки', 'error');
    }
}

async function exportCompliance() {
    var dateFrom = document.getElementById('compl-date-from').value;
    var dateTo = document.getElementById('compl-date-to').value;
    if (!dateFrom || !dateTo) {
        showToast('Укажите период', 'error');
        return;
    }

    var btn = document.getElementById('compl-btn-export');
    btn.disabled = true;
    btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 2v8M5 7l3 3 3-3M3 12v1a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg> Формирование...';

    try {
        var token = localStorage.getItem('token');
        var res = await fetch(API_URL + '/compliance/export?date_from=' + dateFrom + '&date_to=' + dateTo, {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        if (!res.ok) {
            var err = await res.json();
            throw new Error(err.detail || 'Ошибка экспорта');
        }
        var blob = await res.blob();
        var disposition = res.headers.get('Content-Disposition') || '';
        var filenameMatch = disposition.match(/filename="?([^"]+)"?/);
        var filename = filenameMatch ? filenameMatch[1] : 'financial_report.xlsx';
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('Отчёт скачан', 'success');
    } catch (e) {
        showToast(e.message || 'Ошибка экспорта', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 2v8M5 7l3 3 3-3M3 12v1a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg> Скачать Excel';
    }
}

async function exportComplianceZip() {
    var dateFrom = document.getElementById('compl-date-from').value;
    var dateTo = document.getElementById('compl-date-to').value;
    if (!dateFrom || !dateTo) {
        showToast('Укажите период', 'error');
        return;
    }

    var btn = document.getElementById('compl-btn-export-zip');
    btn.disabled = true;
    btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M4 1h8a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1z" stroke="currentColor" stroke-width="1.5"/><path d="M7 4h2M7 6h2M7 8h2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg> Формирование...';

    try {
        var token = localStorage.getItem('token');
        var res = await fetch(API_URL + '/compliance/export-zip?date_from=' + dateFrom + '&date_to=' + dateTo, {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        if (!res.ok) {
            var err = await res.json();
            throw new Error(err.detail || 'Ошибка экспорта');
        }
        var blob = await res.blob();
        var disposition = res.headers.get('Content-Disposition') || '';
        var filenameMatch = disposition.match(/filename="?([^"]+)"?/);
        var filename = filenameMatch ? filenameMatch[1] : 'financial_report.zip';
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('Архив скачан', 'success');
    } catch (e) {
        showToast(e.message || 'Ошибка экспорта', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M4 1h8a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1z" stroke="currentColor" stroke-width="1.5"/><path d="M7 4h2M7 6h2M7 8h2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg> Скачать ZIP + фото';
    }
}

// --- Stats ---
var statsUsagePage = 1;
var ACTION_META = {
    'login_tma':    { label: 'Вошёл (TMA)',    icon: '\ud83d\udcf1', cls: 'login' },
    'login_widget': { label: 'Вошёл (виджет)', icon: '\ud83c\udf10', cls: 'login' },
    'login_bot':    { label: 'Вошёл (бот)',     icon: '\ud83e\udd16', cls: 'login' },
    'create_tx':    { label: 'Создал операцию', icon: '\u2795', cls: 'tx' },
    'update_tx':    { label: 'Изменил операцию',icon: '\u270f\ufe0f', cls: 'tx' },
    'delete_tx':    { label: 'Удалил операцию', icon: '\ud83d\uddd1\ufe0f', cls: 'delete' },
    'role_change':  { label: 'Сменил роль',     icon: '\ud83d\udc51', cls: 'role' }
};

function getActionMeta(action) {
    return ACTION_META[action] || { label: action, icon: '\ud83d\udcdd', cls: 'tx' };
}

async function loadStats() {
    try {
        var [stats, usage] = await Promise.all([
            apiCall('/admin/stats'),
            apiCall('/admin/usage?page=' + statsUsagePage + '&per_page=50')
        ]);

        document.getElementById('stat-total-users').textContent = stats.total_users;
        document.getElementById('stat-active-7d').textContent = stats.active_7d;
        document.getElementById('stat-active-30d').textContent = stats.active_30d;
        document.getElementById('stat-logins-today').textContent = stats.logins_today;

        var maxLogin = Math.max(stats.logins_tma, stats.logins_widget, stats.logins_bot, 1);
        var barsEl = document.getElementById('stats-login-bars');
        var barsData = [
            { label: 'TMA', value: stats.logins_tma, color: 'var(--primary)' },
            { label: 'Виджет', value: stats.logins_widget, color: 'var(--accent)' },
            { label: 'Бот', value: stats.logins_bot, color: '#60a5fa' }
        ];
        barsEl.innerHTML = '';
        barsData.forEach(function(b) {
            var pct = Math.round(b.value / maxLogin * 100);
            var row = document.createElement('div');
            row.className = 'stats-bar-row';
            row.innerHTML = '<div class="stats-bar-label">' + b.label + '</div>' +
                '<div class="stats-bar-track"><div class="stats-bar-fill" style="width:' + pct + '%;background:' + b.color + '">' +
                (pct > 20 ? '<span class="stats-bar-val">' + b.value + '</span>' : '') +
                '</div></div>' +
                (pct <= 20 ? '<span class="stats-bar-val-out">' + b.value + '</span>' : '');
            barsEl.appendChild(row);
        });

        document.getElementById('stat-logins-7d').textContent = stats.logins_7d;
        document.getElementById('stat-logins-30d').textContent = stats.logins_30d;
        document.getElementById('stat-tx-7d').textContent = stats.tx_created_7d;
        document.getElementById('stat-tx-30d').textContent = stats.tx_created_30d;

        var topEl = document.getElementById('stats-top-users-list');
        topEl.innerHTML = '';
        if (stats.top_users.length === 0) {
            topEl.innerHTML = '<div class="stats-empty">Нет данных</div>';
        } else {
            stats.top_users.forEach(function(u, i) {
                var item = document.createElement('div');
                item.className = 'stats-top-item';
                item.innerHTML = '<div class="stats-top-rank">' + (i + 1) + '</div>' +
                    '<div class="stats-top-name">' + u.name + '</div>' +
                    '<div class="stats-top-count">' + u.count + '</div>';
                topEl.appendChild(item);
            });
        }

        var logEl = document.getElementById('stats-usage-log');
        logEl.innerHTML = '';
        if (usage.items.length === 0) {
            logEl.innerHTML = '<div class="stats-empty">Нет записей</div>';
        } else {
            usage.items.forEach(function(e) {
                var meta = getActionMeta(e.action);
                var dt = e.created_at ? new Date(e.created_at) : null;
                var timeStr = dt ? dt.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : '';
                var dateStr = dt ? dt.toLocaleDateString() : '\u2014';
                var item = document.createElement('div');
                item.className = 'stats-log-item';
                item.innerHTML = '<div class="stats-log-icon ' + meta.cls + '">' + meta.icon + '</div>' +
                    '<div class="stats-log-body">' +
                        '<div class="stats-log-title"><strong>' + e.user_name + '</strong> ' + meta.label + '</div>' +
                        (e.details ? '<div class="stats-log-sub">' + e.details + '</div>' : '') +
                    '</div>' +
                    '<div class="stats-log-time">' + dateStr + '<br>' + timeStr + '</div>';
                logEl.appendChild(item);
            });
        }

        renderStatsPagination(usage.page, usage.pages);
    } catch (e) {
        console.error('Stats load error', e);
    }
}

function renderStatsPagination(current, total) {
    var container = document.getElementById('stats-pagination');
    container.innerHTML = '';
    if (total <= 1) return;
    if (current > 1) {
        var prev = document.createElement('button');
        prev.className = 'btn btn-secondary';
        prev.textContent = '\u2190';
        prev.onclick = function() { statsUsagePage = current - 1; loadStats(); };
        container.appendChild(prev);
    }
    var info = document.createElement('span');
    info.style.cssText = 'margin:0 10px;color:var(--text-2);font-size:14px';
    info.textContent = current + ' / ' + total;
    container.appendChild(info);
    if (current < total) {
        var next = document.createElement('button');
        next.className = 'btn btn-secondary';
        next.textContent = '\u2192';
        next.onclick = function() { statsUsagePage = current + 1; loadStats(); };
        container.appendChild(next);
    }
}

initAuth();

// Back button handler
document.getElementById('btn-back-to-dash')?.addEventListener('click', function() {
    loadPage('dashboard');
});

window.registerUser = async function() {
    var tgId = document.getElementById('reg-tg-id').value;
    var name = document.getElementById('reg-name').value;
    var role = document.getElementById('reg-role').value;
    if (!tgId) { alert('Введите Telegram ID'); return; }
    try {
        var formData = new FormData();
        formData.append('telegram_id', tgId);
        if (name) formData.append('name', name);
        formData.append('role', role);
        var token = localStorage.getItem('token');
        var res = await fetch(API_URL + '/users/register', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token },
            body: formData
        });
        var data = await res.json();
        if (res.ok) {
            alert(data.message);
            document.getElementById('reg-tg-id').value = '';
            document.getElementById('reg-name').value = '';
            document.getElementById('add-user-form').style.display = 'none';
            loadUsers();
        } else {
            alert('Ошибка: ' + (data.detail || ''));
        }
    } catch(e) {
        alert('Ошибка сети');
    }
};
